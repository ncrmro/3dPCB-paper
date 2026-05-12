#!/usr/bin/env python3
"""Generate spike.kicad_pcb for the 3dPCB-paper repo.

Produces a minimal but complete KiCad 9 / 10 PCB with three connector
footprints (1x4, 1x5, two 1x9 rows) representing the ESP32-C3 Supermini +
SCD41 + BH1750 spike circuit on a shared I2C bus.

Footprints are self-contained (no external library refs) so the file is
independent of the host KiCad's installed library set — important because
the nixpkgs `kicad` package in this repo's dev shell does not ship
`kicad-symbols` / `kicad-footprints` / `kicad-packages3d`.
"""
from __future__ import annotations

import uuid

# Board geometry (mm). Origin is upper-left page corner per KiCad convention.
ORIGIN_X = 100.0
ORIGIN_Y = 60.0
BOARD_W = 80.0
BOARD_H = 50.0

PITCH = 2.54  # 0.1" header pitch

# Footprint placements (top-left pad position of pin 1 on F.Cu).
# Each entry: ref, value, pin_count, pos_x, pos_y, net_map (pin_number -> net_name)
# Pins extend in +y direction; pin 1 at pos.

# Supermini left row (9 pins, top to bottom: 5V, GND, 3V3, GPIO4, GPIO3,
# GPIO2, GPIO1, GPIO0, NC). The Supermini physically has 8 pins per row,
# but the README says "2 x 1x9 castellated (or female header rows)" so we
# follow the README and use 9-pin rows.
J1A_PINS = {
    1: "+5V",    # unused
    2: "GND",
    3: "+3V3",
    4: "GPIO4",  # not used by the bus
    5: "GPIO3",
    6: "GPIO2",
    7: "GPIO1",
    8: "GPIO0",
    9: "NC",
}

# Supermini right row (9 pins, top to bottom): GPIO5=SDA, GPIO6=SCL,
# GPIO7, GPIO8, GPIO9, GPIO10, GPIO20, GPIO21, NC.
J1B_PINS = {
    1: "SDA",   # GPIO5
    2: "SCL",   # GPIO6
    3: "GPIO7",
    4: "GPIO8",
    5: "GPIO9",
    6: "GPIO10",
    7: "GPIO20",
    8: "GPIO21",
    9: "NC2",
}

# SCD41 breakout 1x4 — Adafruit STEMMA QT 5190 pin order: VCC, GND, SCL, SDA.
J2_PINS = {
    1: "+3V3",
    2: "GND",
    3: "SCL",
    4: "SDA",
}

# BH1750 GY-302 1x5: VCC, GND, SCL, SDA, ADDR.
J3_PINS = {
    1: "+3V3",
    2: "GND",
    3: "SCL",
    4: "SDA",
    5: "ADDR",
}

# Positions (top of pin 1) for each footprint.
J1A_X, J1A_Y = ORIGIN_X + 10.0, ORIGIN_Y + 8.0
J1B_X, J1B_Y = J1A_X + 17.78, J1A_Y  # 7 * 2.54 = 17.78mm between Supermini rows
J2_X,  J2_Y  = ORIGIN_X + 45.0, ORIGIN_Y + 8.0
J3_X,  J3_Y  = ORIGIN_X + 60.0, ORIGIN_Y + 8.0

# Collect unique nets. Net 0 must be "". GND, +3V3, SDA, SCL are the
# routed nets; everything else (GPIOn, +5V, NC, NC2, ADDR) ends up on
# its own no-connect net.
ALL_PIN_NETS = set()
for d in (J1A_PINS, J1B_PINS, J2_PINS, J3_PINS):
    ALL_PIN_NETS.update(d.values())

# Order: "" first, then GND, +3V3, SDA, SCL, then the rest alphabetically.
ORDERED_NETS = ["", "GND", "+3V3", "SDA", "SCL"]
ORDERED_NETS += sorted(n for n in ALL_PIN_NETS if n not in ORDERED_NETS)
NET_INDEX = {n: i for i, n in enumerate(ORDERED_NETS)}


def u() -> str:
    return str(uuid.uuid4())


