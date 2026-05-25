"""Unit tests for `score_paths`.

Synthetic 2-segment paths with known geometry exercise each
component of `RouteScore` so a regression in any one weight shows
up immediately.
"""

from __future__ import annotations

from router.score import score_paths
from vitamins.substrate import Point2D, SignalPath, Via, WireSegment


def _seg(x1: float, y1: float, x2: float, y2: float, layer: int) -> WireSegment:
    return WireSegment(start=Point2D(x1, y1), end=Point2D(x2, y2), layer=layer)


def test_total_and_per_layer_length_split():
    path = SignalPath(
        name="demo",
        elements=(
            _seg(0.0, 0.0, 10.0, 0.0, 1),  # 10 mm on L1
            _seg(0.0, 0.0, 0.0, 5.0, 2),   # 5 mm on L2
        ),
    )
    s = score_paths([path], board_extents=(80.0, 50.0))
    assert s.total_length_mm == 15.0
    assert s.l1_length_mm == 10.0
    assert s.l2_length_mm == 5.0


def test_via_count_explicit():
    path = SignalPath(
        name="vias",
        elements=(
            _seg(0.0, 0.0, 1.0, 0.0, 1),
            Via(position=Point2D(1.0, 0.0)),
            _seg(1.0, 0.0, 1.0, 2.0, 2),
            Via(position=Point2D(1.0, 2.0)),
        ),
    )
    s = score_paths([path], board_extents=(80.0, 50.0))
    assert s.via_count == 2


def test_via_count_implicit_layer_change():
    # Legacy builders emit a layer change as two WireSegments sharing
    # an xy endpoint with different `.layer` — the via is implicit. The
    # score must count these the same as explicit Via elements.
    path = SignalPath(
        name="implicit",
        elements=(
            _seg(0.0, 0.0, 1.0, 0.0, 1),
            _seg(1.0, 0.0, 1.0, 2.0, 2),   # L1→L2 transition at (1,0)
            _seg(1.0, 2.0, 3.0, 2.0, 2),   # same-layer continuation
            _seg(3.0, 2.0, 3.0, 4.0, 1),   # L2→L1 transition at (3,2)
        ),
    )
    s = score_paths([path], board_extents=(80.0, 50.0))
    assert s.via_count == 2


def test_edge_clearance_negative_when_channel_exposed():
    # Centreline at x=34 inflated by 0.8/2 + 0.6 = 1.0 → channel east
    # boundary at x=+35, but board half-width is 34 → clearance = -1.0.
    path = SignalPath(
        name="exposed",
        elements=(_seg(0.0, 0.0, 34.0, 0.0, 2),),
    )
    s = score_paths(
        [path],
        board_extents=(68.0, 50.0),
        channel_width=0.8,
        min_wall_thickness=0.6,
    )
    assert s.edge_clearance_min_mm < 0.0
    # Hard penalty triggered.
    assert s.aggregate >= 50.0


def test_edge_clearance_positive_when_channel_inside():
    path = SignalPath(
        name="safe",
        elements=(_seg(0.0, 0.0, 30.0, 0.0, 2),),
    )
    s = score_paths(
        [path],
        board_extents=(68.0, 50.0),
        channel_width=0.8,
        min_wall_thickness=0.6,
    )
    # Channel east at 31.0, board half-width 34 → clearance 3.0.
    assert s.edge_clearance_min_mm == 3.0


def test_pedestal_underside_l1_only():
    pedestal = (-6.0, 6.0, 6.0, 14.0)  # 12×8 mm centred on (0, 10)
    # L1 segment crossing the pedestal box from x=-10 to x=+10 at y=10
    # → 12 mm overlap inside the box.
    l1_under = SignalPath(
        name="under",
        elements=(_seg(-10.0, 10.0, 10.0, 10.0, 1),),
    )
    # Same segment on L2 should NOT count.
    l2_over = SignalPath(
        name="over",
        elements=(_seg(-10.0, 10.0, 10.0, 10.0, 2),),
    )
    s_under = score_paths(
        [l1_under], board_extents=(80.0, 50.0), pedestal_box=pedestal
    )
    s_over = score_paths(
        [l2_over], board_extents=(80.0, 50.0), pedestal_box=pedestal
    )
    assert abs(s_under.pedestal_underside_mm - 12.0) < 1e-6
    assert s_over.pedestal_underside_mm == 0.0


def test_aggregate_combines_components():
    path = SignalPath(
        name="combo",
        elements=(
            _seg(0.0, 0.0, 10.0, 0.0, 1),
            _seg(0.0, 0.0, 0.0, 4.0, 2),
            Via(position=Point2D(0.0, 4.0)),
        ),
    )
    s = score_paths([path], board_extents=(80.0, 50.0))
    # 0.5 * 14 + 1.0 * 4 + 5.0 * 1 = 7 + 4 + 5 = 16
    assert s.aggregate == 16.0


def test_lower_aggregate_is_better():
    # Two paths with the same total length but different L2 content —
    # the one with less L2 should score lower.
    p_l2 = SignalPath(
        name="l2_heavy",
        elements=(_seg(0.0, 0.0, 10.0, 0.0, 2),),
    )
    p_l1 = SignalPath(
        name="l1_heavy",
        elements=(_seg(0.0, 0.0, 10.0, 0.0, 1),),
    )
    s2 = score_paths([p_l2], board_extents=(80.0, 50.0))
    s1 = score_paths([p_l1], board_extents=(80.0, 50.0))
    assert s1.aggregate < s2.aggregate
