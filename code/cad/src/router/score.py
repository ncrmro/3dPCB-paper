"""Comparative scoring for routed `SignalPath` sets.

Given two candidate route plans (same nets, different topologies), a
human-readable score lets the user say which one is better without
eyeballing every segment. The weights below are an initial
calibration — they're tunable per use case (the user can override
when calling `score_paths` directly).

The score is composed of:

  - total wire length (a longer wire = more material and more
    chances to fail)
  - L2 length specifically (L2 is the visible top surface; L1 is
    hidden when the board is viewed from above, so an aesthetic
    penalty falls on L2 length)
  - via count (each layer transition is a 1.5 mm hole drilled
    through the substrate — printability cost + manual rework
    cost when soldering)
  - edge clearance (smaller margin to the board edge = closer to
    being physically exposed; a negative value means the channel
    already exits the substrate face)
  - L1 length passing through the OLED pedestal xy footprint
    (visible from the underside and structurally compromising)

`aggregate` is a single scalar — lower is better.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vitamins.substrate import SignalPath, Via, WireSegment


@dataclass(frozen=True)
class RouteScore:
    total_length_mm: float
    l1_length_mm: float
    l2_length_mm: float
    via_count: int
    edge_clearance_min_mm: float
    pedestal_underside_mm: float
    aggregate: float


# Initial weights — see module docstring for rationale.
_W_TOTAL = 0.5
_W_L2 = 1.0
_W_VIA = 5.0
_W_EDGE_PENALTY = 50.0
_W_PEDESTAL = 20.0


def _segment_length(seg: WireSegment) -> float:
    dx = seg.end.x - seg.start.x
    dy = seg.end.y - seg.start.y
    return (dx * dx + dy * dy) ** 0.5


def _segment_edge_clearance(
    seg: WireSegment, half_w: float, half_h: float, inflate: float
) -> float:
    x_min = min(seg.start.x, seg.end.x) - inflate
    x_max = max(seg.start.x, seg.end.x) + inflate
    y_min = min(seg.start.y, seg.end.y) - inflate
    y_max = max(seg.start.y, seg.end.y) + inflate
    return min(
        half_w - x_max,
        x_min - (-half_w),
        half_h - y_max,
        y_min - (-half_h),
    )


def _l1_overlap_inside_box(
    seg: WireSegment,
    box: tuple[float, float, float, float],
) -> float:
    """Length of the L1 portion of `seg` whose xy lies inside `box`
    (x_min, y_min, x_max, y_max). Other layers contribute 0; segments
    not crossing the box contribute 0; segments along an axis fully
    inside the box contribute their full length.
    """
    if seg.layer != 1:
        return 0.0
    x_min, y_min, x_max, y_max = box
    sx, sy, ex, ey = seg.start.x, seg.start.y, seg.end.x, seg.end.y

    # Parametric clip along t ∈ [0, 1].
    dx = ex - sx
    dy = ey - sy
    t_lo, t_hi = 0.0, 1.0

    def _clip(p: float, q: float) -> bool:
        nonlocal t_lo, t_hi
        if abs(p) < 1e-12:
            return q >= 0.0  # parallel: inside iff q >= 0
        t = q / p
        if p < 0.0:
            if t > t_hi:
                return False
            t_lo = max(t_lo, t)
        else:
            if t < t_lo:
                return False
            t_hi = min(t_hi, t)
        return True

    # Liang-Barsky against the rect.
    if not _clip(-dx, sx - x_min):
        return 0.0
    if not _clip(dx, x_max - sx):
        return 0.0
    if not _clip(-dy, sy - y_min):
        return 0.0
    if not _clip(dy, y_max - sy):
        return 0.0

    if t_hi <= t_lo:
        return 0.0
    L = (dx * dx + dy * dy) ** 0.5
    return (t_hi - t_lo) * L


def score_paths(
    paths: Sequence[SignalPath],
    *,
    board_extents: tuple[float, float],
    channel_width: float = 0.8,
    min_wall_thickness: float = 0.6,
    pedestal_box: tuple[float, float, float, float] | None = None,
    weights: dict | None = None,
) -> RouteScore:
    """Score a set of routed signal paths.

    `board_extents` is (board_w, board_h) — the plate dimensions.
    The channel inflation used for edge clearance is
    `channel_width / 2 + min_wall_thickness`, matching
    `test_no_channel_on_board_edge`.

    `pedestal_box` is (x_min, y_min, x_max, y_max) of the OLED
    pedestal xy footprint. L1 length inside this box is penalised
    because it's visible from below and prints into the pedestal
    underside.
    """
    half_w = board_extents[0] / 2.0
    half_h = board_extents[1] / 2.0
    inflate = channel_width / 2.0 + min_wall_thickness

    w = {
        "total": _W_TOTAL,
        "l2": _W_L2,
        "via": _W_VIA,
        "edge_penalty": _W_EDGE_PENALTY,
        "pedestal": _W_PEDESTAL,
    }
    if weights:
        w.update(weights)

    total_len = 0.0
    l1_len = 0.0
    l2_len = 0.0
    via_count = 0
    edge_min: float | None = None
    pedestal_len = 0.0

    # The substrate builders represent vias two ways:
    #   - an explicit `Via` element in the path (what the waypoint
    #     helper emits), OR
    #   - an implicit layer change between two consecutive
    #     `WireSegment`s that share an xy endpoint (legacy builders).
    # Both shapes count toward `via_count`.
    for path in paths:
        prev_seg: WireSegment | None = None
        for elem in path.elements:
            if isinstance(elem, Via):
                via_count += 1
                prev_seg = None
                continue
            if not isinstance(elem, WireSegment):
                continue
            length = _segment_length(elem)
            total_len += length
            if elem.layer == 2:
                l2_len += length
            else:
                l1_len += length
            clearance = _segment_edge_clearance(elem, half_w, half_h, inflate)
            if edge_min is None or clearance < edge_min:
                edge_min = clearance
            if pedestal_box is not None:
                pedestal_len += _l1_overlap_inside_box(elem, pedestal_box)
            if (
                prev_seg is not None
                and prev_seg.layer != elem.layer
                and abs(prev_seg.end.x - elem.start.x) < 1e-6
                and abs(prev_seg.end.y - elem.start.y) < 1e-6
            ):
                via_count += 1
            prev_seg = elem

    if edge_min is None:
        edge_min = float("inf")

    aggregate = (
        w["total"] * total_len
        + w["l2"] * l2_len
        + w["via"] * via_count
        + w["pedestal"] * pedestal_len
    )
    if edge_min < 0.0:
        aggregate += w["edge_penalty"]

    return RouteScore(
        total_length_mm=total_len,
        l1_length_mm=l1_len,
        l2_length_mm=l2_len,
        via_count=via_count,
        edge_clearance_min_mm=edge_min,
        pedestal_underside_mm=pedestal_len,
        aggregate=aggregate,
    )
