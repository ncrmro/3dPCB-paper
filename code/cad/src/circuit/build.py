"""CircuitSpec → AnchorSCAD shape + SignalPath emitter.

`build_substrate(spec)` produces the geometry; `route_to_signal_path`
turns a `Route` into the same `SignalPath` tuple that the routing
invariant suite consumes — both used by `Tier2SubstrateFromSpec` so
the spec-driven substrate and the hand-coded one compare apples to
apples.
"""

from __future__ import annotations

from typing import Iterable, List

import anchorscad as ad

from circuit.models import CircuitSpec, Rect, Route, Waypoint as SpecWaypoint
from router.paths import Waypoint as RouterWaypoint, waypoints_to_path
from vitamins.substrate import (
    Point2D,
    SignalPath,
    Tier1SubstrateDimensions,
    Via,
    WireSegment,
    _cut_segment,
    _cut_via,
)


# ---------------------------------------------------------------------------
# Route → SignalPath
# ---------------------------------------------------------------------------


def _to_router_wp(wp: SpecWaypoint) -> RouterWaypoint:
    return RouterWaypoint(point=Point2D(wp.x, wp.y), layer=wp.layer)


def route_to_signal_path(route: Route) -> SignalPath:
    """Stitch a Route's legs (and any explicit vias) into a SignalPath.

    Each leg is run through `waypoints_to_path` and the results are
    concatenated. Vias from `route.vias` are inserted at their
    `after_leg` index — so a `ViaSpec(after_leg=2)` is emitted into
    the element stream right after leg 2's segments. The signal's
    lowercase enum name becomes the SignalPath name.
    """
    name = route.signal.name.lower()
    elements: List = []
    # Group vias by after_leg index for cheap lookup during the leg loop.
    via_by_after_leg: dict[int, list[Via]] = {}
    for v in route.vias:
        via_by_after_leg.setdefault(v.after_leg, []).append(
            Via(position=Point2D(v.x, v.y), diameter=v.diameter)
        )

    for leg_idx, leg in enumerate(route.legs):
        leg_path = waypoints_to_path(
            f"{name}_leg{leg_idx}",
            [_to_router_wp(wp) for wp in leg],
        )
        elements.extend(leg_path.elements)
        # Drop any vias scheduled to land after this leg.
        for v in via_by_after_leg.get(leg_idx, ()):
            elements.append(v)

    return SignalPath(name=name, elements=tuple(elements))


def spec_signal_paths(spec: CircuitSpec) -> list[SignalPath]:
    return [route_to_signal_path(r) for r in spec.routes]


# ---------------------------------------------------------------------------
# CircuitSpec → AnchorSCAD shape
# ---------------------------------------------------------------------------


def _level_to_box(level, cuts: Iterable[Rect], adds: Iterable[Rect]):
    """v1 supports axis-aligned rectangles only."""
    if not isinstance(level.perimeter, Rect):
        raise NotImplementedError(
            "v1 supports axis-aligned Rect perimeters only "
            f"(level {level.name!r} carries {type(level.perimeter).__name__})"
        )
    return level.perimeter


def materialize_dim(spec: CircuitSpec) -> Tier1SubstrateDimensions:
    """Instantiate Tier1SubstrateDimensions with the spec's overrides
    layered on top of the dataclass defaults."""
    return Tier1SubstrateDimensions(**spec.dim.to_kwargs())


