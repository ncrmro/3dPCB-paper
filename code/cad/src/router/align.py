"""Post-route alignment + cleanup passes.

Two passes that run AFTER A* but BEFORE/AFTER `_collapse_one_raw`:

* `align_pair_pitch` — operates on raw cell lists. Walks each bus pair
  per slave, finds the longest horizontal (or vertical) run in the
  second-routed path, finds the parallel run in the first-routed
  partner, and shifts the second run's cross-axis position to match the
  natural pin pitch derived from the device library. Runs **before**
  collapse so chamfers + diagonals are re-derived against the aligned
  geometry. Geometry-driven, not net-name-driven: any bus pair gets it.

* `merge_via_clusters` — operates on `SignalPath`s after collapse.
  Detects `Via → short WireSegment → Via` triples that form an L-jog
  (a tight layer-hop bracketing a foreign-layer crossing) and tries
  three alternatives in order: eliminate both vias if the surrounding
  layer is clear, swap which layer carries the long run, or coalesce
  to a single via at one end. Runs **after** collapse since via
  positions are stable WireSegment boundaries by then.

Both passes share the same forbidden-cell logic used by
`_collapse_one_raw` — `g.blocked` minus the path's own exclusive halo
and `own_pin_cells`. That way an alignment shift can't open a
wall-floor gap against another wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from router.grid import Grid

# Minimum length (in cells) for a run to be considered for alignment.
# 6 cells = 3 mm — short runs don't visually benefit from pitch alignment
# and chasing them risks collateral damage to nearby short bends.
_ALIGN_MIN_RUN_CELLS = 6


@dataclass(frozen=True)
class _Run:
    """A contiguous cardinal run inside a cell list."""

    start_idx: int    # index of first cell in the run
    end_idx: int      # index of last cell (inclusive)
    layer: int
    axis: str         # "H" for horizontal (gy constant) or "V" (gx constant)
    constant: int     # gy if H, gx if V
    other_lo: int     # min gx if H, min gy if V
    other_hi: int     # max gx if H, max gy if V

    @property
    def length(self) -> int:
        return self.end_idx - self.start_idx + 1


def _find_runs(cells: list[tuple[int, int, int]], min_len: int) -> list[_Run]:
    """Return every contiguous H/V run in `cells` of length ≥ `min_len`.

    A run is a maximal subsequence of consecutive cells on the same
    layer where one coordinate is constant and the other increments
    by ±1 each step.
    """
    runs: list[_Run] = []
    if len(cells) < 2:
        return runs
    i = 0
    while i < len(cells) - 1:
        c = cells[i]
        cn = cells[i + 1]
        if c[0] != cn[0]:
            i += 1
            continue
        # Determine axis from the first move.
        if c[1] == cn[1] and abs(cn[2] - c[2]) == 1:
            axis = "H"
        elif c[2] == cn[2] and abs(cn[1] - c[1]) == 1:
            axis = "V"
        else:
            i += 1
            continue
        j = i + 1
        while j < len(cells) - 1:
            a = cells[j]
            b = cells[j + 1]
            if a[0] != b[0]:
                break
            if axis == "H" and (a[1] != b[1] or abs(b[2] - a[2]) != 1):
                break
            if axis == "V" and (a[2] != b[2] or abs(b[1] - a[1]) != 1):
                break
            j += 1
        run_len = j - i + 1
        if run_len >= min_len:
            if axis == "H":
                gys = c[1]
                gxs = [cells[k][2] for k in range(i, j + 1)]
                runs.append(_Run(i, j, c[0], "H", gys, min(gxs), max(gxs)))
            else:
                gxs = c[2]
                gys = [cells[k][1] for k in range(i, j + 1)]
                runs.append(_Run(i, j, c[0], "V", gxs, min(gys), max(gys)))
        i = j
    return runs


def _find_partner_run(
    partner_cells: list[tuple[int, int, int]],
    run: _Run,
    pitch_cells: int,
    pitch_tol: int = 1,
) -> _Run | None:
    """Find the most-overlapping run in `partner_cells` that's parallel
    to `run` (same axis + layer, projected range overlapping). Returns
    the candidate even if its current offset already matches pitch — the
    caller decides whether to shift.
    """
    partner_runs = _find_runs(partner_cells, _ALIGN_MIN_RUN_CELLS)
    best: _Run | None = None
    best_overlap = 0
    for pr in partner_runs:
        if pr.layer != run.layer or pr.axis != run.axis:
            continue
        # Overlap in the projected axis.
        overlap_lo = max(run.other_lo, pr.other_lo)
        overlap_hi = min(run.other_hi, pr.other_hi)
        if overlap_hi <= overlap_lo:
            continue
        overlap = overlap_hi - overlap_lo
        # Partner must be within reasonable cross-axis distance —
        # other parallel runs further out aren't this run's pair-mate.
        if abs(pr.constant - run.constant) > pitch_cells + pitch_tol + 4:
            continue
        if overlap > best_overlap:
            best_overlap = overlap
            best = pr
    return best


def _bridge_cells(
    layer: int,
    a: tuple[int, int],
    b: tuple[int, int],
) -> list[tuple[int, int, int]]:
    """Cardinal bridge cells (exclusive of `a`, inclusive of `b`) from
    `a` to `b`. Both must share one coordinate (no diagonal bridging).
    """
    gy_a, gx_a = a
    gy_b, gx_b = b
    cells: list[tuple[int, int, int]] = []
    if gy_a == gy_b and gx_a == gx_b:
        return cells
    if gy_a == gy_b:
        step = 1 if gx_b > gx_a else -1
        gx = gx_a + step
        while True:
            cells.append((layer, gy_a, gx))
            if gx == gx_b:
                break
            gx += step
    elif gx_a == gx_b:
        step = 1 if gy_b > gy_a else -1
        gy = gy_a + step
        while True:
            cells.append((layer, gy, gx_a))
            if gy == gy_b:
                break
            gy += step
    return cells


def _shift_run(
    cells: list[tuple[int, int, int]],
    run: _Run,
    target_constant: int,
) -> list[tuple[int, int, int]]:
    """Return a new cell list with `run`'s cross-axis position shifted
    to `target_constant`. The cells before `run.start_idx` and after
    `run.end_idx` are unchanged; cardinal bridge cells are inserted at
    each end to keep the path connected.

    Pre-conditions: cells[run.start_idx - 1] (if exists) shares the
    same axis-projection coord as cells[run.start_idx], and similarly
    for the post end. Caller verifies via _adjacent_is_perpendicular.
    """
    if target_constant == run.constant:
        return list(cells)
    layer = run.layer
    if run.axis == "H":
        # Re-emit run cells at the new gy.
        new_run = [(layer, target_constant, c[2]) for c in cells[run.start_idx:run.end_idx + 1]]
        first_gx = cells[run.start_idx][2]
        last_gx = cells[run.end_idx][2]
        # Pre bridge: from cells[run.start_idx - 1] to (layer, target_constant, first_gx).
        prefix = list(cells[:run.start_idx])
        if prefix:
            pre_last = prefix[-1]
            # Walk from pre_last to (target_constant, first_gx) cardinally.
            # Pre_last shares first_gx if the immediately-prior move was
            # perpendicular (vertical for an H run). Otherwise abort.
            if pre_last[0] != layer or pre_last[2] != first_gx:
                return list(cells)  # adjacency check failed
            bridge = _bridge_cells(
                layer, (pre_last[1], pre_last[2]), (target_constant, first_gx),
            )
            # `bridge` includes the destination cell (the new run's first cell).
            # Drop its last entry so the new run starts cleanly with new_run[0].
            if bridge and bridge[-1] == new_run[0]:
                bridge = bridge[:-1]
            prefix.extend(bridge)
        # Post bridge: from (layer, target_constant, last_gx) to cells[run.end_idx + 1].
        suffix: list[tuple[int, int, int]] = []
        if run.end_idx + 1 < len(cells):
            post_first = cells[run.end_idx + 1]
            if post_first[0] != layer or post_first[2] != last_gx:
                return list(cells)  # adjacency check failed
            bridge = _bridge_cells(
                layer, (target_constant, last_gx), (post_first[1], post_first[2]),
            )
            # `bridge` ends with post_first; the original cells[run.end_idx+1:]
            # starts with post_first, so we use bridge as-is and skip the first
            # element of the tail.
            suffix.extend(bridge)
            suffix.extend(cells[run.end_idx + 2:])
        else:
            # Run was the path's tail — no post bridge.
            pass
        return prefix + new_run + suffix
    else:  # V
        new_run = [(layer, c[1], target_constant) for c in cells[run.start_idx:run.end_idx + 1]]
        first_gy = cells[run.start_idx][1]
        last_gy = cells[run.end_idx][1]
        prefix = list(cells[:run.start_idx])
        if prefix:
            pre_last = prefix[-1]
            if pre_last[0] != layer or pre_last[1] != first_gy:
                return list(cells)
            bridge = _bridge_cells(
                layer, (pre_last[1], pre_last[2]), (first_gy, target_constant),
            )
            if bridge and bridge[-1] == new_run[0]:
                bridge = bridge[:-1]
            prefix.extend(bridge)
        suffix = []
        if run.end_idx + 1 < len(cells):
            post_first = cells[run.end_idx + 1]
            if post_first[0] != layer or post_first[1] != last_gy:
                return list(cells)
            bridge = _bridge_cells(
                layer, (last_gy, target_constant), (post_first[1], post_first[2]),
            )
            suffix.extend(bridge)
            suffix.extend(cells[run.end_idx + 2:])
        return prefix + new_run + suffix


def _cells_safe(
    cells: list[tuple[int, int, int]],
    forbidden_check: Callable[[int, int, int], bool],
) -> bool:
    """True iff every cell in `cells` is non-forbidden."""
    return not any(forbidden_check(*c) for c in cells)


def align_pair_pitch(
    raw_paths,
    g: "Grid",
    forbidden_check_factory: Callable[[object], Callable[[int, int, int], bool]],
) -> None:
    """For each bus pair (sig1, sig2) per slave, find the longest
    parallel run in sig2's path and shift it to match the natural pair
    pitch derived from the pair's master pins.

    Mutates `raw_path.raw_cells` in place for paths whose alignment
    improves AND whose shifted cells pass the forbidden-cell check
    (built by the caller, same logic used by `_collapse_one_raw`).
    """
    # Index paths by (bus_name, signal, slave_name) for partner lookup.
    by_key: dict[tuple[str, str, str], object] = {}
    for rp in raw_paths:
        if not (rp.bus_name and rp.signal and rp.slave_name):
            continue
        by_key[(rp.bus_name, rp.signal, rp.slave_name)] = rp

    for rp2 in raw_paths:
        if rp2.partner_signal is None or rp2.pair_pitch_cells is None:
            continue
        partner_key = (rp2.bus_name, rp2.partner_signal, rp2.slave_name)
        rp1 = by_key.get(partner_key)
        if rp1 is None:
            continue
        forbidden_check = forbidden_check_factory(rp2)
        runs2 = _find_runs(rp2.raw_cells, _ALIGN_MIN_RUN_CELLS)
        # Apply shifts longest-first so the most-impactful run wins.
        runs2.sort(key=lambda r: r.length, reverse=True)
        applied = False
        for run in runs2:
            if applied:
                # Re-find after first shift since indices changed.
                break
            partner_run = _find_partner_run(rp1.raw_cells, run, rp2.pair_pitch_cells)
            if partner_run is None:
                continue
            current_offset = run.constant - partner_run.constant
            sign = 1 if current_offset > 0 else -1
            desired_offset = sign * rp2.pair_pitch_cells
            if abs(abs(current_offset) - rp2.pair_pitch_cells) == 0:
                continue
            target_constant = partner_run.constant + desired_offset
            new_cells = _shift_run(rp2.raw_cells, run, target_constant)
            if new_cells == rp2.raw_cells:
                continue
            if not _cells_safe(new_cells, forbidden_check):
                continue
            rp2.raw_cells = new_cells
            applied = True
