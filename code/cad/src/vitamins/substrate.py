"""Routing primitives + CSG cut helpers shared by the router and builder.

This module used to host the hand-coded `Tier1Substrate` / `Tier2Substrate`
classes. They were replaced by the declarative `board/` package; what
remains here is the small set of routing-data dataclasses (`Point2D`,
`WireSegment`, `Via`, `SignalPath`) and the channel/via cut helpers that
both `router/` and `board/build.py` import.

If you're looking for the old substrate-class authoring path, see
`board/devices.py` + `board/build.py` and the YAML specs under
`code/cad/specs/`.
"""

import math
from dataclasses import dataclass
from typing import Tuple, Union

import anchorscad as ad


# ---------------------------------------------------------------------------
# Routing data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Point2D:
    x: float
    y: float


@dataclass(frozen=True)
class WireSegment:
    """Axis-aligned channel cut into one routing layer (1 = bottom, 2 = top)."""

    start: Point2D
    end: Point2D
    layer: int

    @property
    def is_horizontal(self) -> bool:
        return self.start.y == self.end.y


@dataclass(frozen=True)
class Via:
    position: Point2D
    diameter: float = 1.5  # 24-AWG passage with 90° bend clearance


@dataclass(frozen=True)
class SignalPath:
    name: str
    elements: Tuple[Union[WireSegment, Via], ...]


# ---------------------------------------------------------------------------
# Channel + via cut helpers
# ---------------------------------------------------------------------------


def _cut_segment(
    shape,
    seg: "WireSegment",
    dim,
    l1_z: float,
    l2_z: float,
    name: str,
) -> None:
    """Carve a single routed segment into `shape`."""
    cw = dim.channel_width
    cd = dim.channel_depth
    cm = dim.overcut
    z = l1_z if seg.layer == 1 else l2_z
    dx = seg.end.x - seg.start.x
    dy = seg.end.y - seg.start.y
    length = math.hypot(dx, dy)
    cx = (seg.start.x + seg.end.x) / 2
    cy = (seg.start.y + seg.end.y) / 2
    angle_deg = math.degrees(math.atan2(dy, dx))
    box = ad.Box([length + cm, cw, cd + cm])
    shape.add_at(
        box.hole(name).at("centre"),
        post=ad.translate([cx, cy, z]) * ad.rotZ(angle_deg),
    )


def _cut_via(
    shape,
    via: "Via",
    dim,
    name: str,
) -> None:
    """Carve a through-hole via into `shape` at via.position."""
    cyl = ad.Cylinder(r=via.diameter / 2, h=dim.thickness + 0.4)
    shape.add_at(
        cyl.hole(name).at("centre"),
        post=ad.translate([via.position.x, via.position.y, 0]),
    )
