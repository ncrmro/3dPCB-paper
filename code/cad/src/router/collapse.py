"""Cell-list post-processing: simplify tortuous wiggles to clean
L-bends, collapse cardinal staircases into 45° diagonals, then fold
runs of unit cells into Waypoints at corners and layer changes.

Both `_simplify_wiggles` and `_collapse_quadrant_runs` are called by
`route_board` as post-route global passes — every path has been
halo-blocked by then, so the forbidden_check accurately reflects the
final occupancy and the simplification for any one path can't carve
into a corridor reserved for a later net.

Pipeline order matters: simplify-then-collapse. Simplification turns
multi-bend wiggles (often non-monotonic, around dense pin rows) into
clean 1- or 2-bend L-shapes. Collapse then folds monotonic L-shapes
into 45° diagonals where safe.
"""

from __future__ import annotations

import math

from router.grid import Grid
from router.paths import Waypoint
from vitamins.substrate import Point2D as SubstratePoint2D

# Minimum axis-aligned approach length to keep at a pin endpoint after
# collapse. Bare wire can't bend sharply enough to enter a pin barrel at
# 45° — preserving one grid cell of cardinal run lets it drop straight
# in. Was 1.5 mm (3 grid cells) — that was conservative enough to
# swallow whole monotonic-quadrant runs that started at a pin
# (the ESP32 GND fanout in particular), preventing collapse of an
# otherwise-clean NW staircase.
_PIN_APPROACH_RESIDUAL_MM = 0.5

# Wiggle eliminator knobs. A "wiggle" is a sub-path with multiple
# direction changes inside a small bounding box — typically the
# zigzag the router does to escape a dense pin row. The eliminator
# replaces each with a clean L-bend along the perimeter of the box.
_WIGGLE_MAX_BOX_MM = 6.0   # cap on bounding-box dimensions; larger
                           # regions are intentional routing, not a
                           # tight detour around an obstacle.
_WIGGLE_MIN_BENDS = 3      # a clean L is 1 bend; 2 means L-with-jog;
                           # 3+ is a real wiggle worth straightening.