def header() -> str:
    return """(kicad_pcb
\t(version 20241229)
\t(generator "pcbnew")
\t(generator_version "9.0")
\t(general
\t\t(thickness 1.6)
\t\t(legacy_teardrops no)
\t)
\t(paper "A4")
\t(title_block
\t\t(title "3dPCB-paper spike")
\t\t(date "2026-05-12")
\t\t(rev "0.1")
\t\t(company "ncrmro")
\t\t(comment 1 "ESP32-C3 Supermini + SCD41 + BH1750 I2C spike")
\t)
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(9 "F.Adhes" user "F.Adhesive")
\t\t(11 "B.Adhes" user "B.Adhesive")
\t\t(13 "F.Paste" user)
\t\t(15 "B.Paste" user)
\t\t(5 "F.SilkS" user "F.Silkscreen")
\t\t(7 "B.SilkS" user "B.Silkscreen")
\t\t(1 "F.Mask" user)
\t\t(3 "B.Mask" user)
\t\t(17 "Dwgs.User" user "User.Drawings")
\t\t(19 "Cmts.User" user "User.Comments")
\t\t(21 "Eco1.User" user "User.Eco1")
\t\t(23 "Eco2.User" user "User.Eco2")
\t\t(25 "Edge.Cuts" user)
\t\t(27 "Margin" user)
\t\t(31 "F.CrtYd" user "F.Courtyard")
\t\t(29 "B.CrtYd" user "B.Courtyard")
\t\t(35 "F.Fab" user)
\t\t(33 "B.Fab" user)
\t)
\t(setup
\t\t(pad_to_mask_clearance 0.2)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(tenting front back)
\t\t(pcbplotparams
\t\t\t(layerselection 0x00000000_00000000_55555555_555555f5)
\t\t\t(plot_on_all_layers_selection 0x00000000_00000000_00000000_00000000)
\t\t\t(disableapertmacros no)
\t\t\t(usegerberextensions no)
\t\t\t(usegerberattributes yes)
\t\t\t(usegerberadvancedattributes yes)
\t\t\t(creategerberjobfile yes)
\t\t\t(dashed_line_dash_ratio 12.000000)
\t\t\t(dashed_line_gap_ratio 3.000000)
\t\t\t(svgprecision 4)
\t\t\t(plotframeref no)
\t\t\t(mode 1)
\t\t\t(useauxorigin no)
\t\t\t(hpglpennumber 1)
\t\t\t(hpglpenspeed 20)
\t\t\t(hpglpendiameter 15.000000)
\t\t\t(pdf_front_fp_property_popups yes)
\t\t\t(pdf_back_fp_property_popups yes)
\t\t\t(pdf_metadata yes)
\t\t\t(pdf_single_document no)
\t\t\t(dxfpolygonmode yes)
\t\t\t(dxfimperialunits yes)
\t\t\t(dxfusepcbnewfont yes)
\t\t\t(psnegative no)
\t\t\t(psa4output no)
\t\t\t(plot_black_and_white yes)
\t\t\t(plotinvisibletext no)
\t\t\t(sketchpadsonfab no)
\t\t\t(plotpadnumbers no)
\t\t\t(hidednponfab no)
\t\t\t(sketchdnponfab yes)
\t\t\t(crossoutdnponfab yes)
\t\t\t(subtractmaskfromsilk no)
\t\t\t(outputformat 1)
\t\t\t(mirror no)
\t\t\t(drillshape 1)
\t\t\t(scaleselection 1)
\t\t\t(outputdirectory "")
\t\t)
\t)
"""


def nets_block() -> str:
    out = []
    for i, n in enumerate(ORDERED_NETS):
        out.append(f'\t(net {i} "{n}")')
    return "\n".join(out) + "\n"


