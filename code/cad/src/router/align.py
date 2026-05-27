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

import math
from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from router.grid import Grid
    from vitamins.substrate import SignalPath

# Minimum length (in cells) for a run to be considered for alignment.
# 6 cells = 3 mm — short runs don't visually benefit from pitch alignment
# and chasing them risks collateral damage to nearby short bends.
_ALIGN_MIN_RUN_CELLS = 6

# Maximum L2 segment length (mm) for a (via, segment, via) triple to be
# considered an "L-jog cluster" worth trying to collapse. Long L2 runs
# are intentional foreign-layer hops; only short ones get re-evaluated.
_VIA_CLUSTER_MAX_MM = 4.0

# Maximum length (mm) of the perpendicular stub between a long cardinal
# run and a via for the stub to qualify for elimination by pulling the
# via outward to align with the long run. 1.5 mm covers the typical
# 0.5–1.0 mm pin-pitch-vs-grid-residual cases without absorbing
# intentional short stubs that serve a real geometric purpose.
_VIA_STUB_MAX_MM = 1.5


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
    to `target_constant`.

    The adjacent perpendicular run on each side is *extended* or
    *trimmed* depending on its direction relative to the shift:

      * pre direction same sign as shift → bridge cells extend pre to
        reach the new corner.
      * pre direction opposite to shift → the new corner is already
        somewhere inside the existing pre run; trim cells off the tail
        instead of inserting a U-turn (which the collapse pass would
        otherwise fold into a visible 0.5 mm diagonal kink).
      * post direction same sign as shift → trim cells off the suffix
        head (the new run end now sits past an existing post cell).
      * post direction opposite to shift → bridge cells extend post.

    Returns the original cell list unchanged if any invariant fails
    (e.g. adjacent cells not perpendicular, pre run too short to trim).
    """
    if target_constant == run.constant:
        return list(cells)
    layer = run.layer
    delta = target_constant - run.constant
    shift_sign = 1 if delta > 0 else -1
    abs_delta = abs(delta)

    if run.axis == "H":
        # Detect the full "chain" at this constant gy: walk forward and
        # backward including any cells (including via layer transitions)
        # that share gy=run.constant. A trunk bounded by vias on both
        # ends extends through them to the parallel run on the other
        # layer — shifting the trunk requires shifting the via Y + the
        # other-layer run together so the chain stays connected.
        chain_start = run.start_idx
        while chain_start > 0 and cells[chain_start - 1][1] == run.constant:
            chain_start -= 1
        chain_end = run.end_idx
        while chain_end + 1 < len(cells) and cells[chain_end + 1][1] == run.constant:
            chain_end += 1

        new_run = [
            (c[0], target_constant, c[2])
            for c in cells[chain_start:chain_end + 1]
        ]
        first_layer = cells[chain_start][0]
        first_gx = cells[chain_start][2]
        last_layer = cells[chain_end][0]
        last_gx = cells[chain_end][2]

        prefix = list(cells[:chain_start])
        if prefix:
            pre_last = prefix[-1]
            if pre_last[0] != first_layer or pre_last[2] != first_gx:
                return list(cells)
            pre_dir = run.constant - pre_last[1]
            if pre_dir == 0:
                return list(cells)
            pre_sign = 1 if pre_dir > 0 else -1
            if pre_sign * shift_sign < 0:
                # Pre runs opposite to the shift → trim cells off the
                # prefix tail so the new corner lands on an existing
                # pre cell (no U-turn).
                trim_idx = len(prefix) - 1
                for _ in range(abs_delta):
                    if trim_idx < 0:
                        return list(cells)
                    c = prefix[trim_idx]
                    if c[0] != first_layer or c[2] != first_gx:
                        return list(cells)
                    trim_idx -= 1
                prefix = prefix[:trim_idx + 1]
                if prefix:
                    new_last = prefix[-1]
                    if (new_last[0] != first_layer or new_last[2] != first_gx
                            or abs(new_last[1] - target_constant) != 1):
                        return list(cells)
            else:
                # Pre runs the same way as the shift → extend pre by
                # bridging from its old end to the new corner.
                bridge = _bridge_cells(
                    first_layer, (pre_last[1], pre_last[2]), (target_constant, first_gx),
                )
                if bridge and bridge[-1] == new_run[0]:
                    bridge = bridge[:-1]
                prefix.extend(bridge)

        suffix: list[tuple[int, int, int]] = []
        if chain_end + 1 < len(cells):
            post_first = cells[chain_end + 1]
            if post_first[0] != last_layer or post_first[2] != last_gx:
                return list(cells)
            post_dir = post_first[1] - run.constant
            if post_dir == 0:
                return list(cells)
            post_sign = 1 if post_dir > 0 else -1
            tail = list(cells[chain_end + 1:])
            if post_sign * shift_sign > 0:
                # Post runs the same way as the shift → trim cells off
                # the suffix head so the new run end lands on an
                # existing post cell.
                trim_idx = 0
                for _ in range(abs_delta):
                    if trim_idx >= len(tail):
                        return list(cells)
                    c = tail[trim_idx]
                    if c[0] != last_layer or c[2] != last_gx:
                        return list(cells)
                    trim_idx += 1
                suffix = tail[trim_idx:]
                if suffix:
                    new_first = suffix[0]
                    if (new_first[0] != last_layer or new_first[2] != last_gx
                            or abs(new_first[1] - target_constant) != 1):
                        return list(cells)
            else:
                # Post runs opposite to the shift → extend post.
                bridge = _bridge_cells(
                    last_layer, (target_constant, last_gx), (post_first[1], post_first[2]),
                )
                suffix.extend(bridge)
                suffix.extend(cells[chain_end + 2:])

        return prefix + new_run + suffix

    # V axis: same logic with gx/gy roles swapped.
    new_run = [(layer, c[1], target_constant) for c in cells[run.start_idx:run.end_idx + 1]]
    first_gy = cells[run.start_idx][1]
    last_gy = cells[run.end_idx][1]

    prefix = list(cells[:run.start_idx])
    if prefix:
        pre_last = prefix[-1]
        if pre_last[0] != layer or pre_last[1] != first_gy:
            return list(cells)
        pre_dir = run.constant - pre_last[2]
        if pre_dir == 0:
            return list(cells)
        pre_sign = 1 if pre_dir > 0 else -1
        if pre_sign * shift_sign < 0:
            trim_idx = len(prefix) - 1
            for _ in range(abs_delta):
                if trim_idx < 0:
                    return list(cells)
                c = prefix[trim_idx]
                if c[0] != layer or c[1] != first_gy:
                    return list(cells)
                trim_idx -= 1
            prefix = prefix[:trim_idx + 1]
            if prefix:
                new_last = prefix[-1]
                if (new_last[0] != layer or new_last[1] != first_gy
                        or abs(new_last[2] - target_constant) != 1):
                    return list(cells)
        else:
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
        post_dir = post_first[2] - run.constant
        if post_dir == 0:
            return list(cells)
        post_sign = 1 if post_dir > 0 else -1
        tail = list(cells[run.end_idx + 1:])
        if post_sign * shift_sign > 0:
            trim_idx = 0
            for _ in range(abs_delta):
                if trim_idx >= len(tail):
                    return list(cells)
                c = tail[trim_idx]
                if c[0] != layer or c[1] != last_gy:
                    return list(cells)
                trim_idx += 1
            suffix = tail[trim_idx:]
            if suffix:
                new_first = suffix[0]
                if (new_first[0] != layer or new_first[1] != last_gy
                        or abs(new_first[2] - target_constant) != 1):
                    return list(cells)
        else:
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
        # Iterate: each successful shift may unmask a new candidate run
        # (indices change after a shift, and a midline trunk that
        # previously sat behind a longer south run becomes reachable
        # once the south run is aligned). Bounded by the number of
        # _find_runs results; in practice converges after ≤ 3 passes.
        max_iters = 8
        while max_iters > 0:
            max_iters -= 1
            runs2 = _find_runs(rp2.raw_cells, _ALIGN_MIN_RUN_CELLS)
            runs2.sort(key=lambda r: r.length, reverse=True)
            progress = False
            for run in runs2:
                partner_run = _find_partner_run(rp1.raw_cells, run, rp2.pair_pitch_cells)
                if partner_run is None:
                    continue
                current_offset = run.constant - partner_run.constant
                if current_offset == 0:
                    continue
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
                progress = True
                break
            if not progress:
                break


def _seg_length_mm(seg) -> float:
    dx = seg.end.x - seg.start.x
    dy = seg.end.y - seg.start.y
    return math.hypot(dx, dy)


def _seg_path_layer_cells(
    g: "Grid", x0: float, y0: float, x1: float, y1: float, layer: int,
) -> list[tuple[int, int, int]]:
    """Rasterise a straight-line cardinal segment to grid cells on `layer`.
    Caller must guarantee the segment is axis-aligned.
    """
    gx0, gy0 = g.to_grid(x0, y0)
    gx1, gy1 = g.to_grid(x1, y1)
    cells: list[tuple[int, int, int]] = []
    if gx0 == gx1:
        step = 1 if gy1 > gy0 else -1
        gy = gy0
        while True:
            cells.append((layer, gy, gx0))
            if gy == gy1:
                break
            gy += step
    elif gy0 == gy1:
        step = 1 if gx1 > gx0 else -1
        gx = gx0
        while True:
            cells.append((layer, gy0, gx))
            if gx == gx1:
                break
            gx += step
    return cells


def merge_via_clusters(
    paths: list["SignalPath"],
    g: "Grid",
    forbidden_check_factory: Callable[[object], Callable[[int, int, int], bool]],
    raw_paths,
) -> list["SignalPath"]:
    """Try to collapse `Via → short WireSegment → Via` triples to a single
    same-layer crossing when the surrounding layer can bridge the gap.

    Returns a new list of SignalPaths (paths with no qualifying cluster
    are unchanged). The forbidden_check determines whether the bridge
    cells on the surrounding layer are clear — same predicate the
    collapse pass uses, so cluster removal never opens a wall-floor gap.
    """
    from vitamins.substrate import Point2D, SignalPath, Via, WireSegment

    raw_by_name = {rp.name: rp for rp in raw_paths}
    out: list[SignalPath] = []
    for path in paths:
        elements = list(path.elements)
        rp = raw_by_name.get(path.name)
        if rp is None:
            out.append(path)
            continue
        forbidden_check = forbidden_check_factory(rp)
        changed = False
        i = 0
        while i + 2 < len(elements):
            v1, seg, v2 = elements[i], elements[i + 1], elements[i + 2]
            if not (isinstance(v1, Via) and isinstance(seg, WireSegment) and isinstance(v2, Via)):
                i += 1
                continue
            if _seg_length_mm(seg) > _VIA_CLUSTER_MAX_MM:
                i += 1
                continue
            # Find the surrounding layer: the segments immediately before
            # v1 and after v2 should be on the SAME layer (different from
            # seg.layer). Locate them.
            pre_layer = None
            post_layer = None
            for j in range(i - 1, -1, -1):
                if isinstance(elements[j], WireSegment):
                    pre_layer = elements[j].layer
                    break
            for j in range(i + 3, len(elements)):
                if isinstance(elements[j], WireSegment):
                    post_layer = elements[j].layer
                    break
            if pre_layer is None or post_layer is None or pre_layer != post_layer:
                i += 1
                continue
            if pre_layer == seg.layer:
                i += 1
                continue
            # Bridge candidate: same axis-aligned segment from v1.position
            # to v2.position on `pre_layer`.
            if v1.position.x != v2.position.x and v1.position.y != v2.position.y:
                i += 1
                continue
            bridge_cells = _seg_path_layer_cells(
                g,
                v1.position.x, v1.position.y,
                v2.position.x, v2.position.y,
                pre_layer - 1,  # WireSegment.layer is 1/2; grid layer is 0/1
            )
            if not _cells_safe(bridge_cells, forbidden_check):
                i += 1
                continue
            # Replace `v1, seg, v2` with a single bridging WireSegment on
            # pre_layer. Adjacent segments need their endpoints updated.
            bridge_seg = WireSegment(
                start=Point2D(v1.position.x, v1.position.y),
                end=Point2D(v2.position.x, v2.position.y),
                layer=pre_layer,
            )
            elements[i:i + 3] = [bridge_seg]
            changed = True
            # Don't advance i — the new bridge might combine with
            # neighbours (collapse handles that downstream if we re-emit).
        if changed:
            out.append(SignalPath(name=path.name, elements=tuple(elements)))
        else:
            out.append(path)
    return out


def _seg_is_cardinal(seg) -> bool:
    return seg.start.x == seg.end.x or seg.start.y == seg.end.y


def _seg_is_horizontal(seg) -> bool:
    return seg.start.y == seg.end.y and seg.start.x != seg.end.x


def _find_branch_paths(
    paths: list["SignalPath"],
    raw_by_name: dict,
    source_path_name: str,
    via_xy: tuple[float, float],
) -> list[int]:
    """Indices of paths in the same bus+signal as `source_path_name`
    whose first segment starts at `via_xy`. Those paths branched off
    the source path at this via; if we move the via they need to
    cascade-update or we'd disconnect their root.
    """
    from vitamins.substrate import WireSegment

    src_rp = raw_by_name.get(source_path_name)
    if src_rp is None:
        return []
    src_key = (src_rp.bus_name, src_rp.signal)
    out_idx: list[int] = []
    for j, p in enumerate(paths):
        if p.name == source_path_name:
            continue
        rp = raw_by_name.get(p.name)
        if rp is None:
            continue
        if (rp.bus_name, rp.signal) != src_key:
            continue
        if not p.elements:
            continue
        seg0 = p.elements[0]
        if not isinstance(seg0, WireSegment):
            continue
        if (seg0.start.x, seg0.start.y) == via_xy:
            out_idx.append(j)
    return out_idx


def pull_stub_vias(
    paths: list["SignalPath"],
    g: "Grid",
    forbidden_check_factory: Callable[[object], Callable[[int, int, int], bool]],
    raw_paths,
) -> list["SignalPath"]:
    """Pull a via outward to align with its preceding long cardinal run
    when a small perpendicular stub sits between them.

    Pattern (per path, around each Via element):
      ..., long cardinal segment on layer L (axis A),
           short perpendicular stub on layer L (axis B = ⊥ A, length ≤ threshold),
           Via,
           foreign-layer segment on layer L' (axis B, collinear with the stub),
           ...

    The stub exists because A* parked the via one or two cells inward
    of the wire's natural axis to satisfy the via-approach residual.
    Pulling the via outward to where the long run ends drops the stub
    entirely; the post-via foreign-layer segment grows by the stub
    length to compensate.

    Branch handling: if another path in the same net branches off the
    via being shifted (its first segment starts at the via xy), the
    branch's first segment is also shifted in the same direction so the
    branch root tracks the via. We only attempt this when the branch's
    first segment is cardinal and perpendicular to the via shift axis
    (so the shift means "move the run's cross-axis position by Δ" — a
    clean translation, not a reroute). If the branch geometry doesn't
    permit a clean cascade, the whole via-shift is skipped.

    Validation against the same forbidden predicate the collapse pass
    used: no wall-floor gap can open from this transform.
    """
    from vitamins.substrate import Point2D, SignalPath, Via, WireSegment

    raw_by_name = {rp.name: rp for rp in raw_paths}
    out: list[SignalPath] = list(paths)
    for i_path, path in enumerate(out):
        elements = list(path.elements)
        rp = raw_by_name.get(path.name)
        if rp is None:
            continue
        forbidden_check = forbidden_check_factory(rp)
        changed = False
        i = 0
        while i < len(elements):
            elt = elements[i]
            if not isinstance(elt, Via):
                i += 1
                continue
            if i < 2 or i + 1 >= len(elements):
                i += 1
                continue
            seg_long = elements[i - 2]
            seg_stub = elements[i - 1]
            seg_post = elements[i + 1]
            if not all(isinstance(s, WireSegment) for s in (seg_long, seg_stub, seg_post)):
                i += 1
                continue
            if not (_seg_is_cardinal(seg_long) and _seg_is_cardinal(seg_stub) and _seg_is_cardinal(seg_post)):
                i += 1
                continue
            if seg_long.layer != seg_stub.layer:
                i += 1
                continue
            if _seg_is_horizontal(seg_long) == _seg_is_horizontal(seg_stub):
                i += 1
                continue
            if _seg_length_mm(seg_stub) > _VIA_STUB_MAX_MM:
                i += 1
                continue
            if (seg_long.end.x, seg_long.end.y) != (seg_stub.start.x, seg_stub.start.y):
                i += 1
                continue
            if (seg_stub.end.x, seg_stub.end.y) != (elt.position.x, elt.position.y):
                i += 1
                continue
            if (seg_post.start.x, seg_post.start.y) != (elt.position.x, elt.position.y):
                i += 1
                continue
            if _seg_is_horizontal(seg_post) != _seg_is_horizontal(seg_stub):
                i += 1
                continue
            if seg_post.layer == seg_long.layer:
                i += 1
                continue

            old_via_xy = (elt.position.x, elt.position.y)
            new_via_pos = Point2D(seg_long.end.x, seg_long.end.y)
            new_via_xy = (new_via_pos.x, new_via_pos.y)

            # Identify branched paths that root at this via.
            branch_idxs = _find_branch_paths(out, raw_by_name, path.name, old_via_xy)
            # Compute branch updates upfront so we can bail atomically.
            branch_updates: list[tuple[int, list]] = []
            shift_is_horizontal_axis = seg_stub.start.y != seg_stub.end.y  # stub is vertical → shift in Y
            ok_to_cascade = True
            for j in branch_idxs:
                br = out[j]
                if not br.elements:
                    ok_to_cascade = False
                    break
                br_seg0 = br.elements[0]
                if not isinstance(br_seg0, WireSegment) or not _seg_is_cardinal(br_seg0):
                    ok_to_cascade = False
                    break
                # Shift axis: if stub is vertical (gy changes), the via moved in Y.
                # The branch's seg0 must be horizontal (perpendicular) so we can
                # translate it cleanly in Y. (If branch seg0 is parallel to shift,
                # we'd need to extend/trim — not handled here.)
                br_seg0_horizontal = _seg_is_horizontal(br_seg0)
                if shift_is_horizontal_axis:
                    # Shift is in Y → branch seg0 should be horizontal (along X).
                    if not br_seg0_horizontal:
                        ok_to_cascade = False
                        break
                    new_br_seg0 = WireSegment(
                        start=Point2D(br_seg0.start.x, new_via_pos.y),
                        end=Point2D(br_seg0.end.x, new_via_pos.y),
                        layer=br_seg0.layer,
                    )
                else:
                    if br_seg0_horizontal:
                        ok_to_cascade = False
                        break
                    new_br_seg0 = WireSegment(
                        start=Point2D(new_via_pos.x, br_seg0.start.y),
                        end=Point2D(new_via_pos.x, br_seg0.end.y),
                        layer=br_seg0.layer,
                    )
                # If branch has a second segment, it must be cardinal and
                # perpendicular to seg0 (so we can extend its start endpoint).
                new_br_seg1 = None
                if len(br.elements) > 1:
                    br_seg1 = br.elements[1]
                    if isinstance(br_seg1, WireSegment) and _seg_is_cardinal(br_seg1):
                        # seg1 starts where seg0 ends. After shift, seg0 ends
                        # at the new location; seg1 needs its start moved too.
                        if (br_seg1.start.x, br_seg1.start.y) != (br_seg0.end.x, br_seg0.end.y):
                            ok_to_cascade = False
                            break
                        if _seg_is_horizontal(br_seg1) == _seg_is_horizontal(br_seg0):
                            ok_to_cascade = False
                            break
                        new_br_seg1 = WireSegment(
                            start=Point2D(new_br_seg0.end.x, new_br_seg0.end.y),
                            end=br_seg1.end,
                            layer=br_seg1.layer,
                        )
                    elif isinstance(br_seg1, WireSegment):
                        # Non-cardinal seg1 (chamfer) — bail.
                        ok_to_cascade = False
                        break
                # Validate branch cells. Build a same-net allow-list so
                # cells in the source path's own raw/halo (which the
                # standard forbidden_check would treat as "other" relative
                # to the branch) don't spuriously block the cascade —
                # they're same-net wires, not foreign ones.
                same_net_allow = set(rp.raw_cells) | set(rp.halo_cells) | set(rp.own_pin_cells)
                check_cells = _seg_path_layer_cells(
                    g,
                    new_br_seg0.start.x, new_br_seg0.start.y,
                    new_br_seg0.end.x, new_br_seg0.end.y,
                    new_br_seg0.layer - 1,
                )
                br_rp = raw_by_name.get(br.name)
                if br_rp is None:
                    ok_to_cascade = False
                    break
                br_forbidden = forbidden_check_factory(br_rp)
                blocked = [c for c in check_cells if br_forbidden(*c) and c not in same_net_allow]
                if blocked:
                    ok_to_cascade = False
                    break
                if new_br_seg1 is not None:
                    check_cells1 = _seg_path_layer_cells(
                        g,
                        new_br_seg1.start.x, new_br_seg1.start.y,
                        new_br_seg1.end.x, new_br_seg1.end.y,
                        new_br_seg1.layer - 1,
                    )
                    blocked1 = [c for c in check_cells1 if br_forbidden(*c) and c not in same_net_allow]
                    if blocked1:
                        ok_to_cascade = False
                        break
                # Stage update.
                new_br_elements = list(br.elements)
                new_br_elements[0] = new_br_seg0
                if new_br_seg1 is not None:
                    new_br_elements[1] = new_br_seg1
                branch_updates.append((j, new_br_elements))
            if not ok_to_cascade:
                i += 1
                continue

            # Validate the source path's extended foreign-layer segment.
            bridge_cells = _seg_path_layer_cells(
                g,
                new_via_pos.x, new_via_pos.y,
                seg_post.end.x, seg_post.end.y,
                seg_post.layer - 1,
            )
            if not _cells_safe(bridge_cells, forbidden_check):
                i += 1
                continue

            new_via = Via(position=new_via_pos, diameter=elt.diameter)
            new_seg_post = WireSegment(
                start=new_via_pos,
                end=seg_post.end,
                layer=seg_post.layer,
            )
            elements[i - 1:i + 2] = [new_via, new_seg_post]
            changed = True
            # Apply branch updates.
            for j, new_br_elements in branch_updates:
                br = out[j]
                out[j] = SignalPath(name=br.name, elements=tuple(new_br_elements))
            i = max(0, i - 1)
        if changed:
            out[i_path] = SignalPath(name=path.name, elements=tuple(elements))
    return out
