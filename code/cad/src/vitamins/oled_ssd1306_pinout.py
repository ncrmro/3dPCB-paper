"""Hosyond 0.96" OLED I2C SSD1306 pin-net assignments.

Lives as a sibling of `oled_ssd1306.py` (geometry, follow-up commit)
so the KiCad flake's Python can import the PINOUT without pulling
anchorscad.

Pin numbering follows the substrate's J4 column (pin 1 at west,
pin 4 at east). The OLED is mounted with its silkscreen GND label
on the EAST end so that SDA — the high-frequency I2C signal — sits
closest to the ESP32 master at the west:

    J4.1 = SDA  (x = -3.81, closest to ESP32)
    J4.2 = SCL
    J4.3 = VCC
    J4.4 = GND  (x = +3.81, farthest from ESP32)

The Hosyond silkscreen reads "GND VCC SCL SDA" L→R when viewed from
the display front. Mounting it with GND-east on the substrate
inverts the silkscreen reading order relative to the substrate's
+X axis. The netlist abstraction lands this without any code-side
adaptation — each `Net` finds the matching pin by signal lookup
across each participant's PINOUT, so a sensor with a different
physical pin order just declares it here.

Source: Hosyond product page (Amazon listing, 2026-05).
Audit: see `netlist_audit.md` — pending physical-board verification.
"""

from netlist import I2cSignal, Pin


# Hosyond SSD1306 128 × 64 OLED breakout — 4-pin header J4.
# Pin numbering follows substrate column order (west → east), with
# the OLED mounted silkscreen-reversed so SDA is closest to ESP32.
OLED_PINOUT: dict[int, Pin] = {
    1: Pin("J4", 1, signal=I2cSignal.SDA),
    2: Pin("J4", 2, signal=I2cSignal.SCL),
    3: Pin("J4", 3, signal=I2cSignal.VCC),
    4: Pin("J4", 4, signal=I2cSignal.GND),
}
