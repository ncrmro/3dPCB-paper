"""Unit tests for the waypoint helper.

The helper is pure-Python (no AnchorSCAD); these tests exercise
layer-change-emits-via, axis/45° enforcement, and the same-xy
constraint on layer transitions.
"""

from __future__ import annotations

import math

import pytest

from router.paths import Waypoint, waypoints_to_path
from vitamins.substrate import Point2D, Via, WireSegment


def _w(x: float, y: float, layer: int) -> Waypoint:
    return Waypoint(point=Point2D(x, y), layer=layer)


def test_same_layer_waypoints_emit_wire_segments():
    path = waypoints_to_path(
        "demo",
        [_w(0.0, 0.0, 1), _w(5.0, 0.0, 1), _w(5.0, 5.0, 1)],
    )
    assert path.name == "demo"
    assert len(path.elements) == 2
    assert all(isinstance(e, WireSegment) for e in path.elements)
    assert path.elements[0].start == Point2D(0.0, 0.0)
    assert path.elements[0].end == Point2D(5.0, 0.0)
    assert path.elements[0].layer == 1
    assert path.elements[1].layer == 1


def test_layer_change_emits_via_at_shared_xy():
    path = waypoints_to_path(
        "transition",
        [_w(0.0, 0.0, 1), _w(3.0, 0.0, 1), _w(3.0, 0.0, 2), _w(3.0, 4.0, 2)],
    )
    # 1 wire (L1) + 1 via + 1 wire (L2)
    assert len(path.elements) == 3
    assert isinstance(path.elements[0], WireSegment) and path.elements[0].layer == 1
    assert isinstance(path.elements[1], Via)
    assert path.elements[1].position == Point2D(3.0, 0.0)
    assert isinstance(path.elements[2], WireSegment) and path.elements[2].layer == 2


def test_45_degree_diagonal_is_allowed():
    # 45° diagonal — dx == dy
    path = waypoints_to_path("diag", [_w(0.0, 0.0, 1), _w(2.0, 2.0, 1)])
    assert len(path.elements) == 1
    assert isinstance(path.elements[0], WireSegment)


def test_arbitrary_angle_rejected():
    with pytest.raises(ValueError, match="must be axis-aligned or exact-45°"):
        waypoints_to_path("bad", [_w(0.0, 0.0, 1), _w(3.0, 1.0, 1)])


def test_layer_change_with_different_xy_rejected():
    with pytest.raises(ValueError, match="layer transitions must share xy"):
        waypoints_to_path(
            "bad_via",
            [_w(0.0, 0.0, 1), _w(3.0, 0.0, 2)],
        )


def test_invalid_layer_rejected():
    with pytest.raises(ValueError, match="layer must be 1 or 2"):
        waypoints_to_path("bad_layer", [_w(0.0, 0.0, 3), _w(1.0, 0.0, 3)])


def test_too_few_waypoints_rejected():
    with pytest.raises(ValueError, match="at least 2 waypoints"):
        waypoints_to_path("solo", [_w(0.0, 0.0, 1)])


def test_via_diameter_propagates():
    path = waypoints_to_path(
        "v",
        [_w(0.0, 0.0, 1), _w(0.0, 0.0, 2)],
        via_diameter=1.0,
    )
    assert isinstance(path.elements[0], Via)
    assert path.elements[0].diameter == 1.0
