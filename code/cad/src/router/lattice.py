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
from collections.abc import Iterator

from router.astar import _W_BEND, _W_STEP, _W_VIA, _edge_penalty
from router.grid import Grid, _build_grid

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


def _lattice_astar(
    geom: LatticeGeom,
    oracle: LatticeOracle,
    starts: list[tuple[int, int, int]],
    goals: set[tuple[int, int, int]],
    *,
    net_id: int,
    own_pins: frozenset[tuple[int, int, int]],
    layer_step_mul: tuple[float, float] = (1.0, 1.0),
) -> list[tuple[int, int, int]] | None:
    """A* over `(layer, ix, iy)` nodes. Cardinal + 45° diagonal planar moves
    and a via (layer flip); a candidate edge is admitted only if the oracle
    finds its swept channel/via clear. Returns the node path or None."""
    if not starts or not goals:
        return None

    open_heap: list[
        tuple[float, float, tuple[int, int, int], tuple[int, int, int] | None]
    ] = []
    g_cost: dict[tuple[int, int, int], float] = {}
    parents: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
    for s in starts:
        g_cost[s] = 0.0
        parents[s] = None
        h = min(_octile(s, goal) for goal in goals)
        heapq.heappush(open_heap, (h, 0.0, s, None))

    while open_heap:
        _f, gc, cur, prev_dir = heapq.heappop(open_heap)
        if cur in goals:
            path = [cur]
            while parents[path[-1]] is not None:
                path.append(parents[path[-1]])  # type: ignore[arg-type]
            path.reverse()
            return path
        if gc > g_cost.get(cur, math.inf):
            continue
        layer, ix, iy = cur
        cur_world = geom.world(ix, iy)

        for dx, dy in _PLANAR_MOVES:
            nix, niy = ix + dx, iy + dy
            if not geom.in_bounds(nix, niy):
                continue
            nbr = (layer, nix, niy)
            nbr_world = geom.world(nix, niy)
            if not oracle.run_clear(cur_world, nbr_world, layer, net_id, own_pins):
                continue
            base = _SQRT2 if (dx and dy) else 1.0
            step = base * _W_STEP * layer_step_mul[layer]
            step += _edge_penalty(geom.g, nix * geom.n, niy * geom.n)
            step_dir = (0, dy, dx)
            if prev_dir is not None and prev_dir != step_dir:
                step += _W_BEND
            new_g = gc + step
            if new_g < g_cost.get(nbr, math.inf):
                g_cost[nbr] = new_g
                parents[nbr] = cur
                h = min(_octile(nbr, goal) for goal in goals)
                heapq.heappush(open_heap, (new_g + h, new_g, nbr, step_dir))

        other = 1 - layer
        nbr = (other, ix, iy)
        if oracle.via_clear(cur_world, net_id, own_pins):
            step = _W_VIA
            step_dir = (other - layer, 0, 0)
            if prev_dir is not None and prev_dir != step_dir:
                step += _W_BEND
            new_g = gc + step
            if new_g < g_cost.get(nbr, math.inf):
                g_cost[nbr] = new_g
                parents[nbr] = cur
                h = min(_octile(nbr, goal) for goal in goals)
                heapq.heappush(open_heap, (new_g + h, new_g, nbr, step_dir))

    return None
