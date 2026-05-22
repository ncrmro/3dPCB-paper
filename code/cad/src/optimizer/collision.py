"""Jumper-line vs through-hole intersection check.

A "jumper" is the straight segment that would replace the displaced
tail when two pins on the same signal merge. If that segment passes
through any *foreign* through-hole (not the merge's two endpoints),
the merge carries a collision risk and the proposal carries the list
of remediations the existing optimize_net_sharing step writes today:
south-of-pocket route, L2 via pair, or reject the merge.
"""

from __future__ import annotations

from typing import Iterable

from .plan_parser import ParsedPlan, ThroughHole


CLEARANCE_MM = 0.4   # half a 0.8 mm trace + a hair


def foreign_pins_on_jumper(
    plan: ParsedPlan,
    jumper_endpoints: tuple[tuple[float, float], tuple[float, float]],
    exclude_pin_refs: Iterable[str] = (),
) -> list[ThroughHole]:
    """Return through-holes whose centre lies within `pin_diameter/2 +
    clearance` of the jumper segment, excluding the merge's own pins."""
    excluded = set(exclude_pin_refs)
    a, b = jumper_endpoints
    hits: list[ThroughHole] = []
    for hole in plan.through_holes:
        if hole.pin_ref in excluded:
            continue
        radius = hole.diameter / 2 + CLEARANCE_MM
        if _point_to_segment_distance(hole.xy, a, b) <= radius:
            hits.append(hole)
    return hits


def _point_to_segment_distance(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


REMEDIATIONS = ("south_of_pocket_route", "l2_via_pair", "reject_merge")
