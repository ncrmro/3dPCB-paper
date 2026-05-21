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

import math
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
_J4_X, _J4_Y = -3.81, 10.0


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


def _build_south_band_paths(
    signal_strip_ys: dict,  # {I2cSignal: strip_y_float}
    nets: dict,
    visit_order: List[str],
) -> List[SignalPath]:
    """South-band snake-through-holes topology for power signals.

    Each signal's wire is one continuous strand that:
      master pin (terminal, 1 hole)
        → 45° SE on L1 to its bottom strip
        → east along strip on L1
        → 45° NE on L1 up to non-terminal pin hole
        → 45° SE on L2 (top) to the paired return hole
        → wire continues back DOWN through return to the strip
        → east along strip on L1
        → ... repeat at each non-terminal ...
        → 45° SW on L1 down to OLED terminal pin (terminal, 1 hole)

    Strips live in the y∈(-25, -17) band — between sensor pin row
    and substrate south edge. Each non-terminal device pin needs a
    *return hole* drilled at (pin.x + rise, strip_y), drilled by the
    subclass's `_punch_extra_holes`.

    Note: approaches at one signal's strip y must pass through any
    other signal's strip y on the way to the pin row. For example, a
    GND approach (strip y=-21) reaching the sensor pin row at y=-17
    crosses y=-19 (VCC strip) along the way — if VCC strip is cut
    there, the two L1 channels intersect and the bare wires would
    touch at the crossing. Acceptable when insulated wire is used,
    or addressed with L2+vias for the crossings in a future revision.
    """
    DEV_TO_COL = {"SCD41": "J2", "BH1750": "J3", "OLED": "J4"}

    paths: List[SignalPath] = []
    for sig, strip_y in signal_strip_ys.items():
        net = nets[sig]
        elements: List = []
        other_strip_ys = [y for s, y in signal_strip_ys.items() if s != sig]

        master = _pin_position(net.master_pin)
        master_rise = master.y - strip_y
        strip_entry = Point2D(master.x + master_rise, strip_y)
        elements.append(WireSegment(master, strip_entry, 1))

        device_keys = [d for d in visit_order if d != "ESP32"]
        prev_strip_pt = strip_entry
        for i, dev_key in enumerate(device_keys):
            col = DEV_TO_COL.get(dev_key)
            if col is None:
                continue
            pin = next((p for p in net.device_pins if p.ref == col), None)
            if pin is None:
                continue
            dev_pos = _pin_position(pin)
            rise = dev_pos.y - strip_y

            if abs(rise) > 0.01:
                approach_start = Point2D(dev_pos.x - rise, strip_y)
                # Route the diagonal on L2 (with an L1→L2 via at
                # approach_start) when an L1 diagonal would cross
                # another signal's strip — typical for the OLED VCC
                # approach, which would otherwise nick the GND strip
                # at (x≈2.27, y=-21) on L1.
                y_lo, y_hi = min(strip_y, dev_pos.y), max(strip_y, dev_pos.y)
                crosses_other = any(y_lo < y < y_hi for y in other_strip_ys)
                diag_layer = 2 if crosses_other else 1
                if abs(prev_strip_pt.x - approach_start.x) > 0.01:
                    elements.append(WireSegment(prev_strip_pt, approach_start, 1))
                elements.append(WireSegment(approach_start, dev_pos, diag_layer))
            else:
                if abs(prev_strip_pt.x - dev_pos.x) > 0.01:
                    elements.append(WireSegment(prev_strip_pt, dev_pos, 1))

            is_terminal = (i == len(device_keys) - 1)
            if is_terminal:
                break

            return_pt = Point2D(dev_pos.x + rise, strip_y)
            elements.append(WireSegment(dev_pos, return_pt, 2))
            prev_strip_pt = return_pt

        paths.append(SignalPath(name=sig.name.lower(), elements=tuple(elements)))

    return paths


def _south_band_approach_via_positions(
    signal_strip_ys: dict,
    nets: dict,
    visit_order: List[str],
) -> list[tuple[Point2D, str]]:
    """L1→L2 transition vias drilled at approach_start whenever the
    south-band diagonal had to be routed on L2 to avoid crossing
    another signal's L1 strip (see `_build_south_band_paths`)."""
    DEV_TO_COL = {"SCD41": "J2", "BH1750": "J3", "OLED": "J4"}
    out: list[tuple[Point2D, str]] = []
    for sig, strip_y in signal_strip_ys.items():
        net = nets[sig]
        other_strip_ys = [y for s, y in signal_strip_ys.items() if s != sig]
        for dev_key in [d for d in visit_order if d != "ESP32"]:
            col = DEV_TO_COL.get(dev_key)
            if col is None:
                continue
            pin = next((p for p in net.device_pins if p.ref == col), None)
            if pin is None:
                continue
            dev_pos = _pin_position(pin)
            rise = dev_pos.y - strip_y
            if abs(rise) <= 0.01:
                continue
            y_lo, y_hi = min(strip_y, dev_pos.y), max(strip_y, dev_pos.y)
            if not any(y_lo < y < y_hi for y in other_strip_ys):
                continue
            approach_start = Point2D(dev_pos.x - rise, strip_y)
            out.append((
                approach_start,
                f"{sig.name.lower()}_approach_{col.lower()}",
            ))
    return out


_BRIDGE_OFFSET = 0.5  # mm above/below crossed corridor for L2→L1→L2 jog


