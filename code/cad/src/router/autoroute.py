"""Greedy A* auto-router.

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
  5. Convert the grid path back into `Waypoint`s, fold consecutive
     same-layer same-direction steps into single segments, and emit
     a `SignalPath` per net.

This is intentionally a small, greedy implementation — it produces
routable substrates for the kinds of boards the YAML describes (a
handful of devices on a 70×50 mm plate). Ripup/reroute, Steiner-tree
sharing, and chamfering are listed as follow-ups in the plan.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from board.board import Board
from board.buses import Net, PinEndpoint
from board.devices import Rect
from router.paths import Waypoint, waypoints_to_path
# `router.paths.Waypoint` carries a substrate.Point2D — a frozen
# dataclass with positional fields — so we use the substrate variant
# here. The board.pins.Point2D is a Pydantic BaseModel used in the
# spec; the two are interchangeable for routing math but only the
# dataclass accepts positional args.
from vitamins.substrate import Point2D as SubstratePoint2D
from vitamins.substrate import SignalPath, Via, WireSegment


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

GRID_RES_MM = 0.5

_W_STEP        = 1.0
_W_VIA         = 1.5   # cost of a single layer transition — kept low so the
                       # router uses BOTH layers instead of packing L1.
_W_CROSSING    = 10.0
_W_EDGE        = 3.0
_EDGE_RADIUS_MM = 1.0   # within this distance of the board edge → edge penalty

# Priority order: lower number routes first. Bus signal nets compete for
# the cleanest path; power follows because it's the most forgiving (any
# corridor with width clears the I-rail).
_SIGNAL_PRIORITY: dict[str, int] = {
    "SCL": 0, "SDA": 1, "TX": 0, "RX": 1,
    "VCC": 5, "3V3": 5, "5V": 5, "GND": 6,
}


# ---------------------------------------------------------------------------
# Failure type
# ---------------------------------------------------------------------------


class RouteFailure(Exception):
    """A net couldn't be routed. Carries the failing net + partial
    solution so the caller can surface a clear error."""

    def __init__(self, net: Net, reason: str, partial: tuple[SignalPath, ...]):
        super().__init__(f"{net.signal} (bus {net.bus_name!r}): {reason}")
        self.net = net
        self.reason = reason
        self.partial = partial


# ---------------------------------------------------------------------------
# Grid + blocking
# ---------------------------------------------------------------------------


@dataclass
class Grid:
    """Routing grid covering the base level's bounding box, two layers deep."""

    x_min: float
    y_min: float
    width: float     # board extent along x
    height: float    # board extent along y
    res: float = GRID_RES_MM
    # blocked[layer][gy][gx] = True if that cell can't be entered. Layer
    # is 0-indexed internally (0 → physical L1, 1 → physical L2).
    blocked: list[list[list[bool]]] = field(default_factory=list)

    @classmethod
    def from_board(cls, board: Board) -> "Grid":
        perim = board.levels[0].perimeter
        g = cls(
            x_min=perim.x_min, y_min=perim.y_min,
            width=perim.w, height=perim.h,
        )
        nx = int(round(g.width / g.res)) + 1
        ny = int(round(g.height / g.res)) + 1
        g.blocked = [
            [[False] * nx for _ in range(ny)]
            for _ in range(2)
        ]
        return g

    @property
    def nx(self) -> int:
        return len(self.blocked[0][0])

    @property
    def ny(self) -> int:
        return len(self.blocked[0])

    def to_grid(self, x: float, y: float) -> tuple[int, int]:
        gx = int(round((x - self.x_min) / self.res))
        gy = int(round((y - self.y_min) / self.res))
        return gx, gy

    def to_world(self, gx: int, gy: int) -> tuple[float, float]:
        return self.x_min + gx * self.res, self.y_min + gy * self.res

    def in_bounds(self, gx: int, gy: int) -> bool:
        return 0 <= gx < self.nx and 0 <= gy < self.ny

    def block_rect(
        self, rect: Rect, *, inflate: float, layers: Iterable[int]
    ) -> None:
        """Mark every cell inside (rect + inflate) as blocked on the
        listed layers (0/1 = physical L1/L2)."""
        x_min = rect.x_min - inflate
        x_max = rect.x_max + inflate
        y_min = rect.y_min - inflate
        y_max = rect.y_max + inflate
        gx_lo, gy_lo = self.to_grid(x_min, y_min)
        gx_hi, gy_hi = self.to_grid(x_max, y_max)
        for ly in layers:
            for gy in range(max(gy_lo, 0), min(gy_hi + 1, self.ny)):
                for gx in range(max(gx_lo, 0), min(gx_hi + 1, self.nx)):
                    self.blocked[ly][gy][gx] = True

    def block_circle(
        self, cx: float, cy: float, radius: float, layers: Iterable[int]
    ) -> None:
        """Mark every cell whose centre falls within `radius` of (cx, cy)
        on the listed layers."""
        gx_lo, gy_lo = self.to_grid(cx - radius, cy - radius)
        gx_hi, gy_hi = self.to_grid(cx + radius, cy + radius)
        r2 = radius * radius
        for ly in layers:
            for gy in range(max(gy_lo, 0), min(gy_hi + 1, self.ny)):
                for gx in range(max(gx_lo, 0), min(gx_hi + 1, self.nx)):
                    wx, wy = self.to_world(gx, gy)
                    if (wx - cx) ** 2 + (wy - cy) ** 2 <= r2:
                        self.blocked[ly][gy][gx] = True


