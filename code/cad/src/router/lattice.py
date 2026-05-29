"""Breadboard-lattice-native autorouter.

Routes on the 2.54 mm pitch lattice instead of the fine voxel grid, so every
run, corner, and via lands on the breadboard grid *by construction* — no
post-route snapping. A lattice node is `(layer, ix, iy)` where `ix/iy` are
integer pitch indices; world position is `(g.x_min + ix·pitch, g.y_min +
iy·pitch)`. Because device pins are pitch-snapped and the grid origin is a pitch
multiple (see `board._snap_perimeter_to_pitch`), every pin maps to an exact node.

Clearance is justified by the pitch: `wall_floor = channel_width + buffer =
1.8 mm`, and adjacent pitch columns are 2.54 mm apart, so cardinal parallels
clear automatically. The fine `Grid` (res = pitch/5) is retained ONLY as a
clearance oracle — it no longer chooses paths, it just answers whether a
candidate run's channel + halo collides with static blockers (edge strips,
device pockets), another net's committed copper, or a foreign pin.

This module provides the graph + oracle + A* search (`_lattice_astar`). Net
orchestration (scheduling, trunk sharing) and `SignalPath` emission are layered
on in a later phase.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from collections.abc import Iterator

from board.board import Board
from board.buses import Net, resolve_bus
from router.astar import _W_BEND, _W_STEP, _W_VIA, _edge_penalty
from router.autoroute import RouteFailure
from router.grid import Grid, _build_grid, _dense_cluster_pin_axes
from router.paths import Waypoint, waypoints_to_path
from router.schedule import _net_priority, _ordered_bus_actions
from vitamins.substrate import Point2D, SignalPath, Via, WireSegment

_SQRT2 = math.sqrt(2.0)

# Owner sentinel for a cell occupied by a static blocker (edge / pocket) or a
# foreign pin — never routable by anyone.
_STATIC = -2
_FREE = -1

_PLANAR_MOVES = [
    (1, 0), (-1, 0), (0, 1), (0, -1),          # cardinal
    (1, 1), (1, -1), (-1, 1), (-1, -1),        # diagonal
]


# ---------------------------------------------------------------------------
# Fine-grid cell coverage (mirrors blocking._block_path so the oracle's
# read-check and write-commit cover exactly the cells a routed channel/via
# would occupy).
# ---------------------------------------------------------------------------


def _segment_cells(
    g: Grid, a: tuple[float, float], b: tuple[float, float], layer_idx: int, halo: float,
) -> Iterator[tuple[int, int, int]]:
    """Yield the `(layer_idx, gy, gx)` fine cells a channel of radius `halo`
    sweeps from world point `a` to `b`. Cardinal runs halo their bounding
    rectangle; diagonals rasterise at half-grid spacing and halo each sample
    (a swept rectangle hugging the wire, not its bounding box)."""
    ax, ay = a
    bx, by = b
    if ax == bx or ay == by:
        x_lo, y_lo = g.to_grid(min(ax, bx) - halo, min(ay, by) - halo)
        x_hi, y_hi = g.to_grid(max(ax, bx) + halo, max(ay, by) + halo)
        for gy in range(max(y_lo, 0), min(y_hi + 1, g.ny)):
            for gx in range(max(x_lo, 0), min(x_hi + 1, g.nx)):
                yield (layer_idx, gy, gx)
        return
    length = math.hypot(bx - ax, by - ay)
    steps = max(int(length / (g.res / 2)) + 1, 1)
    seen: set[tuple[int, int, int]] = set()
    for i in range(steps + 1):
        t = i / steps
        wx, wy = ax + t * (bx - ax), ay + t * (by - ay)
        x_lo, y_lo = g.to_grid(wx - halo, wy - halo)
        x_hi, y_hi = g.to_grid(wx + halo, wy + halo)
        for gy in range(max(y_lo, 0), min(y_hi + 1, g.ny)):
            for gx in range(max(x_lo, 0), min(x_hi + 1, g.nx)):
                cell = (layer_idx, gy, gx)
                if cell not in seen:
                    seen.add(cell)
                    yield cell


def _via_cells(
    g: Grid, pos: tuple[float, float], via_halo: float,
) -> Iterator[tuple[int, int, int]]:
    """Yield both layers' fine cells within `via_halo` of world `pos`."""
    px, py = pos
    r2 = via_halo * via_halo
    x_lo, y_lo = g.to_grid(px - via_halo, py - via_halo)
    x_hi, y_hi = g.to_grid(px + via_halo, py + via_halo)
    for gy in range(max(y_lo, 0), min(y_hi + 1, g.ny)):
        for gx in range(max(x_lo, 0), min(x_hi + 1, g.nx)):
            wx, wy = g.to_world(gx, gy)
            if (wx - px) ** 2 + (wy - py) ** 2 <= r2:
                yield (0, gy, gx)
                yield (1, gy, gx)