def _build_top_layer_paths(
    signals,
    nets: dict,
    corridor_ys: dict,
    via_escape_xs: dict,
    chamfer_length: float = 1.0,
    visit_order=("ESP32", "SCD41", "BH1750", "OLED"),
) -> List[SignalPath]:
    """Top-layer threading topology for bus signals (SCL, SDA).

    Per signal, the wire path:
      master pin (J1B, inside ESP32 pocket)
        → L1 east stub on bottom past ESP32 pocket east wall
        → via at (via_escape_xs[signal], master.y): L1 → L2 transition
        → L2 north to corridor at corridor_ys[signal]
        → L2 corridor east (through OLED PCB shadow)
        → at each sensor pin: 45° SE chamfer to pickup via at (pin.x,
          via_pickup_y) → L1 vertical south to pin → wire returns
          back up the same L1 channel → 45° NE chamfer back to corridor
        → corridor continues east past last sensor pickup, then west
        → at OLED terminal: 45° SW chamfer + L2 south descent to
          OLED pin at y=-22 (passes through pedestal area; pedestal
          stays attached via surrounding intact substrate)

    Each signal needs a unique `via_escape_xs[signal]` so the L2
    north escape segments don't overlap on top of the substrate. When
    the OLED descent crosses a lower signal's L2 corridor, a via pair
    (L2→L1→L2) bridges around the corridor — the L1 jog is short
    (~1 mm) and well clear of any L1 power strip.
    """
    DEV_TO_COL = {"SCD41": "J2", "BH1750": "J3", "OLED": "J4"}

    paths: List[SignalPath] = []
    c = chamfer_length
    for sig in signals:
        net = nets[sig]
        corridor_y = corridor_ys[sig]
        via_escape_x = via_escape_xs[sig]
        # pickup_y derived from corridor_y so chamfer is always 45° (1×1mm).
        pickup_y = corridor_y - c
        other_corridor_ys = [y for s, y in corridor_ys.items() if s != sig]
        elements: List = []

        master = _pin_position(net.master_pin)
        escape_via = Point2D(via_escape_x, master.y)
        corridor_entry = Point2D(via_escape_x, corridor_y)

        # L1 east stub from master to escape via on bottom face.
        elements.append(WireSegment(master, escape_via, 1))
        # L2 north from escape via to corridor on top face.
        elements.append(WireSegment(escape_via, corridor_entry, 2))

        device_keys = [d for d in visit_order if d != "ESP32"]
        prev_corridor_pt = corridor_entry
        for i, dev_key in enumerate(device_keys):
            col = DEV_TO_COL.get(dev_key)
            pin = next((p for p in net.device_pins if p.ref == col), None)
            if pin is None:
                continue
            dev_pos = _pin_position(pin)
            is_terminal = (i == len(device_keys) - 1)

            if is_terminal:
                # OLED terminal: corridor → 45° SW chamfer → L2 south to pin.
                chamfer_top = Point2D(dev_pos.x + c, corridor_y)
                chamfer_bot = Point2D(dev_pos.x, pickup_y)
                if abs(prev_corridor_pt.x - chamfer_top.x) > 0.01:
                    elements.append(WireSegment(prev_corridor_pt, chamfer_top, 2))
                elements.append(WireSegment(chamfer_top, chamfer_bot, 2))
                # Bridge around any lower L2 corridor the descent would cross.
                blockers = sorted(
                    [y for y in other_corridor_ys
                     if dev_pos.y < y < chamfer_bot.y],
                    reverse=True,
                )
                cur_pt = chamfer_bot
                for y_block in blockers:
                    top_via = Point2D(dev_pos.x, y_block + _BRIDGE_OFFSET)
                    bot_via = Point2D(dev_pos.x, y_block - _BRIDGE_OFFSET)
                    if abs(cur_pt.y - top_via.y) > 0.01:
                        elements.append(WireSegment(cur_pt, top_via, 2))
                    elements.append(WireSegment(top_via, bot_via, 1))
                    cur_pt = bot_via
                elements.append(WireSegment(cur_pt, dev_pos, 2))
            else:
                pickup_via = Point2D(dev_pos.x, pickup_y)
                chamfer_in = Point2D(dev_pos.x - c, corridor_y)
                chamfer_out = Point2D(dev_pos.x + c, corridor_y)
                if abs(prev_corridor_pt.x - chamfer_in.x) > 0.01:
                    elements.append(WireSegment(prev_corridor_pt, chamfer_in, 2))
                # 45° SE diagonal on L2 from corridor down to pickup via.
                elements.append(WireSegment(chamfer_in, pickup_via, 2))
                # L1 vertical from via to pin on bottom face.
                elements.append(WireSegment(pickup_via, dev_pos, 1))
                # 45° NE diagonal on L2 from pickup via back to corridor.
                elements.append(WireSegment(pickup_via, chamfer_out, 2))
                prev_corridor_pt = chamfer_out

        paths.append(SignalPath(name=sig.name.lower(), elements=tuple(elements)))

    return paths


def _top_layer_via_positions(
    signals,
    nets: dict,
    corridor_ys: dict,
    via_escape_xs: dict,
    chamfer_length: float = 1.0,
    visit_order=("ESP32", "SCD41", "BH1750", "OLED"),
) -> list[tuple[Point2D, str]]:
    """Through-substrate vias for L1↔L2 transitions in the top-layer
    threading topology. Per signal: master escape near J1B, one pickup
    via per non-terminal sensor pin, plus a via pair around each lower
    L2 corridor the terminal descent must cross."""
    DEV_TO_COL = {"SCD41": "J2", "BH1750": "J3", "OLED": "J4"}
    out: list[tuple[Point2D, str]] = []
    for sig in signals:
        net = nets[sig]
        corridor_y = corridor_ys[sig]
        pickup_y = corridor_y - chamfer_length
        master = _pin_position(net.master_pin)
        out.append((
            Point2D(via_escape_xs[sig], master.y),
            f"{sig.name.lower()}_escape_via",
        ))
        device_keys = [d for d in visit_order if d != "ESP32"]
        terminal_idx = len(device_keys) - 1
        for i, dev_key in enumerate(device_keys):
            col = DEV_TO_COL.get(dev_key)
            pin = next((p for p in net.device_pins if p.ref == col), None)
            if pin is None:
                continue
            dev_pos = _pin_position(pin)
            if i == terminal_idx:
                # Bridge vias around any lower L2 corridor on the descent.
                other_corridor_ys = [
                    y for s, y in corridor_ys.items() if s != sig
                ]
                blockers = sorted(
                    [y for y in other_corridor_ys
                     if dev_pos.y < y < pickup_y],
                    reverse=True,
                )
                for j, y_block in enumerate(blockers):
                    out.append((
                        Point2D(dev_pos.x, y_block + _BRIDGE_OFFSET),
                        f"{sig.name.lower()}_bridge_top_{j}",
                    ))
                    out.append((
                        Point2D(dev_pos.x, y_block - _BRIDGE_OFFSET),
                        f"{sig.name.lower()}_bridge_bot_{j}",
                    ))
                continue
            out.append((
                Point2D(dev_pos.x, pickup_y),
                f"{sig.name.lower()}_pickup_{col.lower()}",
            ))
    return out