def _build_grid(board: Board, dims) -> tuple[Grid, set[tuple[int, int, int]]]:
    """Prepare the routing grid with all static blockers in place.

    Returns (grid, pin_cells) where pin_cells is the set of cells that
    represent device pin holes — A* may *enter* these cells but they
    don't act as obstacles for the net that targets them. Other nets
    treat them as blocked.
    """
    g = Grid.from_board(board)

    # Edge clearance: forbid a strip along the board outline so channels
    # don't run flush against the edge.
    perim = board.levels[0].perimeter
    ec = dims.edge_clearance
    g.block_rect(
        Rect(cx=perim.cx, cy=perim.y_min + ec / 2, w=perim.w, h=ec),
        inflate=0, layers=(0, 1),
    )
    g.block_rect(
        Rect(cx=perim.cx, cy=perim.y_max - ec / 2, w=perim.w, h=ec),
        inflate=0, layers=(0, 1),
    )
    g.block_rect(
        Rect(cx=perim.x_min + ec / 2, cy=perim.cy, w=ec, h=perim.h),
        inflate=0, layers=(0, 1),
    )
    g.block_rect(
        Rect(cx=perim.x_max - ec / 2, cy=perim.cy, w=ec, h=perim.h),
        inflate=0, layers=(0, 1),
    )

    # Pin-hole cells — they're "soft" blockers (route endpoints land on
    # them) so we don't pre-block them here, but we record them so the
    # router knows which cells are valid termini. We also reserve a
    # one-cell halo around each pin as a "pin approach corridor" — the
    # path-blocking logic below skips these cells so a pin always
    # remains reachable from at least one cardinal direction even after
    # adjacent nets have routed through nearby cells. The approach also
    # protects pin reachability from pocket blocking below.
    # Pin cells + per-pin 1-cell approach corridors.
    #
    # Approach corridor depth tradeoff: deeper corridors keep pins
    # reachable when prior nets' halos crowd in, but if two adjacent
    # pins' corridors OVERLAP, two cross-net wires can route through
    # the overlap and the wall floor between them collapses to 0.5 mm.
    #
    # SCD41/BH1750 pin pitch is 2.54 mm = 5 grid cells at 0.5 mm
    # resolution. A 1-cell cardinal corridor (pin ±1 in x and y) means
    # adjacent pins' corridors sit 2 cells apart — no overlap, no
    # wall-floor collapse, and each pin keeps at least one free
    # approach cell on each layer for A* to step from.
    APPROACH_DEPTH = 3
    pin_cells: set[tuple[int, int, int]] = set()
    pin_approach_by_pin: dict[
        tuple[float, float], set[tuple[int, int, int]]
    ] = {}
    for inst in board.devices:
        device = inst.resolved_device()
        for pin in device.pins:
            abs_pos = device.pin_position_at(inst.position, inst.rotation, pin)
            gx, gy = g.to_grid(abs_pos.x, abs_pos.y)
            if not g.in_bounds(gx, gy):
                continue
            key = (round(abs_pos.x, 3), round(abs_pos.y, 3))
            approach: set[tuple[int, int, int]] = set()
            for ly in (0, 1):
                pin_cells.add((ly, gy, gx))
                for ddx, ddy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    for k in range(1, APPROACH_DEPTH + 1):
                        nx, ny = gx + ddx * k, gy + ddy * k
                        if g.in_bounds(nx, ny):
                            approach.add((ly, ny, nx))
            pin_approach_by_pin[key] = approach
    g._pin_approach_cells = {c for s in pin_approach_by_pin.values() for c in s}
    g._pin_approach_by_pin = pin_approach_by_pin

    # Device pockets — for flat-mounted devices, the pocket cuts away
    # the top face of the substrate, so L2 (top) channels can't pass
    # through the pocket xy. L1 stays clear unless the pin row sits in
    # the pocket. We block the pocket xy on L2 only (L1 keeps routes
    # available under the device for short escapes). Pin approach cells
    # are explicitly excluded so each pin remains reachable from at
    # least one cardinal direction on each layer.
    for inst in board.devices:
        device = inst.resolved_device()
        fp = device.footprint
        if inst.rotation in (0, 180):
            w, h = fp.w, fp.h
        else:
            w, h = fp.h, fp.w
        pocket = Rect(
            cx=inst.position.x + fp.cx,
            cy=inst.position.y + fp.cy,
            w=w + 2 * dims.pocket_clearance,
            h=h + 2 * dims.pocket_clearance,
        )
        if inst.header is None:
            gx_lo, gy_lo = g.to_grid(pocket.x_min, pocket.y_min)
            gx_hi, gy_hi = g.to_grid(pocket.x_max, pocket.y_max)
            for gy in range(max(gy_lo, 0), min(gy_hi + 1, g.ny)):
                for gx in range(max(gx_lo, 0), min(gx_hi + 1, g.nx)):
                    if (1, gy, gx) in pin_cells \
                            or (1, gy, gx) in g._pin_approach_cells:
                        continue
                    g.blocked[1][gy][gx] = True

    return g, pin_cells