def _simplify_wiggles(
    cells: list[tuple[int, int, int]],
    g: Grid,
    *,
    forbidden_check,  # noqa: ANN001 — matches _collapse_quadrant_runs API
    max_box_mm: float = _WIGGLE_MAX_BOX_MM,
    min_bends: int = _WIGGLE_MIN_BENDS,
) -> list[tuple[int, int, int]]:
    """Replace tortuous sub-paths with clean L-bends along the wiggle box.

    A wiggle is a contiguous same-layer sub-path with ≥`min_bends`
    direction changes whose bounding box fits within `max_box_mm` on
    both axes. For each, tries the candidate L-bends from A to B —
    direct (2 segments) first, then perimeter pushes (3 segments,
    through the box's far corners) — and accepts the safest by cell
    count. "Safe" means every cell on the candidate path passes
    `forbidden_check` (other paths' halos, foreign pin holes, etc.).

    Wire length grows when a perimeter push wins over the original
    wiggle, but visual cleanliness wins — the user can read a single
    L-bend, not so much a 7-segment staircase.

    Runs before `_collapse_quadrant_runs` in the pipeline: simplify
    turns wiggles into L-shapes, then collapse folds the L-shapes
    into 45° diagonals where the geometry permits.
    """
    if len(cells) < 3:
        return list(cells)

    max_box_cells = round(max_box_mm / g.res)

    def cell_safe(layer: int, gy: int, gx: int) -> bool:
        return g.in_bounds(gx, gy) and not forbidden_check(layer, gy, gx)

    def line_cells(
        layer: int, p0: tuple[int, int], p1: tuple[int, int],
    ) -> list[tuple[int, int, int]] | None:
        """Cardinal walk from p0 to p1 (exclusive of p0) as cells.

        Returns None if any cell fails `cell_safe` or if p0/p1 aren't
        axis-aligned. p0 and p1 are (gx, gy).
        """
        gx0, gy0 = p0
        gx1, gy1 = p1
        out: list[tuple[int, int, int]] = []
        if gx0 == gx1:
            sy = 1 if gy1 > gy0 else -1
            cy = gy0
            while cy != gy1:
                cy += sy
                if not cell_safe(layer, cy, gx0):
                    return None
                out.append((layer, cy, gx0))
            return out
        if gy0 == gy1:
            sx = 1 if gx1 > gx0 else -1
            cx = gx0
            while cx != gx1:
                cx += sx
                if not cell_safe(layer, gy0, cx):
                    return None
                out.append((layer, gy0, cx))
            return out
        return None

    def try_polyline(
        layer: int, points: list[tuple[int, int]],
    ) -> list[tuple[int, int, int]] | None:
        """Stitch a sequence of (gx, gy) points into a cell list.

        Each consecutive pair must be cardinal. Returns None if any
        segment is non-cardinal or unsafe.
        """
        out: list[tuple[int, int, int]] = []
        for k in range(len(points) - 1):
            seg = line_cells(layer, points[k], points[k + 1])
            if seg is None:
                return None
            out.extend(seg)
        return out

    result: list[tuple[int, int, int]] = [cells[0]]
    i = 0
    n = len(cells)
    while i < n - 1:
        layer = cells[i][0]
        if cells[i + 1][0] != layer:
            result.append(cells[i + 1])
            i += 1
            continue

        x_min = x_max = cells[i][2]
        y_min = y_max = cells[i][1]
        bends = 0
        prev_dir: tuple[int, int] | None = None
        last_j = i
        j = i + 1
        while j < n:
            cell = cells[j]
            if cell[0] != layer:
                break
            nx_min = min(x_min, cell[2])
            nx_max = max(x_max, cell[2])
            ny_min = min(y_min, cell[1])
            ny_max = max(y_max, cell[1])
            if (nx_max - nx_min) > max_box_cells or (ny_max - ny_min) > max_box_cells:
                break
            x_min, x_max, y_min, y_max = nx_min, nx_max, ny_min, ny_max
            prev = cells[j - 1]
            cur_dir = (cell[1] - prev[1], cell[2] - prev[2])
            if prev_dir is not None and prev_dir != cur_dir:
                bends += 1
            prev_dir = cur_dir
            last_j = j
            j += 1

        wiggle_len = last_j - i
        if wiggle_len >= 2 and bends >= min_bends:
            ax, ay = cells[i][2], cells[i][1]
            bx, by = cells[last_j][2], cells[last_j][1]
            original_segs = bends + 1

            # Candidate corner sequences (excluding A and B endpoints).
            # Direct L-bends first (2 segments); then perimeter pushes
            # via each of the 4 box corners (3 segments) so we can route
            # around an obstacle the direct L would clip.
            candidates: list[list[tuple[int, int]]] = []
            if ax != bx and ay != by:
                candidates.append([(bx, ay)])
                candidates.append([(ax, by)])
            for cx in (x_min, x_max):
                for cy in (y_min, y_max):
                    if (cx, cy) in {(ax, ay), (bx, by)}:
                        continue
                    if cx != ax and cy != by:
                        candidates.append([(cx, ay), (cx, by)])
                    if cy != ay and cx != bx:
                        candidates.append([(ax, cy), (bx, cy)])

            # Best = fewest segments (= fewest direction changes), then
            # fewest cells as a tiebreaker. Visual cleanliness comes
            # from segment-count drop; cell count is secondary.
            best: list[tuple[int, int, int]] | None = None
            best_segs = original_segs
            for corners in candidates:
                points = [(ax, ay), *corners, (bx, by)]
                walk = try_polyline(layer, points)
                if walk is None:
                    continue
                walk_segs = len(points) - 1
                if walk_segs < best_segs or (
                    walk_segs == best_segs and best is not None and len(walk) < len(best)
                ):
                    best = walk
                    best_segs = walk_segs

            # Accept only if we reduced the segment count by at least 2
            # (one bend is a clean L — replacing a 3-bend wiggle with
            # another 3-bend shape isn't a real win).
            if best is not None and best_segs <= original_segs - 2:
                result.extend(best)
                i = last_j
                continue

        result.append(cells[i + 1])
        i += 1

    return result


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
                        # Residual cardinal run after the diagonal.
                        # Safety-check each cell + the one perpendicular
                        # neighbour the halo would brush. Without this,
                        # the residual can land on cells the original
                        # staircase never visited (different L-corner
                        # placement) — possibly on another wire or in
                        # another path's halo.
                        if abs_dgx >= abs_dgy:
                            residual = abs_dgx - diag_cells
                            for k in range(1, residual + 1):
                                ngy = gy
                                ngx = gx + k * sx
                                for c in ((layer, ngy, ngx),
                                          (layer, ngy - sy, ngx)):
                                    if not g.in_bounds(c[2], c[1]) \
                                            or not cell_safe(*c):
                                        safe = False
                                        break
                                if not safe:
                                    break
                                new_middle.append((layer, ngy, ngx))
                        else:
                            residual = abs_dgy - diag_cells
                            for k in range(1, residual + 1):
                                ngy = gy + k * sy
                                ngx = gx
                                for c in ((layer, ngy, ngx),
                                          (layer, ngy, ngx - sx)):
                                    if not g.in_bounds(c[2], c[1]) \
                                            or not cell_safe(*c):
                                        safe = False
                                        break
                                if not safe:
                                    break
                                new_middle.append((layer, ngy, ngx))
                        if safe and new_middle and new_middle[-1] == B:
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