def _south_band_return_holes(
    signal_strip_ys: dict,
    nets: dict,
    visit_order: List[str],
) -> list[tuple[Point2D, str]]:
    """Return holes for every non-terminal device pin in the south band."""
    DEV_TO_COL = {"SCD41": "J2", "BH1750": "J3", "OLED": "J4"}
    out: list[tuple[Point2D, str]] = []
    device_keys = [d for d in visit_order if d != "ESP32"]
    if not device_keys:
        return out
    non_terminals = device_keys[:-1]
    for sig, strip_y in signal_strip_ys.items():
        net = nets[sig]
        for dev_key in non_terminals:
            col = DEV_TO_COL.get(dev_key)
            pin = next((p for p in net.device_pins if p.ref == col), None)
            if pin is None:
                continue
            dev_pos = _pin_position(pin)
            rise = dev_pos.y - strip_y
            return_pt = Point2D(dev_pos.x + rise, strip_y)
            out.append((return_pt, f"{sig.name.lower()}_return_{col.lower()}"))
    return out


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
# ESP32 → OLED power-only snake (Tier 2 minimal topology)
# ---------------------------------------------------------------------------

# Each power signal's L1 east-west "highway" y. With the OLED mounted
# silkscreen-up (J4.1=GND west, J4.2=VCC just east), VCC's L1 east
# leg must cross GND's pin-column at x=-3.81 on its way to x=-1.27 —
# so VCC's east leg has to live at a y OUTSIDE GND's final-vertical
# y range [+5, +10]. Choosing y=+12 (just north of the pedestal,
# above the OLED pin row) keeps the crossing on different y; VCC
# then drops back south on L1 from (vcc_target, +12) to the OLED pin
# at (vcc_target, +10).
_OLED_ONLY_HIGHWAY_YS = {
    "VCC": 12.0,
    "GND": 5.0,
}

# L1 escape columns INSIDE the ESP32 pocket footprint (pocket x ∈
# [-26.61, -15.61]). The wire jogs east from the master pin onto this
# column, then runs north on L1 — i.e. genuinely tunnels under the
# ESP32 module before exiting the pocket north edge. VCC is placed
# WEST of GND so the VCC east-jog (at vcc_master.y, between the two
# L1 verticals) doesn't traverse GND's vertical column — otherwise
# the stub would cross GND's L1 north leg at (gnd_escape_x, vcc_master.y).
_OLED_ONLY_ESCAPE_XS = {
    "VCC": -25.0,
    "GND": -22.0,
}

# Distance south of each OLED pin for the L2 stub + return hole. With
# the pedestal at (0, +10) (y ∈ [+8, +12]), -4 mm puts the return hole
# at y=+6 — south of the pedestal in intact substrate, on the path
# toward the SCD41 pin row at y=-17. The L2 stub's first 2 mm runs
# under the pedestal (acceptable undercut); the rest is clear.
_OLED_ONLY_RETURN_OFFSET = -4.0

# y-corridor for the L1 continuation east-leg between the OLED-return
# x column and the SCD41/BH1750 pin x columns. Each signal gets a
# unique y to keep east legs on the same layer from sharing a row.
#   GND  -21.0  — south of every pocket south edge. Was -19.0; moved
#                further south to open a clear L1 east-west band
#                between pin row (-17) and GND for bus L1 returns
#                (SCL J2.3/J3.3 extensions at y=-19.3).
#   VCC  -15.3  — north of pin row; 0.7 mm CAD wall to pin hole north
#                edges at -16.5 ✓. Was -16.0 (0.1 mm wall) — moved
#                north to clear the 0.6 mm FDM printable-wall floor
#                (failure mode #7 in the printable_pcb job).
# SCL/SDA entries are vestigial — bus signals route via the
# north-shoulder L2 highway, not via this SCD41 corridor.
_SCD41_CORRIDOR_YS = {
    "VCC": -15.3,
    "GND": -21.0,
}

# Bus-signal routing uses a north-shoulder highway on L2: each signal
# escapes the ESP32 pocket on L1, transitions to L2 via an escape
# through-hole drilled in clear substrate, then runs east along a
# per-signal highway at the substrate's north shoulder (y ≈ +17/+18)
# clear of the OLED pedestal (y ∈ [+8, +12]) and the substrate north
# edge at +25. South stubs drop from the highway into the OLED pin
# row at y=+10 and continue east to the SCD41 pin extensions.
#
# Highway ys give each bus signal its own L2 row so two east-runs
# don't share a corridor — 1 mm separation is enough for 0.8 mm
# channels (0.2 mm wall between edges).
#
# SCL: master at J1B.2 (-12.22, -14.46). L1 east escape to (-10,
#   -14.46), via to L2, L2 north to highway, then east.
# SDA: master at J1B.1 (-12.22, -17). L2 north at x=-12.22 would
#   pass through the SCL master pin hole at J1B.2 (foreign-pin
#   intrusion). SDA detours: L1 south to y=-21 (below every pocket
#   south edge), via to L2, L2 east to x=+1.5 (in the open gap
#   between ESP32 east edge at -12.11 and SCD41 west edge at +2.16),
#   L2 north up to highway. The +1.5 column is chosen so the x=+17
#   gap between SCD41 and BH1750 stays free for the SCL J2.3 bridge.
_BUS_HIGHWAY_YS = {"SCL": 17.0, "SDA": 20.0}
_SDA_SOUTH_DETOUR_Y = -21.0
# SDA's L2 vertical climbs from the south band at y=-21 to its
# highway at y=+19. The column sits east of the BH1750 pocket
# (BH1750 east edge +32.08) at x=+34 — clear of SCL's bridge
# column at x=+17 (in the SCD41/BH1750 gap +15.46..+18.08), which
# is needed for SCL's J2.3/J3.3 sensor extensions. SDA detours
# all the way east at the south band before climbing.
_SDA_NORTH_ESCAPE_X = 34.0  # east of BH1750 pocket (+32.08)