# ---------------------------------------------------------------------------
# Clearance oracle
# ---------------------------------------------------------------------------


class LatticeOracle:
    """Decides whether a candidate lattice edge (a run or a via) is clear.

    Backed by the fine `Grid`: `g.blocked` holds static blockers (edge strips,
    device pockets). `pin_cells` are every device pin hole — foreign to a given
    net. `owner` records committed routed copper per cell so a net's own trunk
    reads as free (enabling trunk sharing) while another net's copper blocks.
    """

    def __init__(self, g: Grid, pin_cells: set[tuple[int, int, int]], dims) -> None:
        self.g = g
        self.dims = dims
        self.halo = dims.wall_halo_mm(g.res)
        self.via_halo = dims.via_halo_mm
        self.pin_cells = pin_cells
        self.owner: dict[tuple[int, int, int], int] = {}

    @classmethod
    def from_board(cls, board, dims) -> LatticeOracle:
        g, pin_cells = _build_grid(board, dims)
        return cls(g, pin_cells, dims)

    def _cell_clear(
        self, cell: tuple[int, int, int], net_id: int,
        own_pins: frozenset[tuple[int, int, int]],
    ) -> bool:
        layer, gy, gx = cell
        if self.g.blocked[layer][gy][gx]:
            return False
        o = self.owner.get(cell)
        if o is not None and o != net_id:
            return False
        if cell in self.pin_cells and cell not in own_pins:
            return False
        return True

    def run_clear(
        self, a: tuple[float, float], b: tuple[float, float], layer_idx: int,
        net_id: int, own_pins: frozenset[tuple[int, int, int]],
    ) -> bool:
        # Asymmetric by design: a committed run writes its INFLATED halo as a
        # keep-out, but a candidate run is tested on its CENTERLINE only. So
        # the test is "does my centerline enter a foreign halo / static / pin",
        # not "do our halos touch" — two pitch-adjacent parallels (centrelines
        # 2.54mm apart, halos ~1.55mm) clear because neither centerline lands
        # in the other's halo, while half-pitch (1.27mm) parallels do not.
        return all(
            self._cell_clear(c, net_id, own_pins)
            for c in _segment_cells(self.g, a, b, layer_idx, 0.0)
        )

    def via_clear(
        self, pos: tuple[float, float], net_id: int,
        own_pins: frozenset[tuple[int, int, int]],
    ) -> bool:
        # The via barrel sits at the node cell on both layers (mirrors the
        # voxel router's single-cell layer-flip test); the inflated via halo is
        # written on commit so other nets' centerlines keep clear.
        gx, gy = self.g.to_grid(*pos)
        return all(self._cell_clear((ly, gy, gx), net_id, own_pins) for ly in (0, 1))

    def commit_run(
        self, a: tuple[float, float], b: tuple[float, float], layer_idx: int, net_id: int,
    ) -> None:
        for c in _segment_cells(self.g, a, b, layer_idx, self.halo):
            if not self.g.blocked[c[0]][c[1]][c[2]]:
                self.owner[c] = net_id

    def commit_via(self, pos: tuple[float, float], net_id: int) -> None:
        for c in _via_cells(self.g, pos, self.via_halo):
            if not self.g.blocked[c[0]][c[1]][c[2]]:
                self.owner[c] = net_id


# ---------------------------------------------------------------------------
# Lattice geometry
# ---------------------------------------------------------------------------


