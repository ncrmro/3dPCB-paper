"""Board → AnchorSCAD substrate.

`build_board(board)` returns an `ad.Shape` (a `BoardSubstrate` instance)
that renders to STL/3MF via the standard render pipeline. The Shape is
a flat plate with device pockets carved out, pin holes drilled through,
header pedestals stacked on top, and bus channels routed by the
autorouter cut into the top + bottom faces.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import anchorscad as ad
from anchorscad import datatree

from board.board import Board, DeviceInstance, Level
from board.devices import Device, Rect
from board.mounts import Header
from board.pins import Pin, Point2D


# ---------------------------------------------------------------------------
# Built-in dimension defaults
# ---------------------------------------------------------------------------
#
# These mirror `Tier1SubstrateDimensions` in the legacy code. They're the
# small handful of knobs the build pipeline reads to size channels, vias,
# pockets, and wall floors. Per-Board overrides in YAML come through
# `Board.dim` and override these.

_DEFAULTS: dict[str, float] = {
    "channel_width":      0.8,
    "channel_depth":      0.8,
    "via_diameter":       1.5,
    "hole_diameter":      1.0,
    "pocket_clearance":   0.3,
    "overcut":            0.1,
    "min_wall_thickness": 0.6,
    "edge_clearance":     0.8,
    "hole_pair_clearance": 1.2,
}


@dataclass(frozen=True)
class ResolvedDims:
    channel_width: float
    channel_depth: float
    via_diameter: float
    hole_diameter: float
    pocket_clearance: float
    overcut: float
    min_wall_thickness: float
    edge_clearance: float
    hole_pair_clearance: float
    thickness: float  # base-plate thickness, derived from the base level


def resolve_dims(board: Board) -> ResolvedDims:
    base = board.levels[0]
    merged = dict(_DEFAULTS)
    merged.update(board.dim.applied())
    return ResolvedDims(
        channel_width=merged["channel_width"],
        channel_depth=merged["channel_depth"],
        via_diameter=merged["via_diameter"],
        hole_diameter=merged["hole_diameter"],
        pocket_clearance=merged["pocket_clearance"],
        overcut=merged["overcut"],
        min_wall_thickness=merged["min_wall_thickness"],
        edge_clearance=merged["edge_clearance"],
        hole_pair_clearance=merged["hole_pair_clearance"],
        thickness=base.thickness,
    )


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _device_pin_positions(inst: DeviceInstance) -> list[tuple[Pin, Point2D]]:
    """List every (pin, absolute substrate position) for one DeviceInstance."""
    device = inst.resolved_device()
    return [
        (p, device.pin_position_at(inst.position, inst.rotation, p))
        for p in device.pins
    ]


def _rotated_footprint(inst: DeviceInstance) -> Rect:
    """Return the device's footprint translated + rotated into substrate
    coordinates. Rotation swaps w/h on 90°/270°."""
    fp = inst.resolved_device().footprint
    # The footprint's centre is in device-local coords. Rotate it about
    # the device origin (which sits at the instance.position), then offset.
    if inst.rotation in (0, 180):
        w, h = fp.w, fp.h
    else:
        w, h = fp.h, fp.w
    if inst.rotation == 0:
        cx_local, cy_local = fp.cx, fp.cy
    elif inst.rotation == 90:
        cx_local, cy_local = -fp.cy, fp.cx
    elif inst.rotation == 180:
        cx_local, cy_local = -fp.cx, -fp.cy
    else:  # 270
        cx_local, cy_local = fp.cy, -fp.cx
    return Rect(
        cx=inst.position.x + cx_local,
        cy=inst.position.y + cy_local,
        w=w, h=h,
    )


def synthesize_header_levels(board: Board) -> tuple[Level, ...]:
    """For every DeviceInstance with a Header, synthesise a Level for the
    pedestal that the builder will extrude on top of the base plate."""
    base_top = board.levels[0].z_end
    out: list[Level] = []
    for inst in board.devices:
        if inst.header is None:
            continue
        conn = inst.header.resolved_connector()
        height = inst.header.resolved_height()
        # Pedestal footprint = the connector's body, centred at the
        # device's instance.position (= the pin-row centre in our
        # convention). For rotated devices the body's long axis swaps;
        # the connector body is single-row so the swap is simple.
        if inst.rotation in (0, 180):
            w, h = conn.body_width, conn.body_depth
        else:
            w, h = conn.body_depth, conn.body_width
        out.append(Level(
            name=f"{inst.name}__header",
            perimeter=Rect(
                cx=inst.position.x, cy=inst.position.y, w=w, h=h,
            ),
            z_start=base_top,
            z_end=base_top + height,
        ))
    return tuple(out)


# ---------------------------------------------------------------------------
# Cut helpers — port of substrate.py's _cut_segment / _cut_via, kept here
# so the new build pipeline doesn't depend on the legacy module.
# ---------------------------------------------------------------------------


def _cut_segment(shape, seg, dims: ResolvedDims, l1_z: float, l2_z: float, name: str) -> None:
    cw = dims.channel_width
    cd = dims.channel_depth
    cm = dims.overcut
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


def _cut_via(shape, via, dims: ResolvedDims, name: str) -> None:
    cyl = ad.Cylinder(r=via.diameter / 2, h=dims.thickness + 0.4)
    shape.add_at(
        cyl.hole(name).at("centre"),
        post=ad.translate([via.position.x, via.position.y, 0]),
    )


def _drill_pin_hole(shape, x: float, y: float, dims: ResolvedDims, name: str) -> None:
    """Drill a standard pin through-hole through the full plate."""
    cyl = ad.Cylinder(r=dims.hole_diameter / 2, h=dims.thickness + 0.4)
    shape.add_at(
        cyl.hole(name).at("centre"),
        post=ad.translate([x, y, 0]),
    )


def _cut_pocket(shape, footprint: Rect, depth: float, z_centre: float, name: str) -> None:
    """Cut a rectangular pocket into the shape, centred on (footprint.cx, cy)."""
    box = ad.Box([footprint.w, footprint.h, depth])
    shape.add_at(
        box.hole(name).at("centre"),
        post=ad.translate([footprint.cx, footprint.cy, z_centre]),
    )


# ---------------------------------------------------------------------------
# BoardSubstrate AnchorSCAD shape
# ---------------------------------------------------------------------------
#
# The shape looks itself up in a module-level registry keyed by name. We
# can't pass the Board as a datatree field because @datatree calls build()
# from __post_init__, before any non-field attribute could be attached.
# Lookup-by-name lets BoardSubstrate stay a stock @ad.shape @datatree class.


_BOARD_REGISTRY: dict[str, Board] = {}


@ad.shape
@datatree
class BoardSubstrate(ad.CompositeShape):
    """AnchorSCAD shape built from a `Board`.

    Use `build_board(board)` rather than instantiating directly — the
    factory registers the board so `build()` can find it.
    """

    name: str = "board"

    def build(self) -> ad.Maker:
        try:
            board = _BOARD_REGISTRY[self.name]
        except KeyError as exc:
            raise RuntimeError(
                f"BoardSubstrate({self.name!r}).build() called but no Board "
                f"is registered under that name; use build_board(board) "
                f"instead of instantiating directly"
            ) from exc
        dims = resolve_dims(board)

        base_level = board.levels[0]
        l1_z = base_level.z_start + dims.channel_depth / 2
        l2_z = base_level.z_end - dims.channel_depth / 2

        # ---- base plate ----------------------------------------------
        plate = ad.Box([
            base_level.perimeter.w,
            base_level.perimeter.h,
            base_level.thickness,
        ])
        maker = plate.solid("base").at(
            "centre",
            post=ad.translate([
                base_level.perimeter.cx,
                base_level.perimeter.cy,
                (base_level.z_start + base_level.z_end) / 2,
            ]),
        )

        # ---- user-declared extra levels ------------------------------
        for lvl in board.levels[1:]:
            box = ad.Box([lvl.perimeter.w, lvl.perimeter.h, lvl.thickness])
            maker.add_at(
                box.solid(f"level_{lvl.name}").at("centre"),
                post=ad.translate([
                    lvl.perimeter.cx,
                    lvl.perimeter.cy,
                    (lvl.z_start + lvl.z_end) / 2,
                ]),
            )

        # ---- header pedestals ----------------------------------------
        for lvl in synthesize_header_levels(board):
            box = ad.Box([lvl.perimeter.w, lvl.perimeter.h, lvl.thickness])
            maker.add_at(
                box.solid(f"pedestal_{lvl.name}").at("centre"),
                post=ad.translate([
                    lvl.perimeter.cx,
                    lvl.perimeter.cy,
                    (lvl.z_start + lvl.z_end) / 2,
                ]),
            )

        # ---- device pockets + pin holes ------------------------------
        for inst in board.devices:
            footprint = _rotated_footprint(inst)
            # Pocket only for flat-mounted devices (header-mounted devices
            # sit on the pedestal, not in a pocket cut into the substrate).
            if inst.header is None:
                pocket = Rect(
                    cx=footprint.cx, cy=footprint.cy,
                    w=footprint.w + 2 * dims.pocket_clearance,
                    h=footprint.h + 2 * dims.pocket_clearance,
                )
                # Pocket depth: pcb_thickness + clearance, cut from the top face.
                pcb_t = inst.resolved_device().pcb_thickness
                pocket_depth = pcb_t + dims.overcut
                pocket_z_centre = base_level.z_end - pocket_depth / 2
                _cut_pocket(
                    maker, pocket, pocket_depth, pocket_z_centre,
                    name=f"pocket_{inst.name}",
                )
            # Drill the pin holes through the full base plate so wires
            # can be soldered through. Headered devices drill through
            # both the base plate AND the pedestal — but the pedestal
            # is already a separate solid, so a single tall through-hole
            # carved here doesn't reach the pedestal. Drill a second
            # cylinder through each header to clear that path.
            for i, (pin, abs_pos) in enumerate(_device_pin_positions(inst)):
                # i is unique across the device's full pin tuple — pin.index
                # repeats across columns (J1A.1 / J1B.1 both have index 1).
                _drill_pin_hole(
                    maker, abs_pos.x, abs_pos.y, dims,
                    name=f"pin_{inst.name}_{i}",
                )
            if inst.header is not None:
                conn = inst.header.resolved_connector()
                pedestal_h = inst.header.resolved_height()
                # Pedestal-only through-holes for each connector pin.
                for i in range(conn.pin_count):
                    # Pins along the device's pin row (axis matches the
                    # device's pin layout — for our starter devices, +X).
                    offset = (i - (conn.pin_count - 1) / 2) * conn.pitch
                    if inst.rotation in (0, 180):
                        px = inst.position.x + (offset if inst.rotation == 0 else -offset)
                        py = inst.position.y
                    else:
                        px = inst.position.x
                        py = inst.position.y + (offset if inst.rotation == 90 else -offset)
                    cyl = ad.Cylinder(
                        r=conn.drill_diameter / 2,
                        h=pedestal_h + dims.overcut,
                    )
                    maker.add_at(
                        cyl.hole(f"header_{inst.name}_{i + 1}").at("centre"),
                        post=ad.translate([
                            px, py,
                            base_level.z_end + pedestal_h / 2,
                        ]),
                    )

        # ---- bus channels + vias (autorouted) ------------------------
        # The autorouter consumes the resolved nets and returns SignalPaths
        # with WireSegment + Via elements. Channels carved into l1_z / l2_z;
        # vias drilled through the full plate. Wired up in Phase 2.
        signal_paths = _route_or_empty(board, dims)
        for path in signal_paths:
            for i, elt in enumerate(path.elements):
                # Local import keeps the module load order tolerant of
                # the autorouter being filled in mid-phase.
                from vitamins.substrate import Via, WireSegment
                if isinstance(elt, WireSegment):
                    _cut_segment(
                        maker, elt, dims, l1_z, l2_z,
                        name=f"{path.name}_seg{i}",
                    )
                elif isinstance(elt, Via):
                    _cut_via(maker, elt, dims, name=f"{path.name}_via{i}")

        return maker


def _route_or_empty(board: Board, dims: ResolvedDims):
    """Call the autorouter if it exists; return [] if there are no nets
    declared. Phase 1 ships without an autorouter; Phase 2 plugs one in
    by exporting `route_board(board, dims)` from `router.autoroute`."""
    nets = board.nets()
    if not nets:
        return []
    try:
        from router.autoroute import route_board  # noqa: WPS433
    except ImportError:
        # Autorouter not implemented yet — build a substrate without
        # carved channels. The Board still extrudes + drills pin holes
        # correctly so the layout can be visually inspected.
        return []
    return route_board(board, dims)


def build_board(board: Board) -> ad.Shape:
    """Build a Board into an AnchorSCAD shape ready for rendering.

    Registers the Board so the shape's build() can find it. If a Board
    with the same name was registered before with different data, this
    overwrites — intentional for the dev loop where re-loading a YAML
    spec produces a freshly-validated Board object."""
    _BOARD_REGISTRY[board.name] = board
    return BoardSubstrate(name=board.name)
