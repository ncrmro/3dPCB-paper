"""Pure geometric collision helpers for the substrate's routing model.

Axis-aligned bbox math over the `WireSegment` / `Via` / `Point2D` data
that `vitamins.substrate._build_paths_for_net` already produces. Used
by the netlist test gate (`tests/test_netlist.py`) and by the greedy
hint optimiser (`router.optimiser`).

All public helpers operate on data only — they import the geometry
constants and `_pin_position` from `vitamins.substrate` but do NOT
touch anchorscad, so they can run in the lightweight Python env the
KiCad sibling uses as well.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

from netlist import I2cSignal, Net, Pin
from vitamins.esp32_pinout import J1A_PINOUT, J1B_PINOUT
from vitamins.oled_ssd1306_pinout import OLED_PINOUT
from vitamins.sensors_pinout import BH1750_PINOUT, SCD41_PINOUT
from vitamins.substrate import (
    Point2D,
    Tier1SubstrateDimensions,
    Via,
    WireSegment,
    _J1A_X,
    _J1A_Y,
    _J1B_X,
    _J2_X,
    _J2_Y,
    _J3_X,
    _J3_Y,
    _J4_X,
    _J4_Y,
    _PITCH,
    _pin_position,
)


# ---------------------------------------------------------------------------
# Bbox primitives
# ---------------------------------------------------------------------------


BBox = tuple[float, float, float, float]  # (xmin, xmax, ymin, ymax)


def segment_bbox(seg: WireSegment, channel_width: float) -> BBox:
    """Axis-aligned bbox of a `channel_width`-wide channel around the
    centreline of an axis-aligned segment.

    Returns `(xmin, xmax, ymin, ymax)`.
    """
    half = channel_width / 2
    return (
        min(seg.start.x, seg.end.x) - half,
        max(seg.start.x, seg.end.x) + half,
        min(seg.start.y, seg.end.y) - half,
        max(seg.start.y, seg.end.y) + half,
    )


def bboxes_overlap(a: BBox, b: BBox, eps: float = 1e-6) -> bool:
    """True iff axis-aligned bboxes share area beyond `eps` slack.

    The slack avoids flagging two bboxes that merely touch at a shared
    edge (e.g. T-junctions where two same-net segments meet) as
    overlapping.
    """
    ax0, ax1, ay0, ay1 = a
    bx0, bx1, by0, by1 = b
    return (
        ax1 - eps > bx0
        and bx1 - eps > ax0
        and ay1 - eps > by0
        and by1 - eps > ay0
    )


def point_bbox(x: float, y: float, radius: float) -> BBox:
    """Bbox of a disk of `radius` around (x, y)."""
    return (x - radius, x + radius, y - radius, y + radius)


# ---------------------------------------------------------------------------
# Substrate geometry — pockets + pin positions
# ---------------------------------------------------------------------------


def module_pocket_bboxes(dim: Tier1SubstrateDimensions) -> dict[str, BBox]:
    """Pocket footprints in board-local (x, y), matching the geometry
    built inside `Tier1Substrate.build()`."""
    esp_cx = (_J1A_X + _J1B_X) / 2
    esp_cy = _J1A_Y + 4 * _PITCH
    esp_w = dim.esp32.width + dim.pocket_clearance
    esp_h = dim.esp32.length + dim.pocket_clearance

    scd_cx = _J2_X + 1.5 * _PITCH
    scd_cy = _J2_Y + dim.scd41.depth / 2 - dim.scd41.header_body_width / 2
    scd_w = dim.scd41.width + dim.pocket_clearance
    scd_h = dim.scd41.depth + dim.pocket_clearance

    bh_cx = _J3_X + 2.0 * _PITCH
    bh_cy = _J3_Y + dim.bh1750.depth / 2 - dim.bh1750.header_body_width / 2
    bh_w = dim.bh1750.width + dim.pocket_clearance
    bh_h = dim.bh1750.depth + dim.pocket_clearance

    return {
        "ESP32": (esp_cx - esp_w / 2, esp_cx + esp_w / 2,
                  esp_cy - esp_h / 2, esp_cy + esp_h / 2),
        "SCD41": (scd_cx - scd_w / 2, scd_cx + scd_w / 2,
                  scd_cy - scd_h / 2, scd_cy + scd_h / 2),
        "BH1750": (bh_cx - bh_w / 2, bh_cx + bh_w / 2,
                   bh_cy - bh_h / 2, bh_cy + bh_h / 2),
    }


def all_through_holes(
    include_oled: bool = True,
    extra: Optional[Iterable[tuple[Pin, Point2D]]] = None,
) -> list[tuple[Pin, Point2D]]:
    """Every (Pin, position) the spike outline punches through the
    substrate.

    `include_oled` controls whether the J4 (OLED) receptacle pins are
    included — they're only physically present on the Tier 2
    substrate, but treating them as foreign pins on Tier 1 too is
    harmless because the optimiser checks against pins that are NOT on
    the current net.

    `extra` lets a caller inject hand-placed foreign holes (used by
    the optimiser's constraint test to artificially block a corridor).
    """
    out: list[tuple[Pin, Point2D]] = []
    for pinout in (J1A_PINOUT, J1B_PINOUT, SCD41_PINOUT, BH1750_PINOUT):
        for pin in pinout.values():
            out.append((pin, _pin_position(pin)))
    if include_oled:
        for pin in OLED_PINOUT.values():
            out.append((pin, _pin_position(pin)))
    if extra:
        out.extend(extra)
    return out


def net_pin_keys(net: Net) -> set[tuple[float, float]]:
    """Hash-stable keys for all pins that ARE this net's endpoints."""
    pts = [_pin_position(net.master_pin)] + [
        _pin_position(p) for p in net.device_pins
    ]
    return {pin_key(p) for p in pts}


def pin_key(p: Point2D) -> tuple[float, float]:
    """Hash-stable node key (rounds away float jitter)."""
    return (round(p.x, 4), round(p.y, 4))


# ---------------------------------------------------------------------------
# Element-level collision predicates
# ---------------------------------------------------------------------------


def segments_collide(
    a: WireSegment, b: WireSegment, channel_width: float
) -> bool:
    """True iff two channels overlap on the same layer."""
    if a.layer != b.layer:
        return False
    return bboxes_overlap(
        segment_bbox(a, channel_width),
        segment_bbox(b, channel_width),
    )


def segment_pierces_hole(
    seg: WireSegment,
    hole_pos: Point2D,
    channel_width: float,
    hole_radius: float,
) -> bool:
    """True iff the channel bbox overlaps the hole's bbox.

    The hole pierces every layer (it's a through-hole), so this check
    is layer-agnostic. We approximate the disk as its bbox because the
    channel is also rectangular — the bbox-vs-bbox check is the same
    as a Minkowski-sum disk-vs-rectangle inflated by the channel half-
    width, which is what the existing test gate uses.
    """
    return bboxes_overlap(
        segment_bbox(seg, channel_width),
        point_bbox(hole_pos.x, hole_pos.y, hole_radius),
    )


def via_in_pocket(via: Via, pocket: BBox, via_radius: float) -> bool:
    """True iff a via's bbox overlaps a module pocket."""
    return bboxes_overlap(
        point_bbox(via.position.x, via.position.y, via_radius),
        pocket,
    )


def via_overlaps_hole(
    via: Via, hole_pos: Point2D, via_radius: float, hole_radius: float
) -> bool:
    """True iff a via and a through-hole's disks overlap (disk-disk)."""
    dx = via.position.x - hole_pos.x
    dy = via.position.y - hole_pos.y
    return math.hypot(dx, dy) < via_radius + hole_radius


# ---------------------------------------------------------------------------
# Full-path collision check against a fixed environment
# ---------------------------------------------------------------------------


def path_collides(
    candidate_elements: Iterable,
    candidate_net: Net,
    fixed_elements: Iterable[tuple[I2cSignal, object]],
    holes: Iterable[tuple[Pin, Point2D]],
    pockets: dict[str, BBox],
    *,
    channel_width: float,
    hole_radius: float,
    via_radius: float,
) -> Optional[str]:
    """Check a candidate path against a fixed environment.

    Returns `None` if the candidate is collision-free, otherwise a
    short human-readable string explaining the first failure found.

    Tests against:
      a. same-layer wire overlap with any already-fixed segment
      b. trunk piercing any foreign through-hole (every hole that's
         not one of this net's endpoints)
      c. via inside a module pocket
      d. via overlapping a foreign through-hole
    """
    endpoints = net_pin_keys(candidate_net)
    fixed_list = list(fixed_elements)
    candidate_list = list(candidate_elements)

    # (a) same-layer wire overlap against fixed segments
    for el in candidate_list:
        if not isinstance(el, WireSegment):
            continue
        for _sig, other in fixed_list:
            if not isinstance(other, WireSegment):
                continue
            if segments_collide(el, other, channel_width):
                return (
                    f"L{el.layer} segment {el.start}-{el.end} overlaps "
                    f"fixed segment {other.start}-{other.end}"
                )

    # (b) trunk through any foreign through-hole
    for el in candidate_list:
        if not isinstance(el, WireSegment):
            continue
        for pin, pos in holes:
            if pin_key(pos) in endpoints:
                continue
            if segment_pierces_hole(el, pos, channel_width, hole_radius):
                return (
                    f"L{el.layer} segment {el.start}-{el.end} pierces "
                    f"foreign pin {pin.ref}.{pin.number} at {pos}"
                )

    # (c) via in module pocket
    for el in candidate_list:
        if not isinstance(el, Via):
            continue
        for module_name, pocket in pockets.items():
            if via_in_pocket(el, pocket, via_radius):
                return (
                    f"via at {el.position} lies inside pocket {module_name}"
                )

    # (d) via on foreign through-hole
    for el in candidate_list:
        if not isinstance(el, Via):
            continue
        for pin, pos in holes:
            if pin_key(pos) in endpoints:
                continue
            if via_overlaps_hole(el, pos, via_radius, hole_radius):
                return (
                    f"via at {el.position} overlaps foreign pin "
                    f"{pin.ref}.{pin.number} at {pos}"
                )

    return None