# SCL sensor extensions reach J2.3 (+10.08, -17) and J3.3 (+25.08,
# -17) by dropping L2 south from the highway at the bridge column,
# transitioning to L1 just south of the pin row, and running
# L1 east-west to each pin's column with a short north stub up
# to the pin. The L1 east-west y must:
#   - clear pin holes at y=-17 (channel north < -17.5 - 0.6 = -18.1)
#   - clear GND L1 east leg at y=-19 (channel south > -19.4 + 0.6 = -18.8)
# Gap (-18.8, -18.1) — pick -18.5 (centred, 0.3 mm margin each side).
_SCL_BRIDGE_X = 17.0  # SCD41/BH1750 clear gap
# SCL bridge bottom y = -19.3 — south of pin row (channel south clears
# foreign pin holes by 0.6 mm) AND north of GND corridor at -21
# (channel south clears GND inflated north by 0.6 mm). The L1 east-
# west and the L2→L1 transition via both live at this y.
_SCL_BRIDGE_BOTTOM_Y = -19.3


def _build_oled_only_power_paths(nets: dict) -> List[SignalPath]:
    """One snake per power signal: master → OLED → SCD41 → BH1750.

    Topology:
      master (J1A, on L1)
        → L1 east jog onto an escape column inside the ESP32 pocket
        → L1 north under the ESP32, out the pocket footprint, to the
          highway y in the open north band (VCC's highway is above the
          OLED pin row at y=+12, GND's is below at y=+5)
        → L1 east along the highway to the OLED pin's x column
        → L1 vertical onto the OLED pin (north for GND, south for VCC)
        → L2 stub SOUTH from the OLED pin, 4 mm past the pedestal south
          edge (under-pedestal undercut for the first 2 mm is the price
          of putting the return hole on the path toward SCD41 instead
          of north away from it)
        → return through-hole at (oled_x, +6): L2 → L1
        → L1 south down to the per-signal corridor y, east along that
          corridor to (scd_x, corridor_y), and a north stub up to the
          SCD41 pin — the wire enters the pin from the corridor side
        → wire wraps around the SCD41 pin and returns to the corridor:
          the model emits a second east leg starting back at
          (scd_x, corridor_y) and running east to the BH1750 pin's x
          column, ending with a north stub up to the BH1750 pin
          (J3.2 for GND, J3.1 for VCC)
    """
    from netlist import I2cSignal
    paths: List[SignalPath] = []
    sig_map = {"VCC": I2cSignal.VCC, "GND": I2cSignal.GND}
    for name, sig in sig_map.items():
        net = nets.get(sig)
        if net is None:
            continue
        oled_pin = next((p for p in net.device_pins if p.ref == "J4"), None)
        scd41_pin = next((p for p in net.device_pins if p.ref == "J2"), None)
        bh1750_pin = next((p for p in net.device_pins if p.ref == "J3"), None)
        if oled_pin is None or scd41_pin is None:
            continue

        master = _pin_position(net.master_pin)
        oled_xy = _pin_position(oled_pin)
        scd_xy = _pin_position(scd41_pin)
        bh_xy = _pin_position(bh1750_pin) if bh1750_pin is not None else None
        escape_x = _OLED_ONLY_ESCAPE_XS[name]
        hy = _OLED_ONLY_HIGHWAY_YS[name]
        return_y = oled_xy.y + _OLED_ONLY_RETURN_OFFSET
        corridor_y = _SCD41_CORRIDOR_YS[name]

        elements: List = []

        # Master → OLED on L1, with an L2 stub south to the return hole.
        cur = master
        if abs(escape_x - master.x) > 0.01:
            jog = Point2D(escape_x, master.y)
            elements.append(WireSegment(cur, jog, 1))
            cur = jog
        rise = Point2D(cur.x, hy)
        elements.append(WireSegment(cur, rise, 1))
        east = Point2D(oled_xy.x, hy)
        elements.append(WireSegment(rise, east, 1))
        elements.append(WireSegment(east, oled_xy, 1))  # final vertical onto OLED pin
        return_xy = Point2D(oled_xy.x, return_y)
        elements.append(WireSegment(oled_xy, return_xy, 2))  # L2 stub south

        # OLED return hole → SCD41 on L1.
        cont_south = Point2D(oled_xy.x, corridor_y)
        elements.append(WireSegment(return_xy, cont_south, 1))
        cont_east = Point2D(scd_xy.x, corridor_y)
        elements.append(WireSegment(cont_south, cont_east, 1))
        elements.append(WireSegment(cont_east, scd_xy, 1))  # north stub to SCD41 pin

        # SCD41 → BH1750 along the same corridor; the SCD41 pin acts as
        # a wire-loop junction. Three L1 segments meet at (scd_x,
        # corridor_y): the incoming east leg, the north stub up into
        # the SCD41 pin, and the outgoing east leg toward BH1750.
        if bh_xy is not None:
            scd_to_bh = Point2D(bh_xy.x, corridor_y)
            elements.append(WireSegment(cont_east, scd_to_bh, 1))
            elements.append(WireSegment(scd_to_bh, bh_xy, 1))  # north stub to BH1750 pin

        paths.append(SignalPath(name=name.lower(), elements=tuple(elements)))

    return paths


_BUS_L1_ESCAPE_X = -10.0  # 2 mm east of ESP32 pocket east edge (-12.11)