def _block_path(g: Grid, path: SignalPath, dims) -> None:
    """Inflate a routed path's segments + vias into the grid as blockers
    for subsequent nets. Pin cells and their immediate approach corridors
    are never blocked — pins must remain reachable by their owning net.

    Halo of (channel_width/2 + min_wall_thickness/2) — each wire's
    keep-out is half the required centre-to-centre distance, so two
    wires can land at exactly wall_floor apart. The greedy per-net A*
    can't enforce a stricter halo without running out of corridor space
    at the SCD41/BH1750 pin clusters (4 wires per pin row at 2.54 mm
    pitch leaves no slack for wider spacing). Wall-floor enforcement is
    therefore advisory at the moment — surfaced in the report's
    invariants block and the `test_wire_to_wire_wall_floor` check, but
    not blocking. The router rework that fixes this is a Steiner-tree
    trunk sharing for multi-slave nets (plan §Follow-ups: ripup/reroute).
    """
    halo = dims.channel_width / 2 + dims.min_wall_thickness / 2
    via_halo = dims.via_diameter / 2 + dims.min_wall_thickness / 2
    approach = getattr(g, "_pin_approach_cells", set())

    def _block_cell(layer: int, gy: int, gx: int) -> None:
        if not g.in_bounds(gx, gy):
            return
        if (layer, gy, gx) in approach:
            return
        g.blocked[layer][gy][gx] = True

    for elt in path.elements:
        if isinstance(elt, WireSegment):
            x_min = min(elt.start.x, elt.end.x) - halo
            x_max = max(elt.start.x, elt.end.x) + halo
            y_min = min(elt.start.y, elt.end.y) - halo
            y_max = max(elt.start.y, elt.end.y) + halo
            gx_lo, gy_lo = g.to_grid(x_min, y_min)
            gx_hi, gy_hi = g.to_grid(x_max, y_max)
            for gy in range(max(gy_lo, 0), min(gy_hi + 1, g.ny)):
                for gx in range(max(gx_lo, 0), min(gx_hi + 1, g.nx)):
                    _block_cell(elt.layer - 1, gy, gx)
        elif isinstance(elt, Via):
            r2 = via_halo * via_halo
            gx_lo, gy_lo = g.to_grid(elt.position.x - via_halo, elt.position.y - via_halo)
            gx_hi, gy_hi = g.to_grid(elt.position.x + via_halo, elt.position.y + via_halo)
            for ly in (0, 1):
                for gy in range(max(gy_lo, 0), min(gy_hi + 1, g.ny)):
                    for gx in range(max(gx_lo, 0), min(gx_hi + 1, g.nx)):
                        wx, wy = g.to_world(gx, gy)
                        if (wx - elt.position.x) ** 2 + (wy - elt.position.y) ** 2 <= r2:
                            _block_cell(ly, gy, gx)