def edge_cuts() -> str:
    """Rectangular board outline as four gr_line segments on Edge.Cuts."""
    x0, y0 = ORIGIN_X, ORIGIN_Y
    x1, y1 = ORIGIN_X + BOARD_W, ORIGIN_Y + BOARD_H
    lines = [
        (x0, y0, x1, y0),
        (x1, y0, x1, y1),
        (x1, y1, x0, y1),
        (x0, y1, x0, y0),
    ]
    out = []
    for (sx, sy, ex, ey) in lines:
        out.append(
            f'\t(gr_line\n'
            f'\t\t(start {sx} {sy})\n'
            f'\t\t(end {ex} {ey})\n'
            f'\t\t(stroke (width 0.15) (type solid))\n'
            f'\t\t(layer "Edge.Cuts")\n'
            f'\t\t(uuid "{u()}")\n'
            f'\t)'
        )
    return "\n".join(out) + "\n"


def footprint(ref: str, value: str, x: float, y: float, pin_net_map: dict[int, str], description: str) -> str:
    """A through-hole pin header footprint.

    Pads are 2.54mm pitch in +y, 1.7mm drill, 1.7mm × 2.4mm oblong on
    *.Cu and *.Mask. Pin 1 is rectangular (square) to mark orientation,
    all others are oval.
    """
    fp_uuid = u()
    pin_count = len(pin_net_map)
    # Silkscreen rectangle around pads, 1.27mm margin.
    margin = 1.27
    silk_x0 = -margin
    silk_y0 = -margin
    silk_x1 = margin
    silk_y1 = (pin_count - 1) * PITCH + margin
    # Courtyard slightly larger.
    crtyd = 0.25
    crt_x0 = silk_x0 - crtyd
    crt_y0 = silk_y0 - crtyd
    crt_x1 = silk_x1 + crtyd
    crt_y1 = silk_y1 + crtyd

    pads = []
    for pin_num in range(1, pin_count + 1):
        py = (pin_num - 1) * PITCH
        shape = "rect" if pin_num == 1 else "oval"
        net_name = pin_net_map[pin_num]
        net_idx = NET_INDEX[net_name]
        # Per-footprint synthesized net label for nets we don't route
        # (single-pad nets get an "unconnected-(REF-PadN)" label-ish name
        # in real KiCad; we just reuse the net_name).
        pads.append(
            f'\t\t(pad "{pin_num}" thru_hole {shape}\n'
            f'\t\t\t(at 0 {py})\n'
            f'\t\t\t(size 1.7 1.7)\n'
            f'\t\t\t(drill 1.0)\n'
            f'\t\t\t(layers "*.Cu" "*.Mask")\n'
            f'\t\t\t(remove_unused_layers no)\n'
            f'\t\t\t(net {net_idx} "{net_name}")\n'
            f'\t\t\t(uuid "{u()}")\n'
            f'\t\t)'
        )
    pads_str = "\n".join(pads)

    silk = (
        f'\t\t(fp_line (start {silk_x0} {silk_y0}) (end {silk_x1} {silk_y0})\n'
        f'\t\t\t(stroke (width 0.12) (type solid)) (layer "F.SilkS") (uuid "{u()}"))\n'
        f'\t\t(fp_line (start {silk_x1} {silk_y0}) (end {silk_x1} {silk_y1})\n'
        f'\t\t\t(stroke (width 0.12) (type solid)) (layer "F.SilkS") (uuid "{u()}"))\n'
        f'\t\t(fp_line (start {silk_x1} {silk_y1}) (end {silk_x0} {silk_y1})\n'
        f'\t\t\t(stroke (width 0.12) (type solid)) (layer "F.SilkS") (uuid "{u()}"))\n'
        f'\t\t(fp_line (start {silk_x0} {silk_y1}) (end {silk_x0} {silk_y0})\n'
        f'\t\t\t(stroke (width 0.12) (type solid)) (layer "F.SilkS") (uuid "{u()}"))\n'
        # Pin 1 marker triangle on silk, just outside pad 1.
        f'\t\t(fp_line (start {silk_x0 - 0.6} {-0.3}) (end {silk_x0 - 0.6} {0.3})\n'
        f'\t\t\t(stroke (width 0.2) (type solid)) (layer "F.SilkS") (uuid "{u()}"))'
    )

    crtyd_block = (
        f'\t\t(fp_line (start {crt_x0} {crt_y0}) (end {crt_x1} {crt_y0})\n'
        f'\t\t\t(stroke (width 0.05) (type solid)) (layer "F.CrtYd") (uuid "{u()}"))\n'
        f'\t\t(fp_line (start {crt_x1} {crt_y0}) (end {crt_x1} {crt_y1})\n'
        f'\t\t\t(stroke (width 0.05) (type solid)) (layer "F.CrtYd") (uuid "{u()}"))\n'
        f'\t\t(fp_line (start {crt_x1} {crt_y1}) (end {crt_x0} {crt_y1})\n'
        f'\t\t\t(stroke (width 0.05) (type solid)) (layer "F.CrtYd") (uuid "{u()}"))\n'
        f'\t\t(fp_line (start {crt_x0} {crt_y1}) (end {crt_x0} {crt_y0})\n'
        f'\t\t\t(stroke (width 0.05) (type solid)) (layer "F.CrtYd") (uuid "{u()}"))'
    )

    return f"""\t(footprint "spike:PinHeader_1x{pin_count:02d}"
\t\t(layer "F.Cu")
\t\t(uuid "{fp_uuid}")
\t\t(at {x} {y})
\t\t(descr "{description}")
\t\t(tags "pin header through-hole")
\t\t(property "Reference" "{ref}"
\t\t\t(at 0 -2.5 0)
\t\t\t(layer "F.SilkS")
\t\t\t(uuid "{u()}")
\t\t\t(effects (font (size 1 1) (thickness 0.15)))
\t\t)
\t\t(property "Value" "{value}"
\t\t\t(at 0 {silk_y1 + 1.5} 0)
\t\t\t(layer "F.Fab")
\t\t\t(uuid "{u()}")
\t\t\t(effects (font (size 1 1) (thickness 0.15)))
\t\t)
\t\t(property "Footprint" ""
\t\t\t(at 0 0 0) (unlocked yes) (layer "F.Fab") (hide yes)
\t\t\t(uuid "{u()}")
\t\t\t(effects (font (size 1.27 1.27) (thickness 0.15)))
\t\t)
\t\t(property "Datasheet" ""
\t\t\t(at 0 0 0) (unlocked yes) (layer "F.Fab") (hide yes)
\t\t\t(uuid "{u()}")
\t\t\t(effects (font (size 1.27 1.27) (thickness 0.15)))
\t\t)
\t\t(property "Description" "{description}"
\t\t\t(at 0 0 0) (unlocked yes) (layer "F.Fab") (hide yes)
\t\t\t(uuid "{u()}")
\t\t\t(effects (font (size 1.27 1.27) (thickness 0.15)))
\t\t)
\t\t(attr through_hole)
{silk}
{crtyd_block}
\t\t(fp_text user "${{REFERENCE}}"
\t\t\t(at 0 {silk_y1 + 2.5} 0)
\t\t\t(layer "F.Fab")
\t\t\t(uuid "{u()}")
\t\t\t(effects (font (size 1 1) (thickness 0.15)))
\t\t)
{pads_str}
\t\t(embedded_fonts no)
\t)
"""


