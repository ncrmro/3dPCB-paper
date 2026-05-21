"""Hosyond 0.96" OLED I2C SSD1306 pin-net assignments.

Lives as a sibling of `oled_ssd1306.py` (geometry, follow-up commit)
so the KiCad flake's Python can import the PINOUT without pulling
anchorscad.

Pin numbering follows the substrate's J4 column (pin 1 at west,
pin 4 at east). The OLED is mounted silkscreen-up with its
silkscreen GND label on the WEST end, matching the Hosyond
silkscreen order "GND VCC SCL SDA" L→R:

    J4.1 = GND  (x = -3.81)
    J4.2 = VCC
    J4.3 = SCL
    J4.4 = SDA  (x = +3.81)

The Hosyond silkscreen reads "GND VCC SCL SDA" L→R when viewed from
the display front; mounting the module so its silkscreen reads the
same direction as the substrate's +X axis lands GND at the west
column. The netlist abstraction lands this without any code-side
adaptation — each `Net` finds the matching pin by signal lookup
across each participant's PINOUT, so a sensor with a different
physical pin order just declares it here.

Source: Hosyond product page (Amazon listing, 2026-05).
Audit: see `netlist_audit.md` — pending physical-board verification.
"""

from netlist import I2cSignal, Pin


# Hosyond SSD1306 128 × 64 OLED breakout — 4-pin header J4.
# Pin numbering follows substrate column order (west → east), with
# the OLED mounted silkscreen-up so the silkscreen reads "GND VCC
# SCL SDA" in the +X direction.
OLED_PINOUT: dict[int, Pin] = {
    1: Pin("J4", 1, signal=I2cSignal.GND),
    2: Pin("J4", 2, signal=I2cSignal.VCC),
    3: Pin("J4", 3, signal=I2cSignal.SCL),
    4: Pin("J4", 4, signal=I2cSignal.SDA),
}
