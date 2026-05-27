"""Greedy A* auto-router — orchestration layer.

Consumes the `Net`s produced by a `Board` and returns `SignalPath`s the
builder can carve. The algorithm:

  1. Discretise the routable area onto a fixed grid (0.5 mm by default).
  2. Mark cells blocked per layer based on device pockets, pin holes,
     and prior nets' inflated channel + via footprints.
  3. Route nets in priority order (signal nets before power; busier
     nets before quieter ones).
  4. For each net, daisy-chain A* from master → slave1 → slave2 → … .
     The cost function favours short axis-aligned runs on the back
     layer (L1) and penalises layer changes, edge proximity, and
     crossings.
  5. Once every net is routed and halo-blocked, a global post-pass
     collapses monotonic-quadrant cardinal staircases into 45°
     diagonals using each path's raw cell list with self-exemption.
     Running this post-route (not per-net) means each collapse sees
     every other path's footprint, so a diagonal can't carve through
     a corridor reserved for a later net.
  6. Convert the (possibly collapsed) grid path back into `Waypoint`s,
     fold consecutive same-layer same-direction steps into single
     segments, and emit a `SignalPath` per net.

This module owns the per-net + per-board orchestration. The primitives
live in sibling modules:

  - `router.grid`     — Grid dataclass + static-blocker build
  - `router.astar`    — A* search + cost weights
  - `router.blocking` — post-route halo blocking (axis + diagonal aware)
  - `router.collapse` — cells → Waypoints + 45° staircase collapse
  - `router.schedule` — per-net + per-bus routing priority
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from board.board import Board
from board.buses import Net, PinEndpoint, resolve_bus
from router.astar import _astar
from router.blocking import _block_path
from router.collapse import (
    _chamfer_pin_corners,
    _collapse_quadrant_runs,
    _path_to_waypoints,
    _simplify_wiggles,
)
from router.grid import Grid, _build_grid
from router.paths import waypoints_to_path
from router.schedule import _net_priority, _ordered_bus_actions
from vitamins.substrate import SignalPath, Via, WireSegment


@dataclass
class _RawPath:
    """Per-slave routing output, kept aside for the post-route collapse pass.

    `raw_cells` is the A* output; `own_pin_cells` and `own_pin_xys`
    snapshot the exemption sets so the post-pass forbidden_check
    matches A*'s accept rules. `halo_cells` is populated by
    `route_board` after `_block_path` runs — it carries every cell
    the path's own halo touches, so the collapse safety check can
    exempt the corner-brush cells that the diagonal would clip
    (those sit in our own halo by construction).
    """

    name: str
    raw_cells: list[tuple[int, int, int]]
    own_pin_cells: set[tuple[int, int, int]]
    own_pin_xys: set[tuple[float, float]]
    own_via_xys: set[tuple[float, float]]
    priority_pin_xys: set[tuple[float, float]]
    other_pin_blockers: set[tuple[int, int, int]]
    halo_cells: set[tuple[int, int, int]] = field(default_factory=set)


# Signals whose pin corners get an aggressive 45° chamfer on the first
# / second bend off the pin (when surrounding space permits). Bare
# copper snags on 90° bends; power/ground wires are routed against
# tight pin clusters and benefit most from the smoother corner.
# TODO: this hard-coded signal-name set is bespoke. The chamfer should
# fire automatically wherever the geometry supports it — driven by
# surrounding open quadrant size and wire gauge, not by net name —
# so I²C buses, GPIO fan-outs, etc. all benefit without an allow-list.
# Consequence of leaving as-is: only the listed power/ground nets get
# the elegant corner; every other signal still ships with 90° bends.
_PRIORITY_CHAMFER_SIGNALS: frozenset[str] = frozenset({"VCC", "3V3", "5V", "GND"})

# ---------------------------------------------------------------------------
# Failure type
# ---------------------------------------------------------------------------


class RouteFailure(Exception):
    """A net couldn't be routed. Carries the failing net + partial
    solution so the caller can surface a clear error.
    """

    def __init__(self, net: Net, reason: str, partial: tuple[SignalPath, ...]):
        super().__init__(f"{net.signal} (bus {net.bus_name!r}): {reason}")
        self.net = net
        self.reason = reason
        self.partial = partial


# ---------------------------------------------------------------------------
# Per-net routing
# ---------------------------------------------------------------------------


def _endpoint_seed_cells(g: Grid, endpoint: PinEndpoint) -> list[tuple[int, int, int]]:
    gx, gy = g.to_grid(endpoint.position.x, endpoint.position.y)
    return [(0, gy, gx), (1, gy, gx)]


def _route_one_net(
    g: Grid,
    net: Net,
    pin_cells: set[tuple[int, int, int]],
    *,
    parallel_target_cells: set[tuple[int, int, int]] | None = None,
    parallel_pitch_cells: int | None = None,
) -> list[tuple[SignalPath, _RawPath]]:
    """Route a single Net as a Steiner-style tree.

    Topology:
      - First slave: full A* from master → (must_pass waypoints) → slave.
      - Subsequent slaves: multi-source A* with starts = every cell of
        the in-progress tree. The branch takes off from the trunk at
        whichever point is cheapest — no second wire is dragged all the
        way back to the master pin.

    Each leg is still emitted as its own `SignalPath` named
    `f"{net.bus_name}_{net.signal}_{slave.instance_name}"`. The carved
    substrate sees them as a T-junction wherever a branch meets the
    trunk (segments touch but don't overlap).

    Honours `net.hint`:
      - `prefer_layer`: bias A* step cost away from the other layer.
      - `must_pass`: forced intermediate waypoints on the FIRST slave's
        route. Subsequent slaves inherit them transitively via the
        trunk.

    `parallel_target_cells`: optional cell set the cost function rewards
    being adjacent to (Phase 2 — bundled pair routing). When set, A*
    favours cells immediately next to a cell in this set, so the second
    signal of a pair (GND, SDA) tends to run alongside the first (VCC,
    SCL) at minimum wall-floor distance.
    """
    own_pin_cells: set[tuple[int, int, int]] = set()
    approach_by_pin = getattr(g, "_pin_approach_by_pin", {})
    for ep in net.endpoints:
        gx, gy = g.to_grid(ep.position.x, ep.position.y)
        own_pin_cells.add((0, gy, gx))
        own_pin_cells.add((1, gy, gx))
        # Adopt this pin's approach corridor as own — A* may step on it
        # even if a prior halo blocked the cell. (Other nets are kept
        # OUT of this corridor by the pre-block below.)
        own_pin_cells.update(approach_by_pin.get(
            (round(ep.position.x, 3), round(ep.position.y, 3)), set(),
        ))

    # Pre-block every other pin's approach corridor so this net's A*
    # can't route through space reserved for someone else's pin. Without
    # this, two adjacent pins' approach zones merge and the wall floor
    # between their two wires collapses.
    other_pin_approach: set[tuple[int, int, int]] = set()
    own_pin_xys = {
        (round(ep.position.x, 3), round(ep.position.y, 3))
        for ep in net.endpoints
    }
    for xy, cells in approach_by_pin.items():
        if xy in own_pin_xys:
            continue
        other_pin_approach.update(cells)
    # Dense-pin diagonal buffer — cells diagonally adjacent to other
    # nets' dense pins. Block them for this net so a cross-net wire
    # can't sit one cell off the dense pin where halo + approach
    # exemptions otherwise let two wires close in to 0.5 mm.
    buffer_by_pin = getattr(g, "_pin_buffer_by_pin", {})
    for xy, cells in buffer_by_pin.items():
        if xy in own_pin_xys:
            continue
        other_pin_approach.update(cells)

    # Resolve hint into A* knobs.
    must_pass_cells: list[tuple[int, int, int]] = []
    layer_step_mul = (1.0, 1.0)
    if net.hint is not None:
        if net.hint.prefer_layer is not None:
            # The non-preferred layer pays 2× per step. A* still finds a
            # path when the preferred layer is impossible — this is a
            # soft preference, not a wall.
            other = 1 if net.hint.prefer_layer == 1 else 0
            mul = list(layer_step_mul)
            mul[other] = 2.0
            layer_step_mul = (mul[0], mul[1])
        if net.hint.must_pass:
            for wp in net.hint.must_pass:
                gx, gy = g.to_grid(wp.x, wp.y)
                cell = (wp.layer - 1, gy, gx)
                must_pass_cells.append(cell)
                # Must-pass cells are sacred — A* may always step onto
                # them even if some prior blocker landed on the cell.
                own_pin_cells.add(cell)

    other_pin_blockers = (pin_cells - own_pin_cells) | (
        other_pin_approach - own_pin_cells
    )

    master_cells = _endpoint_seed_cells(g, net.master)
    trunk_cells: set[tuple[int, int, int]] = set()
    out: list[tuple[SignalPath, _RawPath]] = []
    for i, slave in enumerate(net.slaves):
        slave_cells = _endpoint_seed_cells(g, slave)

        # Build a list of `goal_cells_set` for each leg. The starting
        # cells of each leg are derived from the END of the previous
        # leg (so layer is preserved across the splice), or from the
        # initial seed for leg 0.
        leg_goals: list[set[tuple[int, int, int]]] = []
        if i == 0:
            for wp_cell in must_pass_cells:
                leg_goals.append({wp_cell})
            leg_goals.append(set(slave_cells))
            initial_starts = master_cells
        else:
            leg_goals.append(set(slave_cells))
            initial_starts = list(trunk_cells)

        full_cells: list[tuple[int, int, int]] = []
        starts = initial_starts
        for leg_no, goals in enumerate(leg_goals):
            cells = _astar(
                g, starts, goals,
                pin_cells=pin_cells - own_pin_cells,
                own_pin_cells=own_pin_cells,
                extra_blocked=other_pin_approach - own_pin_cells,
                layer_step_mul=layer_step_mul,
                parallel_target_cells=parallel_target_cells,
                parallel_pitch_cells=parallel_pitch_cells,
            )
            if cells is None:
                where = (
                    f"leg {leg_no} → waypoint" if leg_no < len(leg_goals) - 1
                    else f"final leg → {slave.instance_name}"
                )
                raise RouteFailure(
                    net, f"no path: {where}", partial=(),
                )
            if not full_cells:
                full_cells = cells
            else:
                # Skip the first cell of subsequent legs — it's the
                # waypoint that ended the previous leg, and it matches
                # full_cells[-1] exactly (same layer, same xy).
                full_cells.extend(cells[1:])
            # Next leg starts from THIS leg's actual end cell — keeps
            # layer/xy continuity across the splice.
            starts = [cells[-1]]

        trunk_cells.update(full_cells)
        # Don't collapse here — the per-net `g.blocked` state can't see
        # cells that later nets will need, so an early collapse may
        # carve a diagonal through a corridor reserved for a future
        # net. `route_board` runs `_collapse_runs_post_route` after all
        # nets are halo-blocked.
        waypoints = _path_to_waypoints(g, full_cells)
        name = f"{net.bus_name}_{net.signal}_{slave.instance_name}"
        path = waypoints_to_path(name, waypoints)
        # Layer transitions in the raw cell list mark via positions —
        # collapse needs their world xy to keep diagonals from slicing
        # into the via barrel.
        own_via_xys: set[tuple[float, float]] = set()
        for k in range(1, len(full_cells)):
            if full_cells[k][0] != full_cells[k - 1][0]:
                vwx, vwy = g.to_world(full_cells[k][2], full_cells[k][1])
                own_via_xys.add((round(vwx, 3), round(vwy, 3)))
        # Snap pin xys to the grid so the chamfer pass can match them
        # against cell-to-world coordinates (cells live on grid
        # intersections, but pins on 2.54 mm pitch don't align to the
        # 0.5 mm grid).
        priority_pin_xys: set[tuple[float, float]] = set()
        if net.signal in _PRIORITY_CHAMFER_SIGNALS:
            for ep in net.endpoints:
                pgx, pgy = g.to_grid(ep.position.x, ep.position.y)
                pwx, pwy = g.to_world(pgx, pgy)
                priority_pin_xys.add((round(pwx, 3), round(pwy, 3)))
        raw = _RawPath(
            name=name,
            raw_cells=full_cells,
            own_pin_cells=set(own_pin_cells),
            own_pin_xys=set(own_pin_xys),
            own_via_xys=own_via_xys,
            priority_pin_xys=priority_pin_xys,
            other_pin_blockers=set(other_pin_blockers),
        )
        out.append((path, raw))
        # No intra-net blocking — successive slaves of the same net
        # share the master pin and may re-use each other's trunks.
        # Cross-net halo blocking is applied by `route_board` after the
        # full net (all slaves) has been routed.
    return out


def _collapse_one_raw(
    g: Grid,
    raw: _RawPath,
    exclusive_halo: set[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    """Run the staircase → 45° collapse against the final blocker state.

    `g.blocked` now carries every routed path's halo (including this
    one's own). The forbidden_check exempts:

      - `raw_cells` — cells this path actually traverses.
      - `own_pin_cells` — this net's pin holes + approach corridors.
      - `exclusive_halo` — cells in *only* this path's halo footprint.
        Critical: the diagonal's corner-brush cells (the safety-check
        neighbours of each diagonal-interior cell) sit on the inside
        of the staircase's L-bend, squarely inside our own halo.
        Without this exemption no collapse ever fires on a run hemmed
        in by its own halo. The *exclusive* qualifier matters: cells
        in our halo *and* another path's halo can't be exempted — a
        diagonal through them would violate wall-floor against the
        neighbour wire.
    """
    raw_set = set(raw.raw_cells)
    hard_blocked: set[tuple[int, int, int]] = getattr(g, "_hard_blocked", set())

    def _forbidden(ly: int, gy: int, gx: int) -> bool:
        cell = (ly, gy, gx)
        # Hard blockers (pocket interior, edge clearance) are physical
        # impossibilities — no substrate, no carve. They must NEVER be
        # exempted, even when in our own halo. Pin cells stay routable
        # because they're not in `_hard_blocked` (the pin cell exemption
        # already happened when pockets were carved into g.blocked).
        if cell in hard_blocked:
            return True
        if cell in raw_set or cell in raw.own_pin_cells or cell in exclusive_halo:
            return False
        if g.blocked[ly][gy][gx]:
            return True
        return cell in raw.other_pin_blockers

    # Simplify wiggles first (turn tortuous zigzags into clean L-bends
    # along the wiggle's bounding-box perimeter), then chamfer the
    # first/second L-corner off any priority-bus pin into a 45°
    # diagonal, then collapse remaining monotonic staircases into
    # diagonals.
    simplified = _simplify_wiggles(
        raw.raw_cells, g, forbidden_check=_forbidden,
    )
    chamfered = _chamfer_pin_corners(
        simplified, g,
        priority_pin_xys=raw.priority_pin_xys,
        forbidden_check=_forbidden,
    )
    return _collapse_quadrant_runs(
        chamfered, g,
        own_pin_xys=raw.own_pin_xys,
        own_via_xys=raw.own_via_xys,
        forbidden_check=_forbidden,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def _path_to_cells(g: Grid, path: SignalPath) -> set[tuple[int, int, int]]:
    """Rasterise every cell touched by a SignalPath. Used to build the
    `parallel_target_cells` set for the second signal of a pair.
    """
    cells: set[tuple[int, int, int]] = set()
    for elt in path.elements:
        if isinstance(elt, WireSegment):
            length = math.hypot(
                elt.end.x - elt.start.x, elt.end.y - elt.start.y,
            )
            steps = max(int(length / g.res) + 1, 1)
            for i in range(steps + 1):
                t = i / steps
                wx = elt.start.x + t * (elt.end.x - elt.start.x)
                wy = elt.start.y + t * (elt.end.y - elt.start.y)
                gx, gy = g.to_grid(wx, wy)
                if g.in_bounds(gx, gy):
                    cells.add((elt.layer - 1, gy, gx))
        elif isinstance(elt, Via):
            gx, gy = g.to_grid(elt.position.x, elt.position.y)
            if g.in_bounds(gx, gy):
                cells.add((0, gy, gx))
                cells.add((1, gy, gx))
    return cells


def _finalise_collapse(
    g: Grid, raw_paths: list[_RawPath], dims,  # noqa: ANN001 — see route_board
) -> list[SignalPath]:
    """Post-route collapse pass: re-emit every path with diagonals where safe.

    Each path's monotonic cardinal staircases fold into 45° diagonals
    where the final g.blocked state allows. Diagonals are halo-aware:
    each gets re-blocked via `_block_path` (swept-rectangle halo for
    diagonal segments) so later diagonals in this pass see them.
    """
    # Precompute per-cell halo ownership so each path's collapse can
    # safely exempt cells it *exclusively* halos (cells shared with
    # another path's halo stay forbidden — collapsing through them
    # would close the wall-floor gap to the neighbour wire).
    owners: dict[tuple[int, int, int], int] = {}
    for raw in raw_paths:
        for cell in raw.halo_cells:
            owners[cell] = owners.get(cell, 0) + 1

    out: list[SignalPath] = []
    for raw in raw_paths:
        exclusive = {c for c in raw.halo_cells if owners.get(c, 0) <= 1}
        cells = _collapse_one_raw(g, raw, exclusive)
        waypoints = _path_to_waypoints(g, cells)
        path = waypoints_to_path(raw.name, waypoints)
        # Re-halo with the (possibly diagonal) collapsed geometry so
        # subsequent collapses in this loop see the new footprint.
        # The earlier axis-aligned halo for this path's staircase is
        # already in g.blocked; re-blocking with the diagonal halo
        # adds (slightly) to the blocked set but never unblocks. The
        # extra blocking is bounded by the diagonal's swept-rectangle
        # footprint, which sits inside the staircase's bounding box,
        # so over-blocking is small.
        _block_path(g, path, dims)
        out.append(path)
    return out


def route_board(board: Board, dims) -> list[SignalPath]:
    """Auto-route every bus on the Board. Entry point used by
    `board.build.build_board`. Routes signals as bundled pairs (e.g.
    VCC alongside GND, SCL alongside SDA for I²C) — see
    `_ordered_bus_actions` for the schedule. Runs the global
    staircase → 45° collapse as a final pass.
    """
    if not board.buses:
        return []

    g, pin_cells = _build_grid(board, dims)
    bound = board.bound_devices()
    paths: list[SignalPath] = []
    raw_paths: list[_RawPath] = []

    for bus in board.buses:
        bus_nets = list(resolve_bus(bus, bound))
        nets_by_signal = {n.signal: n for n in bus_nets}
        schedule = _ordered_bus_actions(bus.kind, nets_by_signal)
        cells_by_signal: dict[str, set[tuple[int, int, int]]] = {}

        for net, target_sig in schedule:
            target_cells = cells_by_signal.get(target_sig) if target_sig else None
            pitch_cells = None
            if target_sig is not None:
                target_net = nets_by_signal.get(target_sig)
                if target_net is not None:
                    # Master-pin pitch on the controller IC (e.g. SCL/SDA
                    # adjacent on ESP32 J1B). The parallel-bonus band is
                    # centred on this pitch so the second signal runs at
                    # the SAME spacing the partners have on the IC,
                    # instead of crowding closer for a marginal discount.
                    dx = net.master.position.x - target_net.master.position.x
                    dy = net.master.position.y - target_net.master.position.y
                    pitch_mm = abs(dx) + abs(dy)
                    pitch_cells = max(1, round(pitch_mm / g.res))
            try:
                net_results = _route_one_net(
                    g, net, pin_cells,
                    parallel_target_cells=target_cells,
                    parallel_pitch_cells=pitch_cells,
                )
            except RouteFailure as exc:
                exc.partial = tuple(paths)
                raise

            this_cells: set[tuple[int, int, int]] = set()
            for path, _ in net_results:
                this_cells |= _path_to_cells(g, path)
            cells_by_signal[net.signal] = this_cells

            for path, raw in net_results:
                paths.append(path)
                raw_paths.append(raw)
                raw.halo_cells = _block_path(g, path, dims)

    return _finalise_collapse(g, raw_paths, dims)


def autoroute(
    nets: Sequence[Net],
    *,
    board: Board,
    dims,
) -> list[SignalPath]:
    """Low-level entry point — route a specific net list against a
    Board's geometry. `route_board` is the usual entry that takes the
    nets straight off the Board.
    """
    g, pin_cells = _build_grid(board, dims)
    nets_sorted = sorted(nets, key=_net_priority)
    paths: list[SignalPath] = []
    raw_paths: list[_RawPath] = []
    for net in nets_sorted:
        net_results = _route_one_net(g, net, pin_cells)
        for path, raw in net_results:
            paths.append(path)
            raw_paths.append(raw)
            raw.halo_cells = _block_path(g, path, dims)
    return _finalise_collapse(g, raw_paths, dims)
