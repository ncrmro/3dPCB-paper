"""A* search on the routing grid + cost weights.

Step cost favours axis-aligned runs and penalises layer transitions
(vias), board-edge proximity, and crossings. An optional
"parallel-bias" set rewards cells next to a pair-mate signal so a
bundled pair (VCC/GND, SCL/SDA) tends to run alongside its partner.
"""

from __future__ import annotations

import heapq
import math

from router.grid import Grid

_W_STEP        = 1.0
_W_VIA         = 1.5   # cost of a single layer transition — kept low so the
                       # router uses BOTH layers instead of packing L1.
_W_CROSSING    = 10.0
_W_EDGE        = 3.0
_EDGE_RADIUS_MM = 1.0   # within this distance of the board edge → edge penalty

_W_PARALLEL_BONUS = 0.4   # step-cost discount when a candidate cell sits
                          # next to a cell in `parallel_target_cells` —
                          # rewards pair-mate signals running parallel.
_PARALLEL_MIN = 2         # Min Manhattan-distance for the parallel
                          # bonus. Below this the halo would already
                          # block — and we don't want to push the
                          # second signal into the first's pin-approach
                          # corridor, where halos are by design relaxed.
_PARALLEL_MAX = 5         # Max Manhattan-distance for the bonus.

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
    parallel_target_cells: set[tuple[int, int, int]] | None = None,
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

    # Precompute the "near parallel" set: every cell at Manhattan
    # distance _PARALLEL_MIN..MAX from a cell in parallel_target_cells,
    # on the SAME layer. Cells in this set get a step-cost discount so
    # A* prefers paths that run alongside their pair-mate signal at a
    # legitimate (post-halo) corridor distance.
    #
    # Cells closer than _PARALLEL_MIN are excluded — those are inside
    # the halo or in the pair-mate's pin-approach corridor, and giving
    # them a bonus would invite the second signal to crawl right next
    # to the first (collapsing wall_floor).
    #
    # Pin approach cells (own + others) are excluded outright: that's
    # where halos are by design relaxed, so giving them a parallel
    # bonus would pull the second signal into the first's pin row at
    # wall-floor-violating distance. The bonus applies only in "open"
    # board space between corridors.
    near_parallel: set[tuple[int, int, int]] = set()
    if parallel_target_cells:
        all_approach = getattr(g, "_pin_approach_cells", set())
        target_set = parallel_target_cells
        for (ly, gy, gx) in target_set:
            for dy in range(-_PARALLEL_MAX, _PARALLEL_MAX + 1):
                rem = _PARALLEL_MAX - abs(dy)
                for dx in range(-rem, rem + 1):
                    dist = abs(dx) + abs(dy)
                    if dist < _PARALLEL_MIN:
                        continue
                    cell = (ly, gy + dy, gx + dx)
                    if cell in all_approach:
                        continue
                    near_parallel.add(cell)
        near_parallel -= target_set

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

    parents: dict[tuple[int, int, int], tuple[int, int, int] | None] = dict.fromkeys(starts)

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
            if near_parallel and nbr in near_parallel:
                step_cost = max(step_cost - _W_PARALLEL_BONUS, 0.05)
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
