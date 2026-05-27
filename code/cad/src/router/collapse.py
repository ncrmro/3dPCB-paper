"""Cell-list post-processing: collapse axis-aligned staircases into 45°
diagonals, then fold runs of unit cells into Waypoints at corners and
layer changes.

`_collapse_quadrant_runs` is currently dormant — wiring it into the
routing pipeline needs a post-route global-halo pass with awareness of
every other path's footprint. The function is kept here so the future
post-route step has a ready primitive to call.
"""

from __future__ import annotations

import math

from router.grid import Grid
from router.paths import Waypoint
from vitamins.substrate import Point2D as SubstratePoint2D

# Minimum axis-aligned approach length to keep at a pin endpoint after
# collapse. Bare wire can't bend sharply enough to enter a pin barrel at
# 45° — preserving a short cardinal run lets it drop straight in.
_PIN_APPROACH_RESIDUAL_MM = 1.5


def _collapse_quadrant_runs(
    cells: list[tuple[int, int, int]],
    g: Grid,
    *,
    own_pin_xys: set[tuple[float, float]],
    forbidden_check,
) -> list[tuple[int, int, int]]:
    """Rewrite cardinal staircases into 45° diagonals.

    A "monotonic-quadrant run" is a maximal sequence of cardinal grid
    steps on a single layer that all advance in one quadrant — every
    x-step has the same sign and every y-step has the same sign. Such
    a run zigzags NE / NW / SE / SW; the collapse replaces it with a
    single 45° diagonal of length `min(|Δgx|, |Δgy|)` plus an
    axis-aligned residual covering the magnitude difference.

    A run is left alone if either endpoint sits on this net's own pin
    xy — the pin needs a straight axis-aligned approach so the wire
    drops into the barrel without binding (see
    `_PIN_APPROACH_RESIDUAL_MM`).

    `forbidden_check(layer, gy, gx) -> bool` is True for cells that the
    diagonal must not enter — foreign pin cells, other-net halos, etc.
    Cells in the original A* path are by definition not forbidden (A*
    walked them), so the safety check only needs to inspect the new
    diagonal-interior cells.
    """
    if len(cells) < 3:
        return list(cells)

    def cell_safe(layer: int, gy: int, gx: int) -> bool:
        return not forbidden_check(layer, gy, gx)

    result: list[tuple[int, int, int]] = [cells[0]]
    i = 0
    n = len(cells)
    while i < n - 1:
        layer = cells[i][0]
        sx = sy = 0
        j = i + 1
        while j < n:
            cur = cells[j]
            prev = cells[j - 1]
            if cur[0] != layer:
                break
            dgx = cur[2] - prev[2]
            dgy = cur[1] - prev[1]
            if dgx != 0 and dgy != 0:
                break  # already diagonal — leave alone
            if dgx == 0 and dgy == 0:
                break
            tx = 1 if dgx > 0 else (-1 if dgx < 0 else 0)
            ty = 1 if dgy > 0 else (-1 if dgy < 0 else 0)
            if tx != 0:
                if sx == 0:
                    sx = tx
                elif sx != tx:
                    break
            if ty != 0:
                if sy == 0:
                    sy = ty
                elif sy != ty:
                    break
            j += 1
        run_end = j - 1

        if run_end - i >= 2 and sx != 0 and sy != 0:
            pin_res_cells = int(math.ceil(_PIN_APPROACH_RESIDUAL_MM / g.res))
            A_cell = cells[i]
            B_cell = cells[run_end]
            wx_a, wy_a = g.to_world(A_cell[2], A_cell[1])
            wx_b, wy_b = g.to_world(B_cell[2], B_cell[1])
            a_pin = (round(wx_a, 3), round(wy_a, 3)) in own_pin_xys
            b_pin = (round(wx_b, 3), round(wy_b, 3)) in own_pin_xys
            pre = pin_res_cells if a_pin else 0
            post = pin_res_cells if b_pin else 0
            sub_i = i + pre
            sub_end = run_end - post
            if sub_end - sub_i >= 2:
                A = cells[sub_i]
                B = cells[sub_end]
                abs_dgx = abs(B[2] - A[2])
                abs_dgy = abs(B[1] - A[1])
                if abs_dgx >= 1 and abs_dgy >= 1:
                    diag_cells = min(abs_dgx, abs_dgy)
                    new_middle: list[tuple[int, int, int]] = []
                    gx, gy = A[2], A[1]
                    safe = True
                    for k in range(1, diag_cells + 1):
                        ngy = gy + k * sy
                        ngx = gx + k * sx
                        # Diagonal-interior cell + the two cardinal
                        # neighbors the channel halo would brush.
                        for c in ((layer, ngy, ngx),
                                  (layer, ngy - sy, ngx),
                                  (layer, ngy, ngx - sx)):
                            if not g.in_bounds(c[2], c[1]):
                                safe = False
                                break
                            if not cell_safe(*c):
                                safe = False
                                break
                        if not safe:
                            break
                        new_middle.append((layer, ngy, ngx))
                    if safe:
                        gx += diag_cells * sx
                        gy += diag_cells * sy
                        if abs_dgx >= abs_dgy:
                            residual = abs_dgx - diag_cells
                            for k in range(1, residual + 1):
                                new_middle.append((layer, gy, gx + k * sx))
                        else:
                            residual = abs_dgy - diag_cells
                            for k in range(1, residual + 1):
                                new_middle.append((layer, gy + k * sy, gx))
                        if new_middle and new_middle[-1] == B:
                            # Keep the pre/post cardinal segments as-is
                            # so pin approaches stay axis-aligned.
                            result.extend(cells[i + 1:sub_i + 1])
                            result.extend(new_middle)
                            result.extend(cells[sub_end + 1:run_end + 1])
                            i = run_end
                            continue

        result.append(cells[i + 1])
        i += 1

    return result


def _path_to_waypoints(g: Grid, cells: list[tuple[int, int, int]]) -> list[Waypoint]:
    """Collapse a sequence of unit grid steps into Waypoints at every
    corner / layer change.
    """
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
