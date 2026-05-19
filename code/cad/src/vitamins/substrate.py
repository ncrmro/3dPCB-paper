"""Tier 1 substrate — flat 3D-printed sibling of the KiCad spike PCB.

Single 80 × 50 × 3 mm plate carrying ESP32-C3 SuperMini + SCD41 +
BH1750 in inlay pockets, with through-holes at every module pin and
two-sided routing channels carrying the I2C bus.

Routing topology (v2, verified PASS by the printable_pcb routing
gate — see printable_pcb/spike_v2/routing_check.md):

    ESP32 pin ─[L1 east stub]─ (north_x, esp.y)
                                    │
                              [L1 north]
                                    │
                              (north_x, corridor_y) ── via ── L2 ─┐
                                                                  │
                              (scd.x, corridor_y) ── via ─────────┤
                                  │                               │
                              [L1 south] ── SCD pad               │
                                                                  │
                              ┌─────────── L2 ─────────────[via]──┤
                              │                                   │
                              (bh.x, corridor_y) ── via ──────────┘
                                  │
                              [L1 south] ── BH pad

Each net has a unique north corridor x (J1A nets escape inside the
ESP32 pocket east of J1A, J1B nets via a short east stub past J1B)
and a unique corridor y above every module pocket (y ≥ +6). All
vias land at corridor y, north of every pocket footprint.
L2 east legs are used wherever the L1 alternative would cross
another net's L1 vertical; SDA (corridor y +15) is high enough that
its east leg can stay on L1.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Union

import anchorscad as ad
from anchorscad import datatree

from netlist import I2cSignal, Net, Pin
from vitamins.esp32 import Esp32C3SuperminiDimensions
from vitamins.sensors import Bh1750Dimensions, Scd41Dimensions


# ---------------------------------------------------------------------------
# Routing data model — minimal port from plant-caravan/wire_routing.py
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
# Substrate geometry constants
# ---------------------------------------------------------------------------

_BOARD_W = 80.0
_BOARD_H = 50.0
_THICKNESS = 3.0
_PITCH = 2.54
_HOLE_D = 1.0  # matches KiCad pad drill in gen_spike_pcb.py:272

_J1A_X, _J1A_Y = -30.0, -17.0  # ESP32 left col, pin 1
_J1B_X = _J1A_X + 17.78
_J1B_Y = _J1A_Y
_J2_X, _J2_Y = 5.0, -17.0  # SCD41 pad 1 (rotated so pads run +X)
_J3_X, _J3_Y = 20.0, -17.0  # BH1750 pad 1
# OLED (Hosyond SSD1306) header. 4 pins running +X, header at south
# edge of the substrate so the OLED PCB cantilevers south off the
# board — this puts the OLED entirely outside the BH1750's xy
# footprint (BH1750 at x∈[17.9,32.2], y∈[-24.4,-5.6]; OLED PCB at
# x∈[-13.5,+13.5], y∈[-22,-49]) so the upward light cone stays clear.
_J4_X, _J4_Y = -3.81, -22.0


def _esp32_pin(col_x: float, base_y: float, pin: int) -> Point2D:
    """1-indexed ESP32 pad position (pads run +Y from pin 1)."""
    return Point2D(col_x, base_y + (pin - 1) * _PITCH)


def _sensor_pin(base_x: float, base_y: float, pin: int) -> Point2D:
    """1-indexed sensor pad position (pads run +X after KiCad 270° rotation)."""
    return Point2D(base_x + (pin - 1) * _PITCH, base_y)


# Resolve a netlist Pin into a (x, y) on the spike outline. The column
# anchors and axes below match `code/kicad/gen_spike_pcb.py` placements;
# any board with the same module classes but different placements will
# carry its own `_pin_position` helper.
_COLUMN_ANCHORS: dict[str, Tuple[float, float, str]] = {
    "J1A": (_J1A_X, _J1A_Y, "+y"),
    "J1B": (_J1B_X, _J1B_Y, "+y"),
    "J2":  (_J2_X,  _J2_Y,  "+x"),
    "J3":  (_J3_X,  _J3_Y,  "+x"),
    "J4":  (_J4_X,  _J4_Y,  "+x"),
}


def _pin_position(pin: Pin) -> Point2D:
    """Map a netlist Pin to its (x, y) on this board."""
    try:
        x0, y0, axis = _COLUMN_ANCHORS[pin.ref]
    except KeyError as exc:
        raise ValueError(f"unknown pin column {pin.ref!r}") from exc
    offset = (pin.number - 1) * _PITCH
    if axis == "+y":
        return Point2D(x0, y0 + offset)
    if axis == "+x":
        return Point2D(x0 + offset, y0)
    raise ValueError(f"unsupported axis {axis!r} for column {pin.ref}")


def _build_paths_for_net(net: Net) -> List[SignalPath]:
    """Generate one merged path per net, generalised to N devices.

    Topology per net:
      ESP pin → L1 east stub → L1 north to corner_west at corridor_y →
      [via to L2 if scd_east_on_l2] → corridor segment to first device
      corner → [via to L1] → L1 vertical to device pin → corridor
      segment to next device corner → ... (repeated per device, sorted
      west-to-east by pin x).

    The L1 vertical to each device pin goes SOUTH when the pin's y is
    below the corridor (SCD41, BH1750) and NORTH when it's above
    (cantilevered OLED south of the modules) — the segment's start/end
    encode the direction, no special handling needed.

    `net.branch_east_on_l2` is retained on the Net dataclass for
    backwards compatibility but no longer consulted — the corridor
    layer is now driven entirely by `scd_east_on_l2` (one corridor
    layer per net, regardless of device count).
    """
    esp = _pin_position(net.master_pin)
    elements: List = []

    stub_end = Point2D(net.north_x, esp.y)
    corner_west = Point2D(net.north_x, net.corridor_y)

    elements.append(WireSegment(esp, stub_end, 1))
    elements.append(WireSegment(stub_end, corner_west, 1))

    corridor_layer = 2 if net.scd_east_on_l2 else 1
    if corridor_layer == 2:
        elements.append(Via(corner_west))

    # Sort device endpoints west-to-east so the corridor sweeps one
    # direction across the board.
    device_endpoints = sorted(
        (_pin_position(dp) for dp in net.device_pins),
        key=lambda p: p.x,
    )

    prev_corner = corner_west
    for dev_pos in device_endpoints:
        dev_corner = Point2D(dev_pos.x, net.corridor_y)
        elements.append(WireSegment(prev_corner, dev_corner, corridor_layer))
        if corridor_layer == 2:
            elements.append(Via(dev_corner))
        elements.append(WireSegment(dev_corner, dev_pos, 1))
        prev_corner = dev_corner

    return [SignalPath(name=net.signal.name.lower(), elements=tuple(elements))]


# ---------------------------------------------------------------------------
# AnchorSCAD vitamin
# ---------------------------------------------------------------------------

@datatree
class Tier1SubstrateDimensions:
    board_w: float = _BOARD_W
    board_h: float = _BOARD_H
    thickness: float = _THICKNESS
    hole_diameter: float = _HOLE_D
    channel_width: float = 0.8  # 22 AWG bare copper + clearance
    channel_depth: float = 0.8
    via_diameter: float = 1.5
    pocket_clearance: float = 0.3
    overcut: float = 0.1
    # Receptacle hole diameter for OLED male DuPont pin (~0.64 mm pin).
    # Smaller than `hole_diameter` so the printed plastic grips by
    # interference fit.
    #
    # 2026-05-19, confirmed by physical test: the v1 0.50–0.65 mm
    # range printed as solid plastic; the v2 ReceptacleTestCoupon
    # (rows at 0.80, 0.95, 1.10, 1.25 mm) confirmed **1.25 mm CAD**
    # as the smallest diameter that prints open AND takes a Hosyond
    # SSD1306 OLED's male header pin on the validation hardware
    # (PLA, default Bambu Studio profile, 0.4 mm nozzle). See
    # `docs/fdm_tolerance_notes.md` and `docs/paper.md` §5.5.
    receptacle_diameter: float = 1.25

    # OLED mounting features (Tier 2 only). The OLED PCB cantilevers
    # north from the receptacles in J4 and would otherwise rest at
    # z ≈ +5.5 mm — well below the SCD41 sensor IC top at z ≈ +7.65
    # mm (measured: 9.15 mm from substrate back to CO2 sensor top).
    # The pedestal lifts the OLED's header plastic body (and the OLED
    # PCB above it) high enough to clear the SCD41 with margin; the
    # support bump props up the cantilevered north end of the OLED
    # PCB so it stays level.
    #
    # Geometry budget (substrate-back z=-1.5, substrate-top z=+1.5):
    #   pedestal top      = +1.5 + 5.0 = +6.5
    #   header plastic    = +2.5
    #   OLED PCB bottom   = +6.5 + 2.5 = +9.0   ← target ≥ SCD41 top
    #   SCD41 sensor top  = +7.65 (measured)
    #   clearance         = 1.35 mm
    #
    oled_pedestal_width: float = 12.0   # x extent (covers 4 pins at 2.54)
    oled_pedestal_depth: float = 4.0    # y extent
    oled_pedestal_height: float = 5.0   # z above substrate top

    # Support bump under the OLED PCB's north end (cantilever support).
    # Height matches the pedestal so the OLED PCB sits level. xy chosen
    # to clear the SCD41 sensor IC footprint (x ∈ [6.06, 11.56],
    # y ∈ [-8.10, -2.60]) — bump centred at (0, 0) leaves it 6+ mm
    # west of the SCD41 IC.
    oled_support_bump_width: float = 4.0
    oled_support_bump_depth: float = 4.0
    oled_support_bump_height: float = 5.0
    oled_support_bump_x: float = 0.0
    oled_support_bump_y: float = 0.0
    esp32: Esp32C3SuperminiDimensions = field(default_factory=Esp32C3SuperminiDimensions)
    scd41: Scd41Dimensions = field(default_factory=Scd41Dimensions)
    bh1750: Bh1750Dimensions = field(default_factory=Bh1750Dimensions)


@ad.shape
@datatree
class Tier1Substrate(ad.CompositeShape):
    """Flat plate with module pockets, 27 through-holes, and dual-sided
    branch-merge routing channels for the four I2C bus signals.

    Tier 1: bare-copper wire soldered through every pin's clearance
    through-hole. No pressure-fit receptacles, no OLED. The substrate
    routes only the SCD41 + BH1750 devices (see `netlist.TIER1_BUS`).

    Subclasses extend this class via three hooks:
      - `_routed_nets()` to add bus devices.
      - `_add_extra_solids()` to add raised features above the substrate
        top (pedestals, support bumps, standoffs).
      - `_punch_extra_holes()` to add holes (receptacles, vents) after
        the base 27 through-holes and 3 pockets.
    `Tier2Substrate` below uses all three.
    """

    dim: Tier1SubstrateDimensions = field(default_factory=Tier1SubstrateDimensions)

    def _routed_nets(self) -> dict[I2cSignal, Net]:
        """Which NETS this substrate routes. Tier 1 = SCD41 + BH1750."""
        from netlist import TIER1_NETS
        return TIER1_NETS

    def _add_extra_solids(self, shape, d: Tier1SubstrateDimensions) -> None:
        """Hook for subclasses to add raised features (pedestals,
        support bumps) above the substrate top. Tier 1 adds nothing."""
        pass

    def _punch_extra_holes(self, shape, d: Tier1SubstrateDimensions) -> None:
        """Hook for subclasses to add extra holes (receptacles, etc.).
        Tier 1 has no extras."""
        pass

    def build(self) -> ad.Maker:
        d = self.dim

        plate = ad.Box([d.board_w, d.board_h, d.thickness])
        shape = plate.solid("plate").colour([0.92, 0.88, 0.78]).at("centre")

        # L1 = bottom face, L2 = top face. Channel boxes extend
        # `overcut` past the substrate edge so CSG cuts cleanly.
        l1_z = -d.thickness / 2 + d.channel_depth / 2 - d.overcut / 2
        l2_z = d.thickness / 2 - d.channel_depth / 2 + d.overcut / 2

        # ---- raised features above substrate top (subclass hook) ------
        # Done BEFORE punching receptacles so subclass holes can extend
        # through both the substrate body AND any added raised features.
        self._add_extra_solids(shape, d)

        # ---- module pin through-holes ---------------------------------
        hole = ad.Cylinder(r=d.hole_diameter / 2, h=d.thickness + 0.4)

        def punch_hole(pt: Point2D, name: str) -> None:
            shape.add_at(
                hole.hole(name).at("centre"),
                post=ad.translate([pt.x, pt.y, 0]),
            )

        # ESP32 columns: only punch holes for pins that carry a routed
        # bus signal. The SuperMini has 9 + 9 pins but only 4 are
        # wired on this design (J1A.2 GND, J1A.3 +3V3, J1B.1 SDA,
        # J1B.2 SCL). Skipping the other 14 saves ~20 % of slicer
        # output complexity and meaningful print time, with no
        # functional cost: the ESP32 mounts either bare-pin (only the
        # 4 needed pins soldered) or with the unused pre-soldered
        # pins trimmed flush before insertion. The 4 routed holes
        # plus the inlay pocket walls keep the module aligned.
        routed_esp_pins: set[tuple[str, int]] = set()
        for net in self._routed_nets().values():
            mp = net.master_pin
            if mp.ref in ("J1A", "J1B"):
                routed_esp_pins.add((mp.ref, mp.number))

        for ref, x_anchor in (("J1A", _J1A_X), ("J1B", _J1B_X)):
            for i in range(9):
                if (ref, i + 1) not in routed_esp_pins:
                    continue
                punch_hole(
                    _esp32_pin(x_anchor, _J1A_Y, i + 1),
                    f"{ref.lower()}_{i + 1}",
                )

        # Sensor headers stay fully populated — they come from the
        # vendor with all pins pre-soldered and need every hole to
        # seat into the pocket.
        for i in range(4):
            punch_hole(_sensor_pin(_J2_X, _J2_Y, i + 1), f"j2_{i + 1}")
        for i in range(5):
            punch_hole(_sensor_pin(_J3_X, _J3_Y, i + 1), f"j3_{i + 1}")

        # Subclass extension point (e.g. OLED receptacles).
        self._punch_extra_holes(shape, d)

        # ---- module pockets -------------------------------------------
        def punch_pocket(cx: float, cy: float, w: float, h: float,
                         pcb_t: float, name: str) -> None:
            box = ad.Box([
                w + d.pocket_clearance,
                h + d.pocket_clearance,
                pcb_t + d.overcut,
            ])
            box_z = d.thickness / 2 - pcb_t / 2 + d.overcut / 2
            shape.add_at(
                box.hole(name).at("centre"),
                post=ad.translate([cx, cy, box_z]),
            )

        esp_cx = (_J1A_X + _J1B_X) / 2
        esp_cy = _J1A_Y + 4 * _PITCH
        punch_pocket(esp_cx, esp_cy,
                     d.esp32.width, d.esp32.length,
                     d.esp32.pcb_thickness, "pocket_esp32")

        scd_cx = _J2_X + 1.5 * _PITCH
        scd_cy = _J2_Y + d.scd41.depth / 2 - d.scd41.header_body_width / 2
        punch_pocket(scd_cx, scd_cy,
                     d.scd41.width, d.scd41.depth,
                     d.scd41.pcb_thickness, "pocket_scd41")

        bh_cx = _J3_X + 2.0 * _PITCH
        bh_cy = _J3_Y + d.bh1750.depth / 2 - d.bh1750.header_body_width / 2
        punch_pocket(bh_cx, bh_cy,
                     d.bh1750.width, d.bh1750.depth,
                     d.bh1750.pcb_thickness, "pocket_bh1750")

        # ---- routing channels + vias ----------------------------------
        def cut_segment(seg: WireSegment, name: str) -> None:
            cw = d.channel_width
            cd = d.channel_depth
            cm = d.overcut
            z = l1_z if seg.layer == 1 else l2_z
            if seg.is_horizontal:
                length = abs(seg.end.x - seg.start.x)
                cx = (seg.start.x + seg.end.x) / 2
                cy = seg.start.y
                box = ad.Box([length + cm, cw, cd + cm])
            else:
                length = abs(seg.end.y - seg.start.y)
                cx = seg.start.x
                cy = (seg.start.y + seg.end.y) / 2
                box = ad.Box([cw, length + cm, cd + cm])
            shape.add_at(
                box.hole(name).at("centre"),
                post=ad.translate([cx, cy, z]),
            )

        def cut_via(via: Via, name: str) -> None:
            cyl = ad.Cylinder(r=via.diameter / 2, h=d.thickness + 0.4)
            shape.add_at(
                cyl.hole(name).at("centre"),
                post=ad.translate([via.position.x, via.position.y, 0]),
            )

        seg_idx = 0
        via_idx = 0
        for net in self._routed_nets().values():
            for path in _build_paths_for_net(net):
                for elem in path.elements:
                    if isinstance(elem, WireSegment):
                        cut_segment(elem, f"{path.name}_seg_{seg_idx}")
                        seg_idx += 1
                    else:
                        cut_via(elem, f"{path.name}_via_{via_idx}")
                        via_idx += 1

        return shape


@ad.shape
@datatree
class Tier2Substrate(Tier1Substrate):
    """Tier 1 substrate + Hosyond SSD1306 OLED on 4 pressure-fit female
    receptacles, raised on a pedestal that lifts the OLED PCB above
    the SCD41 sensor IC.

    Everything in `Tier1Substrate` is inherited unchanged: same outline,
    same 3 module pockets, same 27 module pin through-holes, same
    bare-copper routing topology. Tier 2 *adds*:

    - **Raised pedestal** centred on the OLED header (y=-22), 5 mm tall.
      Lifts the OLED's header plastic body — and therefore the OLED PCB
      itself — above the substrate top by enough to clear the SCD41
      sensor IC (top at z ≈ +7.65 from the substrate back).
    - **4 receptacle holes** through both the substrate AND the pedestal
      (combined 8 mm bore) at the OLED's J4 pin positions, sized
      `dim.receptacle_diameter` for interference fit on a 0.64 mm
      DuPont pin.
    - **Support bump** north of the receptacles, same height as the
      pedestal, to prop the OLED PCB's cantilevered end at the same
      level so the PCB stays parallel to the substrate.
    - OLED participation on the I2C bus (routing extends via
      `netlist.TIER2_NETS`).

    The pedestal + bump combination is what makes the OLED physically
    safe to mount alongside the SCD41: without them the OLED PCB would
    sit at z ≈ +5.5 — well below the SCD41 sensor IC top at z ≈ +7.65,
    crashing into the sensor.
    """

    def _routed_nets(self) -> dict[I2cSignal, Net]:
        from netlist import TIER2_NETS
        return TIER2_NETS

    def _add_extra_solids(self, shape, d: Tier1SubstrateDimensions) -> None:
        # Raised pedestal around the 4 OLED receptacles.
        pedestal = ad.Box([
            d.oled_pedestal_width,
            d.oled_pedestal_depth,
            d.oled_pedestal_height,
        ])
        # Pedestal bottom at substrate top (z = +d.thickness/2).
        # Centre at z = thickness/2 + pedestal_height/2.
        pedestal_z = d.thickness / 2 + d.oled_pedestal_height / 2
        shape.add_at(
            pedestal.solid("oled_pedestal")
            .colour([0.92, 0.88, 0.78])
            .at("centre"),
            post=ad.translate([0.0, _J4_Y, pedestal_z]),
        )

        # Support bump under the OLED PCB's north end. Same height as
        # the pedestal so the OLED PCB sits level.
        bump = ad.Box([
            d.oled_support_bump_width,
            d.oled_support_bump_depth,
            d.oled_support_bump_height,
        ])
        bump_z = d.thickness / 2 + d.oled_support_bump_height / 2
        shape.add_at(
            bump.solid("oled_support_bump")
            .colour([0.92, 0.88, 0.78])
            .at("centre"),
            post=ad.translate([
                d.oled_support_bump_x,
                d.oled_support_bump_y,
                bump_z,
            ]),
        )

    def _punch_extra_holes(self, shape, d: Tier1SubstrateDimensions) -> None:
        # Receptacle goes through both the substrate body (thickness)
        # AND the raised pedestal (oled_pedestal_height) so the OLED
        # pin can press all the way through.
        bore_h = d.thickness + d.oled_pedestal_height + 0.4
        receptacle = ad.Cylinder(r=d.receptacle_diameter / 2, h=bore_h)
        # Centre the cylinder so it spans from substrate bottom
        # (-thickness/2) to pedestal top (+thickness/2 + pedestal_h):
        #   centre = (substrate_bottom + pedestal_top) / 2
        #          = pedestal_height / 2
        receptacle_z = d.oled_pedestal_height / 2
        for i in range(4):
            pt = _sensor_pin(_J4_X, _J4_Y, i + 1)
            shape.add_at(
                receptacle.hole(f"j4_{i + 1}").at("centre"),
                post=ad.translate([pt.x, pt.y, receptacle_z]),
            )
