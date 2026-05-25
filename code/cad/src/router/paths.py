"""Waypoint-based authoring for routed signal paths.

A `Waypoint` is a (point, layer) checkpoint along a wire. Consecutive
waypoints are connected with `WireSegment` elements; a layer change
between two waypoints emits a `Via` at the transition point. This
keeps experimental route authoring legible — declare a path as a
small list of corners instead of 30 hand-typed `WireSegment(...)`
calls — without taking on any AnchorSCAD dependency, so the helper
stays unit-testable.

The 45°/axis-aligned invariant from
`test_every_segment_is_45_or_90` is enforced at construction time:
each consecutive waypoint pair must run axis-aligned or at an exact
45° diagonal. Layer values must be 1 (substrate bottom) or 2 (top).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from vitamins.substrate import Point2D, SignalPath, Via, WireSegment


@dataclass(frozen=True)
class Waypoint:
    point: Point2D
    layer: int  # 1 = substrate bottom (hidden), 2 = top (visible)


# Tolerance for the 45°/axis-aligned check. Matches the test in
# `test_every_segment_is_45_or_90` so the helper can't author a path
# that the invariant test would reject.
_ANGLE_TOLERANCE_DEG = 0.05
_ALLOWED_ANGLE_DEGREES = (0.0, 45.0, 90.0, 135.0, 180.0, -45.0, -90.0, -135.0, -180.0)


def _is_axis_or_45(start: Point2D, end: Point2D) -> bool:
    dx = end.x - start.x
    dy = end.y - start.y
    if math.hypot(dx, dy) < 1e-6:
        return True  # zero-length is degenerate but not an angle violation
    angle = math.degrees(math.atan2(dy, dx))
    return any(abs(angle - a) < _ANGLE_TOLERANCE_DEG for a in _ALLOWED_ANGLE_DEGREES)


def waypoints_to_path(
    name: str,
    waypoints: Sequence[Waypoint],
    *,
    via_diameter: float = 1.5,
) -> SignalPath:
    """Build a `SignalPath` from a list of `Waypoint` checkpoints.

    Between consecutive waypoints:
      - if both lie on the same layer, emit a `WireSegment` on that layer
      - if layers differ, emit a `Via` at the second waypoint's point
        (the layer transition happens at the corner, so the via's xy
        is the shared corner xy) and do NOT emit a WireSegment for the
        zero-length "move"

    Two consecutive waypoints on different layers MUST share the same
    xy — a layer transition is a vertical hole drilled at one xy, not
    a diagonal slope between two layers.
    """
    if len(waypoints) < 2:
        raise ValueError(
            f"path {name!r}: need at least 2 waypoints, got {len(waypoints)}"
        )

    elements: list[WireSegment | Via] = []
    for i, w in enumerate(waypoints):
        if w.layer not in (1, 2):
            raise ValueError(
                f"path {name!r}: waypoint {i} layer must be 1 or 2, got {w.layer!r}"
            )

    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        if a.layer == b.layer:
            if not _is_axis_or_45(a.point, b.point):
                dx = b.point.x - a.point.x
                dy = b.point.y - a.point.y
                angle = math.degrees(math.atan2(dy, dx))
                raise ValueError(
                    f"path {name!r}: waypoints {i}→{i + 1} run at {angle:.3f}° "
                    f"— must be axis-aligned or exact-45°"
                )
            elements.append(WireSegment(a.point, b.point, a.layer))
        else:
            # Layer transition: emit a via at the shared xy. Both
            # waypoints must share xy — a layer change at one corner.
            if abs(a.point.x - b.point.x) > 1e-6 or abs(a.point.y - b.point.y) > 1e-6:
                raise ValueError(
                    f"path {name!r}: waypoints {i}→{i + 1} change layer "
                    f"({a.layer}→{b.layer}) but xy differs "
                    f"(({a.point.x}, {a.point.y}) vs ({b.point.x}, {b.point.y})) "
                    f"— layer transitions must share xy"
                )
            elements.append(Via(position=a.point, diameter=via_diameter))

    return SignalPath(name=name, elements=tuple(elements))