def build_substrate(spec: CircuitSpec, dim: Tier1SubstrateDimensions | None = None) -> ad.Maker:
    """Build an AnchorSCAD shape from a validated CircuitSpec.

    For v1 — axis-aligned rectangular perimeters only — each level
    becomes a single `ad.Box` solid; device pockets and route channels
    are then carved out as `hole()`s. The output is the same shape
    family the hand-built Tier1Substrate.build() produces, so its
    routing voxel test applies unchanged.
    """
    d = dim if dim is not None else materialize_dim(spec)

    # Pre-compute the L1 / L2 channel z-centres exactly as
    # Tier1Substrate.build() does, so `_cut_segment` carves identical
    # channels for the same WireSegment.
    l1_z = -d.thickness / 2 + d.channel_depth / 2 - d.overcut / 2
    l2_z = d.thickness / 2 - d.channel_depth / 2 + d.overcut / 2

    if not spec.levels:
        raise ValueError("CircuitSpec must declare at least one level")

    # Base plate uses the first level's perimeter. v1 makes one combined
    # box per level by summing its z-extent; later levels stack on top
    # via add_at. The voxel test only cares about the L1/L2 routing
    # band, which the first level (the base plate) supplies.
    base_level = spec.levels[0]
    if not isinstance(base_level.perimeter, Rect):
        raise NotImplementedError(
            "v1 supports axis-aligned Rect perimeters only "
            f"(base level {base_level.name!r} carries "
            f"{type(base_level.perimeter).__name__})"
        )
    base = base_level.perimeter
    base_z = (base_level.z_start + base_level.z_end) / 2
    base_h = base_level.z_end - base_level.z_start
    plate = ad.Box([base.w, base.h, base_h])
    shape = plate.solid("plate").colour([0.92, 0.88, 0.78]).at("centre")
    if abs(base_z) > 1e-9 or abs(base.cx) > 1e-9 or abs(base.cy) > 1e-9:
        # The default centred plate already lands at (0,0,0); only
        # translate if the spec moves it.
        shape = shape.at("centre").solid("plate_at_origin").at("centre")  # type: ignore[attr-defined]

    # Stacked levels (index ≥ 1): emit each as a solid box sitting at
    # its (cx, cy, mean_z). v1 just adds them; pocket subtraction is
    # handled by the device loop below.
    for idx, level in enumerate(spec.levels):
        if idx == 0:
            continue
        if not isinstance(level.perimeter, Rect):
            raise NotImplementedError(
                "v1 supports axis-aligned Rect perimeters only "
                f"(level {level.name!r} carries "
                f"{type(level.perimeter).__name__})"
            )
        per = level.perimeter
        z_mid = (level.z_start + level.z_end) / 2
        z_h = level.z_end - level.z_start
        block = ad.Box([per.w, per.h, z_h])
        shape.add_at(
            block.solid(level.name).colour([0.92, 0.88, 0.78]).at("centre"),
            post=ad.translate([per.cx, per.cy, z_mid]),
        )

    # Device pockets: each device with a pocket Rect cuts that rect
    # through every level it occupies. v1 maps the pocket to a hole
    # box spanning the device's level z-range (with the standard
    # pocket_clearance + overcut margins).
    for device in spec.devices:
        if device.pocket is None:
            continue
        pocket = device.pocket
        if not isinstance(pocket, Rect):
            raise NotImplementedError(
                "v1 supports axis-aligned Rect pockets only "
                f"(device {device.name!r} carries "
                f"{type(pocket).__name__})"
            )
        for idx in device.levels:
            level = spec.levels[idx]
            pcb_t = level.z_end - level.z_start
            box = ad.Box([
                pocket.w + d.pocket_clearance,
                pocket.h + d.pocket_clearance,
                pcb_t + d.overcut,
            ])
            box_z = (level.z_start + level.z_end) / 2 + d.overcut / 2
            shape.add_at(
                box.hole(f"{device.name}_pocket_l{idx}").at("centre"),
                post=ad.translate([pocket.cx, pocket.cy, box_z]),
            )

    # Pin through-holes: every Pin in any device.pin_holes drills
    # through the full plate.
    from vitamins.substrate import _pin_position
    hole_cyl = ad.Cylinder(r=d.hole_diameter / 2, h=d.thickness + 0.4)
    for device in spec.devices:
        for pin in device.pin_holes:
            pos = _pin_position(pin)
            shape.add_at(
                hole_cyl.hole(
                    f"{device.name}_{pin.ref.lower()}_{pin.number}"
                ).at("centre"),
                post=ad.translate([pos.x, pos.y, 0]),
            )

    # Channels + vias from each Route.
    seg_idx = 0
    via_idx = 0
    for path in spec_signal_paths(spec):
        for elem in path.elements:
            if isinstance(elem, WireSegment):
                _cut_segment(shape, elem, d, l1_z, l2_z,
                             f"{path.name}_seg_{seg_idx}")
                seg_idx += 1
            elif isinstance(elem, Via):
                _cut_via(shape, elem, d, f"{path.name}_via_{via_idx}")
                via_idx += 1

    return shape