class LatticeGeom:
    """Maps lattice nodes `(layer, ix, iy)` to world / fine-cell coordinates.

    `N = pitch / res` (an integer, e.g. 5) is the number of fine cells per
    pitch; lattice node `ix` sits on fine column `ix·N`.
    """

    def __init__(self, g: Grid, pitch: float) -> None:
        self.g = g
        self.pitch = pitch
        self.n = round(pitch / g.res)
        self.max_ix = (g.nx - 1) // self.n
        self.max_iy = (g.ny - 1) // self.n

    def world(self, ix: int, iy: int) -> tuple[float, float]:
        return self.g.to_world(ix * self.n, iy * self.n)

    def node_of_pin(self, x: float, y: float) -> tuple[int, int]:
        gx, gy = self.g.to_grid(x, y)
        return gx // self.n, gy // self.n

    def in_bounds(self, ix: int, iy: int) -> bool:
        return 0 <= ix <= self.max_ix and 0 <= iy <= self.max_iy


# ---------------------------------------------------------------------------
# A* on the lattice
# ---------------------------------------------------------------------------


def _octile(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    dx = abs(a[1] - b[1])
    dy = abs(a[2] - b[2])
    dl = abs(a[0] - b[0])
    return (max(dx, dy) + (_SQRT2 - 1) * min(dx, dy)) * _W_STEP + dl * _W_VIA


def _perp_ok(axis: tuple[int, int]) -> frozenset[tuple[int, int]]:
    return frozenset({axis, (-axis[0], -axis[1])})


def _lattice_astar(
    geom: LatticeGeom,
    oracle: LatticeOracle,
    starts: list[tuple[int, int, int]],
    goals: set[tuple[int, int, int]],
    *,
    net_id: int,
    own_pins: frozenset[tuple[int, int, int]],
    layer_step_mul: tuple[float, float] = (1.0, 1.0),
    dense_axis: dict[tuple[int, int], tuple[int, int]] | None = None,
    forbidden_nodes: frozenset[tuple[int, int]] = frozenset(),
) -> list[tuple[int, int, int]] | None:
    """A* over `(layer, ix, iy)` nodes. Cardinal + 45° diagonal planar moves
    and a via (layer flip); a candidate edge is admitted only if the oracle
    finds its swept channel/via clear. Returns the node path or None.

    `dense_axis` maps a dense-pin-row node `(ix, iy)` to the perpendicular
    approach axis: a planar move that enters OR leaves such a node must run
    along that axis. This keeps each pin in a tight row approached on its own
    perpendicular column so adjacent nets' halos (which exceed half a pitch)
    don't contaminate a neighbour pin's approach lane."""
    if not starts or not goals:
        return None
    dense_axis = dense_axis or {}

    open_heap: list[
        tuple[float, float, tuple[int, int, int], tuple[int, int, int] | None]
    ] = []
    # The search state is (node, prev_step), not just the node. prev_step is
    # the move token that arrived at the node — planar (0, dy, dx), via
    # (±1, 0, 0), or None at a start — and it drives two things: the bend
    # penalty (any direction change) AND the turn restriction below. Keying on
    # it stops the search collapsing two arrivals that reach the same node from
    # different directions, which is what makes the turn restriction sound: a
    # node entered going NE may legally exit S only via an arrival the
    # node-only search would have discarded.
    State = tuple[tuple[int, int, int], tuple[int, int, int] | None]
    g_cost: dict[State, float] = {}
    parents: dict[State, State | None] = {}
    for s in starts:
        g_cost[(s, None)] = 0.0
        parents[(s, None)] = None
        h = min(_octile(s, goal) for goal in goals)
        heapq.heappush(open_heap, (h, 0.0, s, None))

    while open_heap:
        _f, gc, cur, prev_step = heapq.heappop(open_heap)
        state: State = (cur, prev_step)
        if cur in goals:
            path = [cur]
            st = parents[state]
            while st is not None:
                path.append(st[0])
                st = parents[st]
            path.reverse()
            return path
        if gc > g_cost.get(state, math.inf):
            continue
        layer, ix, iy = cur
        cur_world = geom.world(ix, iy)
        cur_perp = dense_axis.get((ix, iy))
        # Incoming planar direction, or None at a start / just after a via —
        # both leave the next planar move's direction unconstrained.
        din = (
            (prev_step[2], prev_step[1])
            if prev_step is not None and prev_step[0] == 0
            else None
        )

        for dx, dy in _PLANAR_MOVES:
            # Turn restriction: never bend more than 90° between consecutive
            # planar runs. A >90° direction change makes an acute (< 90°)
            # interior corner — a sub-45° spike that can't be printed as a
            # channel. All lattice steps have components in {-1, 0, 1}, so the
            # sign of the dot product alone separates a ≤90° turn (≥ 0) from a
            # 135°/180° one (< 0).
            if din is not None and din[0] * dx + din[1] * dy < 0:
                continue
            nix, niy = ix + dx, iy + dy
            if not geom.in_bounds(nix, niy):
                continue
            # Another dense pin's reserved approach lane — keep this net's
            # trunk out so the pin's owner can always reach it.
            if (nix, niy) in forbidden_nodes:
                continue
            # Dense-row pins are entered/left only along their perpendicular
            # approach axis (keeps neighbour pins' halos out of each lane).
            if cur_perp is not None and (dx, dy) not in _perp_ok(cur_perp):
                continue
            nbr_perp = dense_axis.get((nix, niy))
            if nbr_perp is not None and (dx, dy) not in _perp_ok(nbr_perp):
                continue
            nbr = (layer, nix, niy)
            nbr_world = geom.world(nix, niy)
            if not oracle.run_clear(cur_world, nbr_world, layer, net_id, own_pins):
                continue
            base = _SQRT2 if (dx and dy) else 1.0
            step = base * _W_STEP * layer_step_mul[layer]
            step += _edge_penalty(geom.g, nix * geom.n, niy * geom.n)
            step_dir = (0, dy, dx)
            if prev_step is not None and prev_step != step_dir:
                step += _W_BEND
            new_g = gc + step
            nstate: State = (nbr, step_dir)
            if new_g < g_cost.get(nstate, math.inf):
                g_cost[nstate] = new_g
                parents[nstate] = state
                h = min(_octile(nbr, goal) for goal in goals)
                heapq.heappush(open_heap, (new_g + h, new_g, nbr, step_dir))

        other = 1 - layer
        nbr = (other, ix, iy)
        if oracle.via_clear(cur_world, net_id, own_pins):
            step = _W_VIA
            step_dir = (other - layer, 0, 0)
            if prev_step is not None and prev_step != step_dir:
                step += _W_BEND
            new_g = gc + step
            nstate = (nbr, step_dir)
            if new_g < g_cost.get(nstate, math.inf):
                g_cost[nstate] = new_g
                parents[nstate] = state
                h = min(_octile(nbr, goal) for goal in goals)
                heapq.heappush(open_heap, (new_g + h, new_g, nbr, step_dir))

    return None


# ---------------------------------------------------------------------------
# Node path -> waypoints -> SignalPath
# ---------------------------------------------------------------------------


def _nodes_to_waypoints(geom: LatticeGeom, nodes: list[tuple[int, int, int]]) -> list[Waypoint]:
    """Collapse a node path into corner/via waypoints. A waypoint is kept at
    the ends, at every planar direction change, and on both sides of a layer
    flip (so `waypoints_to_path` emits a Via at the shared xy)."""
    def to_wp(node: tuple[int, int, int]) -> Waypoint:
        layer, ix, iy = node
        wx, wy = geom.world(ix, iy)
        return Waypoint(point=Point2D(x=round(wx, 3), y=round(wy, 3)), layer=layer + 1)

    keep = [nodes[0]]
    for i in range(1, len(nodes) - 1):
        prev, cur, nxt = nodes[i - 1], nodes[i], nodes[i + 1]
        if cur[0] != prev[0] or nxt[0] != cur[0]:
            keep.append(cur)  # adjacent to a layer flip (via)
            continue
        d_in = (cur[1] - prev[1], cur[2] - prev[2])
        d_out = (nxt[1] - cur[1], nxt[2] - cur[2])
        if d_in != d_out:
            keep.append(cur)  # planar corner
    keep.append(nodes[-1])
    return [to_wp(n) for n in keep]


def _own_pin_cells(g: Grid, net: Net) -> frozenset[tuple[int, int, int]]:
    cells: set[tuple[int, int, int]] = set()
    for ep in net.endpoints:
        gx, gy = g.to_grid(ep.position.x, ep.position.y)
        cells.add((0, gy, gx))
        cells.add((1, gy, gx))
    return frozenset(cells)


def _route_one_net_lattice(
    geom: LatticeGeom, oracle: LatticeOracle, net: Net, net_id: int,
    dense_axis: dict[tuple[int, int], tuple[int, int]] | None = None,
    approach_reserved: dict[tuple[int, int], set[tuple[int, int]]] | None = None,
) -> list[SignalPath]:
    """Route one net as a greedy Steiner tree on the lattice. First slave:
    master → (must_pass) → slave. Later slaves branch off the committed trunk
    nodes (multi-source A*). Each leg is emitted as its own SignalPath and its
    halo committed to the oracle before the next net routes."""
    g = oracle.g
    own_pins = _own_pin_cells(g, net)
    # Forbid this net from every dense-pin approach lane EXCEPT the lanes that
    # serve its own pins — so a trunk never parks on a neighbour pin's only
    # approach.
    own_pin_nodes = {
        geom.node_of_pin(ep.position.x, ep.position.y) for ep in net.endpoints
    }
    forbidden_nodes = frozenset(
        anode for anode, served in (approach_reserved or {}).items()
        if not (served & own_pin_nodes)
    )

    layer_step_mul = (1.0, 1.0)
    must_pass_nodes: list[tuple[int, int, int]] = []
    if net.hint is not None:
        if net.hint.prefer_layer is not None:
            other = 1 if net.hint.prefer_layer == 1 else 0
            mul = [1.0, 1.0]
            mul[other] = 2.0
            layer_step_mul = (mul[0], mul[1])
        for wp in net.hint.must_pass:
            ix, iy = geom.node_of_pin(wp.x, wp.y)
            must_pass_nodes.append((wp.layer - 1, ix, iy))

    mix, miy = geom.node_of_pin(net.master.position.x, net.master.position.y)
    master_nodes = [(0, mix, miy), (1, mix, miy)]
    trunk_nodes: set[tuple[int, int, int]] = set()
    out: list[SignalPath] = []

    for i, slave in enumerate(net.slaves):
        six, siy = geom.node_of_pin(slave.position.x, slave.position.y)
        slave_goal = {(0, six, siy), (1, six, siy)}
        if i == 0:
            leg_goals = [{n} for n in must_pass_nodes] + [slave_goal]
            starts = master_nodes
        else:
            leg_goals = [slave_goal]
            starts = list(trunk_nodes)

        full_nodes: list[tuple[int, int, int]] = []
        for goals in leg_goals:
            seg = _lattice_astar(
                geom, oracle, starts, set(goals),
                net_id=net_id, own_pins=own_pins, layer_step_mul=layer_step_mul,
                dense_axis=dense_axis, forbidden_nodes=forbidden_nodes,
            )
            if seg is None:
                # CRITICAL: drop this net's already-committed legs before
                # raising. The coordinator retries nets in other orders / after
                # rip-up, and a half-committed net would poison the oracle —
                # its stale halo would block the very rerouting meant to fix it.
                _rollback_net(oracle, net_id)
                raise RouteFailure(
                    net, f"lattice: no route to {slave.instance_name}", (),
                )
            full_nodes.extend(seg if not full_nodes else seg[1:])
            starts = [seg[-1]]

        trunk_nodes.update(full_nodes)
        name = f"{net.bus_name}_{net.signal}_{slave.instance_name}"
        path = waypoints_to_path(
            name, _nodes_to_waypoints(geom, full_nodes),
            via_diameter=oracle.dims.via_diameter,
        )
        for elt in path.elements:
            if isinstance(elt, WireSegment):
                oracle.commit_run(
                    (elt.start.x, elt.start.y), (elt.end.x, elt.end.y),
                    elt.layer - 1, net_id,
                )
            elif isinstance(elt, Via):
                oracle.commit_via((elt.position.x, elt.position.y), net_id)
        out.append(path)
    return out


def _rollback_net(oracle: LatticeOracle, net_id: int) -> None:
    """Delete every committed owner cell belonging to `net_id`, restoring the
    oracle to its pre-routing state for that net. Lets the coordinator undo a
    backtracked, failed, or ripped net without touching any other net's copper."""
    dead = [cell for cell, owner in oracle.owner.items() if owner == net_id]
    for cell in dead:
        del oracle.owner[cell]


def _seed_order(actions: list[tuple[Net, str | None]]) -> list[Net]:
    """Heuristic net order that seeds the search. Takes the scheduler's actions
    and sorts the second-of-pair nets by priority (route the harder signal of
    each pair — SDA — ahead of the forgiving one — GND). This is the order
    empirically validated to route both production boards in a single pass;
    `_route_bus` explores from it first and only deviates when a board needs a
    different order, so the common case stays on the known-good routing while
    the search adds robustness for boards the seed doesn't satisfy."""
    second_slots = [i for i, (_net, target) in enumerate(actions) if target is not None]
    out = [net for net, _target in actions]
    if len(second_slots) > 1:
        ranked = sorted((actions[i][0] for i in second_slots), key=_net_priority)
        for slot, net in zip(second_slots, ranked, strict=True):
            out[slot] = net
    return out


def _dfs_order(
    geom: LatticeGeom,
    oracle: LatticeOracle,
    nets: list[Net],
    ids: list[int],
    remaining: frozenset[int],
    dense_axis: dict[tuple[int, int], tuple[int, int]] | None,
    approach_reserved: dict[tuple[int, int], set[tuple[int, int]]] | None,
) -> list[SignalPath] | None:
    """Find a net order that routes every net of the bus, by depth-first search
    over orderings with first-failure pruning. At each level try the remaining
    nets in seed order (ascending canonical index); commit the chosen net,
    recurse, and on a dead end roll it back and try the next. The first complete
    branch wins, so a net that boxes in a later one is simply never the prefix
    of a solution. Because `nets` is pre-sorted into the seed order, the search
    reproduces the seed routing whenever it works and is otherwise independent
    of the scheduler's emission order. Returns the routed paths in commit order,
    or None if no order routes the whole bus.

    `remaining` holds canonical indices into `nets`/`ids`; each net keeps a fixed
    id across attempts so `_rollback_net` cleanly removes exactly its copper."""
    if not remaining:
        return []
    for idx in sorted(remaining):
        try:
            legs = _route_one_net_lattice(
                geom, oracle, nets[idx], ids[idx], dense_axis, approach_reserved,
            )
        except RouteFailure:
            continue  # net unroutable on this prefix; its partial legs self-cleaned
        rest = _dfs_order(
            geom, oracle, nets, ids, remaining - {idx}, dense_axis, approach_reserved,
        )
        if rest is not None:
            return legs + rest
        _rollback_net(oracle, ids[idx])  # backtrack: this prefix has no completion
    return None


def _blockers_around(
    geom: LatticeGeom, oracle: LatticeOracle, net: Net,
) -> set[int]:
    """Net ids whose committed copper sits on the lattice cells immediately
    around this net's endpoints — i.e. the foreign nets sealing off its escape
    edges. These are the rip-up candidates: removing them reopens the fan-out."""
    blockers: set[int] = set()
    for ep in net.endpoints:
        ix, iy = geom.node_of_pin(ep.position.x, ep.position.y)
        for dx, dy in _PLANAR_MOVES:
            nix, niy = ix + dx, iy + dy
            if not geom.in_bounds(nix, niy):
                continue
            wa, wb = geom.world(ix, iy), geom.world(nix, niy)
            for layer in (0, 1):
                for cell in _segment_cells(oracle.g, wa, wb, layer, 0.0):
                    owner = oracle.owner.get(cell)
                    if owner is not None:
                        blockers.add(owner)
    return blockers


# Per-net cap on how many times a single net may trigger a rip-up before the
# bus is declared unroutable — bounds the rip-and-reroute loop so it always
# terminates (at most _RIP_BUDGET * n_nets rip events).
_RIP_BUDGET = 3


def _ripup_route_bus(
    geom: LatticeGeom,
    oracle: LatticeOracle,
    nets: list[Net],
    ids: list[int],
    dense_axis: dict[tuple[int, int], tuple[int, int]] | None,
    approach_reserved: dict[tuple[int, int], set[tuple[int, int]]] | None,
) -> list[SignalPath]:
    """Rip-up-and-reroute fallback for buses where no single net order routes
    every net (a mutual block that reordering alone can't resolve). Route nets
    in priority order; when one fails, rip the committed nets fencing its escape
    edges, route the failed net first, then re-queue the ripped nets. A per-net
    rip budget guarantees termination; exhausting it raises `RouteFailure`."""
    paths_by_idx: dict[int, list[SignalPath]] = {}
    rip_count = [0] * len(nets)
    work: deque[int] = deque(range(len(nets)))  # seed order (ascending index)
    while work:
        idx = work.popleft()
        if idx in paths_by_idx:
            continue
        try:
            paths_by_idx[idx] = _route_one_net_lattice(
                geom, oracle, nets[idx], ids[idx], dense_axis, approach_reserved,
            )
            continue
        except RouteFailure:
            pass  # partial legs already rolled back; now make room by ripping
        blocker_ids = _blockers_around(geom, oracle, nets[idx]) - {ids[idx]}
        rippable = sorted(i for i in paths_by_idx if ids[i] in blocker_ids)
        if not rippable or rip_count[idx] >= _RIP_BUDGET:
            raise RouteFailure(
                nets[idx],
                f"lattice: no working order and rip-up exhausted for {nets[idx].signal}",
                tuple(p for legs in paths_by_idx.values() for p in legs),
            )
        rip_count[idx] += 1
        for i in rippable:
            _rollback_net(oracle, ids[i])
            del paths_by_idx[i]
        # Route the blocked net first now its escape is clear, then the ripped.
        for i in reversed(rippable):
            work.appendleft(i)
        work.appendleft(idx)
    return [p for idx in sorted(paths_by_idx) for p in paths_by_idx[idx]]


def _route_bus(
    geom: LatticeGeom,
    oracle: LatticeOracle,
    nets: list[Net],
    base_net_id: int,
    dense_axis: dict[tuple[int, int], tuple[int, int]] | None,
    approach_reserved: dict[tuple[int, int], set[tuple[int, int]]] | None,
) -> tuple[list[SignalPath], int]:
    """Route every net of one bus, independent of the order the scheduler hands
    them in. Try order-search first (it routes both production boards); fall
    back to rip-up only if no order completes. Each net gets a fixed bus-scoped
    id (`base_net_id+1 …`) so rollbacks are exact. Returns the bus's paths plus
    the next free net id for the following bus."""
    next_id = base_net_id + len(nets)
    if not nets:
        return [], next_id
    ids = [base_net_id + 1 + i for i in range(len(nets))]
    paths = _dfs_order(
        geom, oracle, nets, ids, frozenset(range(len(nets))),
        dense_axis, approach_reserved,
    )
    if paths is None:
        paths = _ripup_route_bus(geom, oracle, nets, ids, dense_axis, approach_reserved)
    return paths, next_id


def route_board(board: Board, dims) -> list[SignalPath]:
    """Auto-route every bus on the lattice. Drop-in for
    `autoroute.route_board`: same scheduling (`_ordered_bus_actions`) and
    bundled-pair ordering, but routes on the 2.54mm lattice so output is
    on-pitch by construction — no post-route collapse/align/snap passes."""
    if not board.buses:
        return []
    oracle = LatticeOracle.from_board(board, dims)
    geom = LatticeGeom(oracle.g, dims.pitch)
    # Dense pin rows (≥3 pins within a pitch) → per-node perpendicular approach
    # axis, keyed by lattice node.
    dense_axis: dict[tuple[int, int], tuple[int, int]] = {
        geom.node_of_pin(x, y): axis
        for (x, y), axis in _dense_cluster_pin_axes(board).items()
    }
    # Each dense pin reserves its two perpendicular approach nodes; only the
    # net owning that pin may route through them.
    approach_reserved: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for pnode, (pdx, pdy) in dense_axis.items():
        for k in (1, -1):
            anode = (pnode[0] + k * pdx, pnode[1] + k * pdy)
            approach_reserved.setdefault(anode, set()).add(pnode)
    bound = board.bound_devices()
    paths: list[SignalPath] = []
    net_id = 0
    for bus in board.buses:
        nets_by_signal = {n.signal: n for n in resolve_bus(bus, bound)}
        # `_seed_order` is the priority + pair-bundling heuristic; `_route_bus`
        # explores from it and finds an order that actually routes, so the
        # result no longer depends on the scheduler getting it right.
        nets = _seed_order(_ordered_bus_actions(bus.kind, nets_by_signal))
        try:
            bus_paths, net_id = _route_bus(
                geom, oracle, nets, net_id, dense_axis, approach_reserved,
            )
        except RouteFailure as exc:
            exc.partial = tuple(paths) + tuple(exc.partial or ())
            raise
        paths.extend(bus_paths)
    return paths