def segment(x1: float, y1: float, x2: float, y2: float, net_name: str, layer: str = "F.Cu", width: float = 0.4) -> str:
    return (
        f'\t(segment\n'
        f'\t\t(start {x1} {y1})\n'
        f'\t\t(end {x2} {y2})\n'
        f'\t\t(width {width})\n'
        f'\t\t(layer "{layer}")\n'
        f'\t\t(net {NET_INDEX[net_name]})\n'
        f'\t\t(uuid "{u()}")\n'
        f'\t)\n'
    )


def via(x: float, y: float, net_name: str) -> str:
    return (
        f'\t(via\n'
        f'\t\t(at {x} {y})\n'
        f'\t\t(size 0.8)\n'
        f'\t\t(drill 0.4)\n'
        f'\t\t(layers "F.Cu" "B.Cu")\n'
        f'\t\t(net {NET_INDEX[net_name]})\n'
        f'\t\t(uuid "{u()}")\n'
        f'\t)\n'
    )


def find_pad(fp_x: float, fp_y: float, pin_map: dict[int, str], target_net: str) -> tuple[float, float] | None:
    """Return absolute (x, y) for the first pad on fp wired to target_net."""
    for pin_num, net in pin_map.items():
        if net == target_net:
            return (fp_x, fp_y + (pin_num - 1) * PITCH)
    return None