def _build_bus_signal_paths(nets: dict) -> List[SignalPath]:
    """North-shoulder highway routing per bus signal: master → OLED.
    Sensor extensions (SCD41 + BH1750) remain deferred — see the
    note at the end of this docstring.

    The J1B master pins sit INSIDE the ESP32 PCB footprint (PCB is
    18 × 22.5 mm and the J1B column at x=-12.22 is ~0.1 mm inside
    the pocket east edge at -12.11). An L2 segment emerging directly
    from a J1B master would short into the ESP32 board. Each bus
    signal escapes on L1 first (below the pocket), out to a column
    clear of the pocket, then transitions to L2 via an explicit
    through-hole.

    Topology:
      SCL: L1 east escape from J1B.2 (-12.22, -14.46) → (-10, -14.46),
           via to L2, L2 north to highway y=+17, L2 east along the
           highway, south drop into OLED J4.3 at (+1.27, +10).
           Highway continues east to the bridge column x=+17 in the
           SCD41/BH1750 gap. L2 south from (+17, +17) to
           (+17, -18.5), via to L1 there. From the bridge bottom:
           L1 west to (+10.08, -18.5) then north 1.5 mm into J2.3,
           AND L1 east to (+25.08, -18.5) then north 1.5 mm into
           J3.3. Both L1 east-west legs span x ranges that exclude
           GND's north stubs (at x=+7.54 and x=+27.62 — outside
           the [+10.08, +17] and [+17, +25.08] spans).
      SDA: L1 south escape from J1B.1 (-12.22, -17) → (-12.22, -21)
           past all pocket south edges, via to L2, L2 east to x=+34
           (east of BH1750 pocket +32.08), L2 north to highway
           y=+19, L2 west to OLED J4.4 at (+3.81, +10). SDA detours
           all the way east at the south band to leave the
           SCD41/BH1750 gap free for SCL's bridge column.

    Deferred sensor extensions:
      SDA → J2.4 (+12.62, -17) and SDA → J3.2 (+22.54, -17) remain
      unwired. Both are inside the SCD41/BH1750 pocket-spanned x
      range. Any L1 east-west bus return that reaches them crosses
      GND's north stubs (at x=+7.54 for J2.2, at +27.62 for J3.4),
      since the GND-stub channels span y∈[GND_corridor, pin_row].
      The SCD41/BH1750 gap (where SCL's bridge sits) cannot fit a
      second L2 vertical for SDA — only one via column fits in the
      2.62 mm gap with printable-wall clearances. Fixing requires
      either: (a) restructuring VCC/GND to use 45° stubs (so the
      stub at a given x doesn't span the full y range from corridor
      to pin); (b) per-pin SDA return holes drilled adjacent to
      each sensor's SDA pin, with a manual solder jumper on top of
      the substrate; (c) the conductivity refinement (allow L2
      under silkscreened PCB-back regions). All three are bigger
      changes than the SCL extension that fits the current
      topology cleanly. Tier2SubstrateBundled lists these pins in
      `_known_unconnected_pins` so the connectivity test surfaces
      the gap honestly without false-green."""
    from netlist import I2cSignal
    paths: List[SignalPath] = []
    sig_map = {"SCL": I2cSignal.SCL, "SDA": I2cSignal.SDA}
    for name, sig in sig_map.items():
        net = nets.get(sig)
        if net is None:
            continue
        oled_pin = next((p for p in net.device_pins if p.ref == "J4"), None)
        if oled_pin is None:
            continue

        master = _pin_position(net.master_pin)
        oled_xy = _pin_position(oled_pin)
        highway_y = _BUS_HIGHWAY_YS[name]

        elements: List = []

        if name == "SDA":
            # L1 south past the ESP32 pocket south edge, then via to L2.
            l1_end = Point2D(master.x, _SDA_SOUTH_DETOUR_Y)
            elements.append(WireSegment(master, l1_end, 1))
            east = Point2D(_SDA_NORTH_ESCAPE_X, _SDA_SOUTH_DETOUR_Y)
            elements.append(WireSegment(l1_end, east, 2))
            rise = Point2D(_SDA_NORTH_ESCAPE_X, highway_y)
            elements.append(WireSegment(east, rise, 2))
            oled_corner = Point2D(oled_xy.x, highway_y)
            elements.append(WireSegment(rise, oled_corner, 2))
            # Enter J4.4 from BELOW via L1, not L2. An L2 south stub
            # from (+3.81, +20) to (+3.81, +10) would cross SCL's L2
            # east leg at (+3.81, +17). Instead, transition to L1 at
            # the OLED-column highway corner and run L1 south. The
            # via at (oled_xy.x, highway_y) is drilled at hole_diameter
            # (smaller than via_diameter) so its inflated y stays
            # clear of SCL's highway by the 0.6 mm wall floor.
            elements.append(WireSegment(oled_corner, oled_xy, 1))
        else:  # SCL
            # L1 east past the ESP32 pocket east edge, then via to L2.
            l1_end = Point2D(_BUS_L1_ESCAPE_X, master.y)
            elements.append(WireSegment(master, l1_end, 1))
            rise = Point2D(_BUS_L1_ESCAPE_X, highway_y)
            elements.append(WireSegment(l1_end, rise, 2))
            oled_corner = Point2D(oled_xy.x, highway_y)
            elements.append(WireSegment(rise, oled_corner, 2))
            elements.append(WireSegment(oled_corner, oled_xy, 2))

            # SCD41 (J2.3) and BH1750 (J3.3) sensor extensions —
            # highway continues east from the OLED column to the
            # bridge column at x=+17, L2 south to L1, then L1
            # east-west to each pin column with a short north stub
            # up to the pin.
            scd41_scl = next((p for p in net.device_pins if p.ref == "J2"), None)
            bh1750_scl = next((p for p in net.device_pins if p.ref == "J3"), None)
            if scd41_scl is not None or bh1750_scl is not None:
                bridge_top = Point2D(_SCL_BRIDGE_X, highway_y)
                elements.append(WireSegment(oled_corner, bridge_top, 2))
                bridge_bot = Point2D(_SCL_BRIDGE_X, _SCL_BRIDGE_BOTTOM_Y)
                elements.append(WireSegment(bridge_top, bridge_bot, 2))
                if scd41_scl is not None:
                    scd_xy = _pin_position(scd41_scl)
                    west_at_bridge_y = Point2D(scd_xy.x, _SCL_BRIDGE_BOTTOM_Y)
                    elements.append(WireSegment(bridge_bot, west_at_bridge_y, 1))
                    elements.append(WireSegment(west_at_bridge_y, scd_xy, 1))
                if bh1750_scl is not None:
                    bh_xy = _pin_position(bh1750_scl)
                    east_at_bridge_y = Point2D(bh_xy.x, _SCL_BRIDGE_BOTTOM_Y)
                    elements.append(WireSegment(bridge_bot, east_at_bridge_y, 1))
                    elements.append(WireSegment(east_at_bridge_y, bh_xy, 1))

        paths.append(SignalPath(name=name.lower(), elements=tuple(elements)))

    return paths


