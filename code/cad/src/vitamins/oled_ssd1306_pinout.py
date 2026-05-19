"""Hosyond 0.96" OLED I2C SSD1306 pin-net assignments.

Lives as a sibling of `oled_ssd1306.py` (geometry, follow-up commit)
so the KiCad flake's Python can import the PINOUT without pulling
anchorscad.

Pin order (looking DOWN at the display, header visible):
    GND, VCC, SCL, SDA

⚠ This is DIFFERENT from the BH1750 / SCD41 order (`VCC, GND, SCL,
SDA`). The netlist abstraction lands these without any code-side
adaptation — the `Net` for each `I2cSignal` finds the matching pin
by signal lookup across each participant's PINOUT, so a sensor
with a different physical pin order just declares it here.

Source: Hosyond product page (Amazon listing, 2026-05).
Audit: see `netlist_audit.md` — pending physical-board verification.
"""

from netlist import I2cSignal, Pin


# Hosyond SSD1306 128 × 64 OLED breakout — 4-pin header J4,
# silkscreen "GND VCC SCL SDA" L→R when viewed from the display side.
OLED_PINOUT: dict[int, Pin] = {
    1: Pin("J4", 1, signal=I2cSignal.GND),
    2: Pin("J4", 2, signal=I2cSignal.VCC),
    3: Pin("J4", 3, signal=I2cSignal.SCL),
    4: Pin("J4", 4, signal=I2cSignal.SDA),
}