def main() -> str:
    out = [header()]
    out.append(nets_block())

    # Edge cuts.
    out.append(edge_cuts())

    # Three footprints: J1A (left Supermini row), J1B (right Supermini row),
    # J2 (SCD41), J3 (BH1750). The Supermini is one physical module split
    # across two female headers, so we use two refs J1A/J1B for clarity.
    out.append(footprint("J1A", "ESP32-C3-SuperMini-L", J1A_X, J1A_Y, J1A_PINS,
                         "ESP32-C3 Supermini left header row 1x9 female"))
    out.append(footprint("J1B", "ESP32-C3-SuperMini-R", J1B_X, J1B_Y, J1B_PINS,
                         "ESP32-C3 Supermini right header row 1x9 female"))
    out.append(footprint("J2", "SCD41_Breakout", J2_X, J2_Y, J2_PINS,
                         "Sensirion SCD41 breakout 1x4 female header"))
    out.append(footprint("J3", "BH1750_GY302", J3_X, J3_Y, J3_PINS,
                         "Rohm BH1750 GY-302 breakout 1x5 female header"))

    # Route the four I2C-bus nets between the four headers.
    # For SDA: J1B pin 1 -> J2 pin 4 -> J3 pin 4 (all on F.Cu).
    # For SCL: J1B pin 2 -> J2 pin 3 -> J3 pin 3.
    # For +3V3: J1A pin 3 -> J2 pin 1 -> J3 pin 1.
    # For GND: J1A pin 2 -> J2 pin 2 -> J3 pin 2.
    # Use simple L-shaped (orthogonal) traces.
    def route(start, end, net_name, layer="F.Cu"):
        """Route start -> mid (right angle) -> end."""
        sx, sy = start
        ex, ey = end
        # Single bend: go horizontally first, then vertically.
        mx, my = ex, sy
        out.append(segment(sx, sy, mx, my, net_name, layer=layer))
        out.append(segment(mx, my, ex, ey, net_name, layer=layer))

    # SDA route on F.Cu
    j1b_sda = find_pad(J1B_X, J1B_Y, J1B_PINS, "SDA")
    j2_sda  = find_pad(J2_X,  J2_Y,  J2_PINS,  "SDA")
    j3_sda  = find_pad(J3_X,  J3_Y,  J3_PINS,  "SDA")
    route(j1b_sda, j2_sda, "SDA")
    route(j2_sda,  j3_sda, "SDA")

    # SCL route on F.Cu
    j1b_scl = find_pad(J1B_X, J1B_Y, J1B_PINS, "SCL")
    j2_scl  = find_pad(J2_X,  J2_Y,  J2_PINS,  "SCL")
    j3_scl  = find_pad(J3_X,  J3_Y,  J3_PINS,  "SCL")
    route(j1b_scl, j2_scl, "SCL")
    route(j2_scl,  j3_scl, "SCL")

    # +3V3 route on B.Cu (use bottom layer to avoid SDA/SCL crossings)
    j1a_3v3 = find_pad(J1A_X, J1A_Y, J1A_PINS, "+3V3")
    j2_3v3  = find_pad(J2_X,  J2_Y,  J2_PINS,  "+3V3")
    j3_3v3  = find_pad(J3_X,  J3_Y,  J3_PINS,  "+3V3")
    route(j1a_3v3, j2_3v3, "+3V3", layer="B.Cu")
    route(j2_3v3,  j3_3v3, "+3V3", layer="B.Cu")

    # GND route on B.Cu
    j1a_gnd = find_pad(J1A_X, J1A_Y, J1A_PINS, "GND")
    j2_gnd  = find_pad(J2_X,  J2_Y,  J2_PINS,  "GND")
    j3_gnd  = find_pad(J3_X,  J3_Y,  J3_PINS,  "GND")
    route(j1a_gnd, j2_gnd, "GND", layer="B.Cu")
    route(j2_gnd,  j3_gnd, "GND", layer="B.Cu")

    out.append(")\n")
    return "".join(out)


if __name__ == "__main__":
    import sys
    sys.stdout.write(main())