def _bus_bridge_via_positions(nets: dict) -> list[tuple[Point2D, str]]:
    """L1↔L2 transition vias drilled at via_diameter = 1.5 mm. The
    SCL escape and SDA escape vias sit just outside the ESP32 pocket
    where the extra width is harmless. The narrower L1↔L2 holes
    (SCL bridge bottom, SDA OLED entry) use hole_diameter and are
    in `_bus_bridge_hole_positions` instead."""
    from netlist import I2cSignal
    out: list[tuple[Point2D, str]] = []
    net_scl = nets.get(I2cSignal.SCL)
    if net_scl is not None:
        master_scl = _pin_position(net_scl.master_pin)
        out.append((Point2D(_BUS_L1_ESCAPE_X, master_scl.y), "scl_escape_via"))
    net_sda = nets.get(I2cSignal.SDA)
    if net_sda is not None:
        master_sda = _pin_position(net_sda.master_pin)
        out.append((Point2D(master_sda.x, _SDA_SOUTH_DETOUR_Y), "sda_escape_via"))
    return out


def _bus_bridge_hole_positions(nets: dict) -> list[tuple[Point2D, str]]:
    """L1↔L2 transition holes drilled at hole_diameter = 1.0 mm.
    Used where via_diameter (1.5 mm) inflates close enough to a
    foreign feature (SCL highway, pin row, GND corridor) that the
    larger drill would violate the printable-wall floor.

    Names DON'T end in `_via` so the test's diameter-dispatch logic
    falls through to `hole_diameter`."""
    from netlist import I2cSignal
    out: list[tuple[Point2D, str]] = []
    net_scl = nets.get(I2cSignal.SCL)
    if net_scl is not None and any(p.ref in ("J2", "J3") for p in net_scl.device_pins):
        out.append((
            Point2D(_SCL_BRIDGE_X, _SCL_BRIDGE_BOTTOM_Y),
            "scl_bridge",
        ))
    net_sda = nets.get(I2cSignal.SDA)
    if net_sda is not None:
        sda_oled = next((p for p in net_sda.device_pins if p.ref == "J4"), None)
        if sda_oled is not None:
            oled_xy = _pin_position(sda_oled)
            highway_y = _BUS_HIGHWAY_YS["SDA"]
            out.append((
                Point2D(oled_xy.x, highway_y),
                "sda_oled_entry",
            ))
    return out