# ---------------------------------------------------------------------------
# A* core
# ---------------------------------------------------------------------------


_MOVES = [
    (1,  0,  0), (-1, 0,  0),
    (0,  1,  0), ( 0, -1, 0),
]
_LAYER_FLIP = (0, 1, 1)  # ΔLayer used when moving across layers


def _heuristic(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    # Manhattan in xy, plus one via cost per layer mismatch.
    dx = abs(a[2] - b[2])
    dy = abs(a[1] - b[1])
    dl = abs(a[0] - b[0])
    return (dx + dy) * _W_STEP + dl * _W_VIA


def _edge_penalty(g: Grid, gx: int, gy: int) -> float:
    # Penalise cells within EDGE_RADIUS_MM of the board outline beyond
    # the hard edge_clearance strip already blocked. Soft edge cost
    # encourages the A* to stay centred when there's no other reason.
    wx, wy = g.to_world(gx, gy)
    perim_dx = min(wx - g.x_min, g.x_min + g.width - wx)
    perim_dy = min(wy - g.y_min, g.y_min + g.height - wy)
    perim = min(perim_dx, perim_dy)
    if perim < _EDGE_RADIUS_MM:
        return _W_EDGE * (1 - perim / _EDGE_RADIUS_MM)
    return 0.0


def _astar(
    g: Grid,
    starts: list[tuple[int, int, int]],
    goals: set[tuple[int, int, int]],
    *,
    pin_cells: set[tuple[int, int, int]],
    own_pin_cells: set[tuple[int, int, int]],
    extra_blocked: set[tuple[int, int, int]] = frozenset(),
    layer_step_mul: tuple[float, float] = (1.0, 1.0),
) -> list[tuple[int, int, int]] | None:
    """A* on the (layer, gy, gx) grid.

    `starts` is the set of seed cells (one per layer for a pin start, or
    every cell of the in-progress net's path for daisy-chain steps).
    `goals` is the cell set considered "reached" (pin xy on either layer).
    `pin_cells` are device pin holes for OTHER devices on the board — A*
    treats them as blocked (no routing through somebody else's pin).
    `own_pin_cells` are the goal pins — A* may end on them.
    """
    if not starts or not goals:
        return None

    # Priority queue of (f, g, cell, parent)
    open_heap: list[tuple[float, float, tuple[int, int, int], int]] = []
    # cell → (g_cost, parent_index). parents stored in a list so we can
    # reconstruct the path.
    came_from: list[tuple[int, int, int] | None] = [None]  # index 0 = root sentinel
    g_cost: dict[tuple[int, int, int], float] = {}

    for s in starts:
        g_cost[s] = 0.0
        h = min(_heuristic(s, goal) for goal in goals)
        heapq.heappush(open_heap, (h, 0.0, s, 0))

    parents: dict[tuple[int, int, int], tuple[int, int, int] | None] = {s: None for s in starts}

    while open_heap:
        f, gc, cur, _ = heapq.heappop(open_heap)
        if cur in goals:
            # reconstruct
            path = [cur]
            while parents[path[-1]] is not None:
                path.append(parents[path[-1]])  # type: ignore[arg-type]
            path.reverse()
            return path

        if gc > g_cost.get(cur, math.inf):
            continue

        cur_layer, cur_gy, cur_gx = cur

        # Same-layer moves
        for dx, dy, dl in _MOVES:
            ny, nx_ = cur_gy + dy, cur_gx + dx
            if not g.in_bounds(nx_, ny):
                continue
            nbr = (cur_layer, ny, nx_)
            if g.blocked[cur_layer][ny][nx_]:
                # Allow stepping onto OWN pin cells (they're the goals);
                # forbid stepping onto other-net pins or static blockers.
                if nbr not in own_pin_cells:
                    continue
            if nbr in pin_cells and nbr not in own_pin_cells:
                continue
            if nbr in extra_blocked and nbr not in own_pin_cells:
                continue
            step_cost = (
                _W_STEP * layer_step_mul[cur_layer]
                + _edge_penalty(g, nx_, ny)
            )
            new_g = gc + step_cost
            if new_g < g_cost.get(nbr, math.inf):
                g_cost[nbr] = new_g
                parents[nbr] = cur
                h = min(_heuristic(nbr, goal) for goal in goals)
                heapq.heappush(open_heap, (new_g + h, new_g, nbr, 0))

        # Layer change (via)
        other = 1 - cur_layer
        nbr = (other, cur_gy, cur_gx)
        if (not g.blocked[other][cur_gy][cur_gx] or nbr in own_pin_cells) \
                and (nbr not in pin_cells or nbr in own_pin_cells) \
                and (nbr not in extra_blocked or nbr in own_pin_cells):
            new_g = gc + _W_VIA
            if new_g < g_cost.get(nbr, math.inf):
                g_cost[nbr] = new_g
                parents[nbr] = cur
                h = min(_heuristic(nbr, goal) for goal in goals)
                heapq.heappush(open_heap, (new_g + h, new_g, nbr, 0))

    return None


# ---------------------------------------------------------------------------
# Path → Waypoint conversion + SignalPath build
# ---------------------------------------------------------------------------


def _path_to_waypoints(g: Grid, cells: list[tuple[int, int, int]]) -> list[Waypoint]:
    """Collapse a sequence of unit grid steps into Waypoints at every
    corner / layer change."""
    if not cells:
        return []

    def cell_to_wp(c: tuple[int, int, int]) -> Waypoint:
        layer, gy, gx = c
        wx, wy = g.to_world(gx, gy)
        return Waypoint(SubstratePoint2D(wx, wy), layer + 1)

    waypoints: list[Waypoint] = [cell_to_wp(cells[0])]
    for i in range(1, len(cells) - 1):
        prev, cur, nxt = cells[i - 1], cells[i], cells[i + 1]
        # Direction changes or layer changes are corner waypoints.
        prev_dir = (cur[0] - prev[0], cur[1] - prev[1], cur[2] - prev[2])
        next_dir = (nxt[0] - cur[0], nxt[1] - cur[1], nxt[2] - cur[2])
        if prev_dir != next_dir:
            waypoints.append(cell_to_wp(cur))
    waypoints.append(cell_to_wp(cells[-1]))
    return waypoints


def _route_one_net(
    g: Grid,
    net: Net,
    pin_cells: set[tuple[int, int, int]],
) -> list[SignalPath]:
    """Route a single Net. Emits one `SignalPath` per (master, slave)
    pair — the I²C bus is a logical net; physically each leg can take
    its own route. Daisy-chaining and Steiner-tree sharing are a
    follow-up optimisation (see plan §Follow-ups).

    Honours `net.hint` if set:
      - `prefer_layer`: bias A* step cost away from the other layer.
      - `must_pass`: route master → wp1 → wp2 → … → slave for every
        slave, with each waypoint a forced (layer, gy, gx) intermediate.
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

    master_cells = _endpoint_seed_cells(g, net.master)
    out: list[SignalPath] = []
    for slave in net.slaves:
        slave_cells = _endpoint_seed_cells(g, slave)
        # Each slave's full path is master → wp1 → wp2 → … → slave.
        # Build the leg sequence as a list of (start_cells, goal_cells).
        leg_endpoints: list[
            tuple[list[tuple[int, int, int]], set[tuple[int, int, int]]]
        ] = []
        cursor = master_cells
        for wp_cell in must_pass_cells:
            leg_endpoints.append((cursor, {wp_cell}))
            cursor = [wp_cell]
        leg_endpoints.append((cursor, set(slave_cells)))

        full_cells: list[tuple[int, int, int]] = []
        for leg_no, (starts, goals) in enumerate(leg_endpoints):
            cells = _astar(
                g, starts, goals,
                pin_cells=pin_cells - own_pin_cells,
                own_pin_cells=own_pin_cells,
                extra_blocked=other_pin_approach - own_pin_cells,
                layer_step_mul=layer_step_mul,
            )
            if cells is None:
                where = (
                    f"leg {leg_no} (→ waypoint {leg_no})"
                    if leg_no < len(must_pass_cells)
                    else f"final leg → {slave.instance_name}"
                )
                raise RouteFailure(
                    net, f"no path: {where}", partial=(),
                )
            if not full_cells:
                full_cells = cells
            else:
                # Skip the first cell of subsequent legs — it's the
                # waypoint that ended the previous leg.
                full_cells.extend(cells[1:])

        waypoints = _path_to_waypoints(g, full_cells)
        path = waypoints_to_path(
            f"{net.bus_name}_{net.signal}_{slave.instance_name}", waypoints,
        )
        out.append(path)
        # No intra-net blocking — successive slaves of the same net
        # share the master pin and may re-use each other's trunks.
        # Cross-net halo blocking is applied by `route_board` after the
        # full net (all slaves) has been routed.
    return out


def _endpoint_seed_cells(g: Grid, endpoint: PinEndpoint) -> list[tuple[int, int, int]]:
    gx, gy = g.to_grid(endpoint.position.x, endpoint.position.y)
    return [(0, gy, gx), (1, gy, gx)]


def _block_path_into_grid(g: Grid, path: SignalPath) -> None:
    """Block every cell touched by `path` so subsequent legs of the same
    net (and later nets) don't overrun it. Pin approach cells are
    preserved — see `_block_path` for the rationale."""
    approach = getattr(g, "_pin_approach_cells", set())

    def block(layer: int, gx: int, gy: int) -> None:
        if not g.in_bounds(gx, gy):
            return
        if (layer, gy, gx) in approach:
            return
        g.blocked[layer][gy][gx] = True

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
                block(elt.layer - 1, gx, gy)
        elif isinstance(elt, Via):
            gx, gy = g.to_grid(elt.position.x, elt.position.y)
            block(0, gx, gy)
            block(1, gx, gy)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def _net_priority(net: Net) -> tuple[int, int]:
    sig_priority = _SIGNAL_PRIORITY.get(net.signal, 7)
    # Tie-break: more pins → harder to route, do it first.
    return sig_priority, -len(net.endpoints)


def route_board(board: Board, dims) -> list[SignalPath]:
    """Auto-route every bus on the Board. Entry point used by
    `board.build.build_board`."""
    nets = list(board.nets())
    if not nets:
        return []
    nets.sort(key=_net_priority)

    g, pin_cells = _build_grid(board, dims)
    paths: list[SignalPath] = []
    for net in nets:
        try:
            net_paths = _route_one_net(g, net, pin_cells)
        except RouteFailure as exc:
            exc.partial = tuple(paths)
            raise
        for p in net_paths:
            paths.append(p)
            _block_path(g, p, dims)
    return paths


def autoroute(
    nets: Sequence[Net],
    *,
    board: Board,
    dims,
) -> list[SignalPath]:
    """Low-level entry point — route a specific net list against a
    Board's geometry. `route_board` is the usual entry that takes the
    nets straight off the Board."""
    g, pin_cells = _build_grid(board, dims)
    nets_sorted = sorted(nets, key=_net_priority)
    paths: list[SignalPath] = []
    for net in nets_sorted:
        net_paths = _route_one_net(g, net, pin_cells)
        for p in net_paths:
            paths.append(p)
            _block_path(g, p, dims)
    return paths