def _oled_only_return_hole_positions(nets: dict) -> list[tuple[Point2D, str]]:
    """Position of the L2→L1 return through-hole south of each OLED
    POWER pin. Bus signals (SCL/SDA) terminate at the OLED pin (or
    continue east on the highway) and never use a return hole, so
    they're excluded."""
    from netlist import I2cSignal
    out: list[tuple[Point2D, str]] = []
    for name, sig in (
        ("vcc", I2cSignal.VCC),
        ("gnd", I2cSignal.GND),
    ):
        net = nets.get(sig)
        if net is None:
            continue
        oled_pin = next((p for p in net.device_pins if p.ref == "J4"), None)
        if oled_pin is None:
            continue
        target = _pin_position(oled_pin)
        ret = Point2D(target.x, target.y + _OLED_ONLY_RETURN_OFFSET)
        out.append((ret, f"{name}_oled_return"))
    return out


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
    # Minimum substrate-wall thickness between any two voids (channel,
    # hole, via, pocket). Below this floor an FDM printer at 0.4 mm
    # nozzle merges the two voids into one — see
    # `docs/fdm_tolerance_notes.md`. The routing voxel test inflates
    # each void by `min_wall_thickness / 2` and flags inflated overlaps
    # between different signals as a wall-thickness failure.
    min_wall_thickness: float = 0.6
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

    def _known_unconnected_pins(self) -> tuple[tuple[str, str, int], ...]:
        """Tuple of (signal_name, pin_ref, pin_number) entries that
        this substrate intentionally leaves unwired despite being
        listed in `_routed_nets()`. Used by the connectivity test
        to surface deferred work without false-green CI. Override
        on subclasses that have known topological constraints."""
        return ()

    def _get_signal_paths(self) -> List[SignalPath]:
        """Per-signal corridor topology (one corridor per net).

        Subclasses can replace this hook to swap in a different topology
        without re-implementing all of `build()`. `Tier2SubstrateBundled`
        overrides this to emit the bundled-bus topology.

        Orthogonal paths are post-processed through
        `voxel_suggester.apply_chamfers` to replace any safe axis-
        aligned L-bend with a 45° diagonal — the chamfer is only
        applied when the diagonal still satisfies the printable wall
        buffer (failure mode #7) against all other features.
        """
        paths: List[SignalPath] = []
        for net in self._routed_nets().values():
            paths.extend(_build_paths_for_net(net))
        # Lazy import to avoid a substrate ↔ voxel_suggester import cycle.
        from voxel_suggester import apply_chamfers
        return apply_chamfers(self, paths)

    def _add_extra_solids(self, shape, d: Tier1SubstrateDimensions) -> None:
        """Hook for subclasses to add raised features (pedestals,
        support bumps) above the substrate top. Tier 1 adds nothing."""
        pass

    def _punch_extra_holes(self, shape, d: Tier1SubstrateDimensions) -> None:
        """Hook for subclasses to add extra holes (receptacles, etc.).
        Tier 1 has no extras."""
        pass

    def _standard_hole_positions(self) -> list[tuple["Point2D", str]]:
        """Pin through-holes drilled at the default hole_diameter:
        routed ESP32 master pins plus every sensor (J2, J3) pin.

        Build() uses this to drive the punch loop, and the routing
        tests use it (together with `_drilled_hole_positions`) to
        check that no routed channel intrudes on a foreign pin hole."""
        routed_esp_pins: set[tuple[str, int]] = set()
        for net in self._routed_nets().values():
            mp = net.master_pin
            if mp.ref in ("J1A", "J1B"):
                routed_esp_pins.add((mp.ref, mp.number))

        holes: list[tuple[Point2D, str]] = []
        for ref, x_anchor in (("J1A", _J1A_X), ("J1B", _J1B_X)):
            for i in range(9):
                if (ref, i + 1) not in routed_esp_pins:
                    continue
                holes.append(
                    (_esp32_pin(x_anchor, _J1A_Y, i + 1), f"{ref}.{i + 1}")
                )
        for i in range(4):
            holes.append((_sensor_pin(_J2_X, _J2_Y, i + 1), f"J2.{i + 1}"))
        for i in range(5):
            holes.append((_sensor_pin(_J3_X, _J3_Y, i + 1), f"J3.{i + 1}"))
        return holes

    def _drilled_hole_positions(self) -> list[tuple["Point2D", str]]:
        """Every drilled through-hole on this substrate, including
        subclass extras (OLED receptacles, return holes, vias).
        Subclasses override to extend the standard list."""
        return list(self._standard_hole_positions())

    def _module_pcb_footprints(self) -> list[tuple[str, float, float, float, float]]:
        """Sensor PCB xy footprints (= pocket footprints).

        Returns (name, cx, cy, half_w, half_l) per module. Sensor PCBs
        physically sit IN the pocket cavities, occupying the same
        z-band as L2 routing channels — any L2 wire whose xy lands
        inside one of these footprints would short into the module
        PCB. The voxel test uses this list to forbid L2 wires in
        sensor pocket xy. OLED PCB is excluded: it sits above the
        pedestal at z≈+9, well clear of L2's z=+0.7..+1.5 band, so
        L2 wires under the OLED PCB don't make contact.

        This is the CONSERVATIVE model — the full PCB back is treated
        as forbidden. Most module backs are silkscreened or
        soldermask-covered with only specific regions (pin barrels,
        exposed traces) actually conductive. See
        `docs/module_back_conductivity.md` for the per-module audit
        and the future refinement plan."""
        d = self.dim
        esp_cx = (_J1A_X + _J1B_X) / 2
        esp_cy = _J1A_Y + 4 * _PITCH
        scd_cx = _J2_X + 1.5 * _PITCH
        scd_cy = _J2_Y + d.scd41.depth / 2 - d.scd41.header_body_width / 2
        bh_cx = _J3_X + 2.0 * _PITCH
        bh_cy = _J3_Y + d.bh1750.depth / 2 - d.bh1750.header_body_width / 2
        return [
            ("ESP32",  esp_cx, esp_cy, d.esp32.width  / 2, d.esp32.length / 2),
            ("SCD41",  scd_cx, scd_cy, d.scd41.width  / 2, d.scd41.depth  / 2),
            ("BH1750", bh_cx,  bh_cy,  d.bh1750.width / 2, d.bh1750.depth / 2),
        ]

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

        # ESP32 columns: only the routed master pins are drilled
        # (SuperMini has 18 pins but only 4 are wired). Sensor headers
        # are fully populated — they come from the vendor with all pins
        # pre-soldered and need every hole to seat into the pocket.
        # The exact enumeration lives in `_standard_hole_positions` so
        # routing tests can audit it without re-running the build.
        for pt, name in self._standard_hole_positions():
            punch_hole(pt, name.lower().replace(".", "_"))

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
            dx = seg.end.x - seg.start.x
            dy = seg.end.y - seg.start.y
            length = math.hypot(dx, dy)
            cx = (seg.start.x + seg.end.x) / 2
            cy = (seg.start.y + seg.end.y) / 2
            # Box default extent is along +X. Rotate around Z to align
            # with the segment direction so diagonals cut at 45° instead
            # of collapsing into axis-aligned drops.
            angle_deg = math.degrees(math.atan2(dy, dx))
            box = ad.Box([length + cm, cw, cd + cm])
            shape.add_at(
                box.hole(name).at("centre"),
                post=ad.translate([cx, cy, z]) * ad.rotZ(angle_deg),
            )

        def cut_via(via: Via, name: str) -> None:
            cyl = ad.Cylinder(r=via.diameter / 2, h=d.thickness + 0.4)
            shape.add_at(
                cyl.hole(name).at("centre"),
                post=ad.translate([via.position.x, via.position.y, 0]),
            )

        seg_idx = 0
        via_idx = 0
        for path in self._get_signal_paths():
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

    def _oled_receptacle_positions(self) -> list[tuple["Point2D", str]]:
        return [
            (_sensor_pin(_J4_X, _J4_Y, i + 1), f"J4.{i + 1}")
            for i in range(4)
        ]

    def _drilled_hole_positions(self) -> list[tuple["Point2D", str]]:
        return super()._drilled_hole_positions() + self._oled_receptacle_positions()

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
        for pt, name in self._oled_receptacle_positions():
            shape.add_at(
                receptacle.hole(name.lower().replace(".", "_")).at("centre"),
                post=ad.translate([pt.x, pt.y, receptacle_z]),
            )


@ad.shape
@datatree
class Tier2SubstrateBundled(Tier2Substrate):
    """Tier 2 substrate with split bus-trunk topology — power signals
    snake through the south band on a threadable wire path, bus
    signals keep the existing north-corridor model.

    Per-signal routing:

      VCC, GND (south band)
        master → 45° SE to south strip → east → 45° NE up to non-terminal
        pin (solder) → 45° SE on L2 to paired return hole → continue east
        → ... → 45° SW down to OLED terminal pin.
        Each non-terminal pin gets a 2nd "return" through-hole drilled
        south of the pin row.

      SCL, SDA (north band)
        Existing per-signal corridor model: master east-stub → north
        escape → L2 east corridor → south to each device pin. Branches,
        not a continuous snake — bus signals don't get the threading
        treatment because the optimizer's per-signal-vs-bundled
        comparison naturally pairs them with the corridor model.

    This split prevents the diagonal crossings that occur when all
    four signals share the south band; only VCC↔GND can still cross
    within the south band (acceptable for insulated wire, future work
    for vias). Returns sit between the sensor pin row and substrate
    south edge per the user's preferred install layout.
    """

    # South band visits OLED first so the wire sweeps strictly east —
    # avoids a ~27 mm L1 backsweep that the OLED-as-terminal order
    # produced. Top layer keeps OLED as terminal so its L2 descent
    # through the pedestal shadow stays a single straight drop instead
    # of a sensor-style L1 pickup (which would cross VCC/GND L1 strips).
    _SOUTH_BAND_VISIT_ORDER = ("ESP32", "OLED", "SCD41", "BH1750")
    _TOP_LAYER_VISIT_ORDER = ("ESP32", "SCD41", "BH1750", "OLED")
    _SOUTH_BAND_STRIP_YS = {  # filled in lazily — depends on I2cSignal import
        # I2cSignal.VCC: -19.0, I2cSignal.GND: -21.0
    }
    _TOP_LAYER_CORRIDOR_YS = {
        # I2cSignal.SCL: 5.0, I2cSignal.SDA: 6.5
    }
    _TOP_LAYER_VIA_ESCAPE_XS = {
        # I2cSignal.SCL: -6.0, I2cSignal.SDA: -8.0 — staggered so the
        # two L2 north escapes don't share an x column.
    }
    _TOP_LAYER_CHAMFER_LENGTH = 1.0

    def _south_band_strip_ys(self) -> dict:
        from netlist import I2cSignal
        if not self._SOUTH_BAND_STRIP_YS:
            self._SOUTH_BAND_STRIP_YS.update({
                I2cSignal.VCC: -19.0,
                I2cSignal.GND: -21.0,
            })
        return self._SOUTH_BAND_STRIP_YS

    def _top_layer_corridor_ys(self) -> dict:
        from netlist import I2cSignal
        if not self._TOP_LAYER_CORRIDOR_YS:
            self._TOP_LAYER_CORRIDOR_YS.update({
                I2cSignal.SCL: 5.0,
                I2cSignal.SDA: 6.5,
            })
        return self._TOP_LAYER_CORRIDOR_YS

    def _top_layer_via_escape_xs(self) -> dict:
        from netlist import I2cSignal
        if not self._TOP_LAYER_VIA_ESCAPE_XS:
            self._TOP_LAYER_VIA_ESCAPE_XS.update({
                I2cSignal.SCL: -6.0,
                I2cSignal.SDA: -8.0,
            })
        return self._TOP_LAYER_VIA_ESCAPE_XS

    def _get_signal_paths(self) -> List[SignalPath]:
        from netlist import TIER2_NETS
        paths = (
            _build_oled_only_power_paths(TIER2_NETS)
            + _build_bus_signal_paths(TIER2_NETS)
        )
        from voxel_suggester import apply_chamfers
        return apply_chamfers(self, paths)

    def _drilled_hole_positions(self) -> list[tuple["Point2D", str]]:
        from netlist import TIER2_NETS
        return (
            super()._drilled_hole_positions()
            + list(_oled_only_return_hole_positions(TIER2_NETS))
            + list(_bus_bridge_via_positions(TIER2_NETS))
            + list(_bus_bridge_hole_positions(TIER2_NETS))
        )

    def _known_unconnected_pins(self) -> tuple[tuple[str, str, int], ...]:
        # SDA → J2.4 (SCD41 SDA pin) and SDA → J3.2 (BH1750 SDA pin)
        # cannot be wired with the current power-corridor topology —
        # see the deferred-extensions block in
        # `_build_bus_signal_paths` for the topological constraint.
        return (
            ("SDA", "J2", 4),
            ("SDA", "J3", 2),
        )

    def _add_extra_solids(self, shape, d: Tier1SubstrateDimensions) -> None:
        # Pedestal only — the cantilever support bump is omitted because
        # the OLED is now centered on the substrate and no longer hangs
        # off a single edge.
        pedestal = ad.Box([
            d.oled_pedestal_width,
            d.oled_pedestal_depth,
            d.oled_pedestal_height,
        ])
        pedestal_z = d.thickness / 2 + d.oled_pedestal_height / 2
        shape.add_at(
            pedestal.solid("oled_pedestal")
            .colour([0.92, 0.88, 0.78])
            .at("centre"),
            post=ad.translate([0.0, _J4_Y, pedestal_z]),
        )

    def _punch_extra_holes(self, shape, d: Tier1SubstrateDimensions) -> None:
        super()._punch_extra_holes(shape, d)
        from netlist import TIER2_NETS
        hole = ad.Cylinder(r=d.hole_diameter / 2, h=d.thickness + 0.4)
        for pt, name in _oled_only_return_hole_positions(TIER2_NETS):
            shape.add_at(
                hole.hole(name).at("centre"),
                post=ad.translate([pt.x, pt.y, 0]),
            )
        via = ad.Cylinder(r=d.via_diameter / 2, h=d.thickness + 0.4)
        for pt, name in _bus_bridge_via_positions(TIER2_NETS):
            shape.add_at(
                via.hole(name).at("centre"),
                post=ad.translate([pt.x, pt.y, 0]),
            )
        for pt, name in _bus_bridge_hole_positions(TIER2_NETS):
            shape.add_at(
                hole.hole(name).at("centre"),
                post=ad.translate([pt.x, pt.y, 0]),
            )
