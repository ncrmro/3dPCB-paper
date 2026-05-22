"""Sensor breakout pin-net assignments.

Lives as a sibling of `sensors.py` (the geometry) so the KiCad
flake's Python can import the PINOUTs without pulling in anchorscad.
"""

from netlist import I2cSignal, Pin


# SCD41 breakout (Adafruit STEMMA QT 5190) — 4-pin header J2,
# silkscreen "GND VCC SCL SDA" L→R from pin 1 on the physical
# board in hand (2026-05-19 inspection — supersedes the earlier
# "VCC GND" assumption from the product page diagram, which lists
# the rails in the OTHER orientation).
# Source: physical inspection + audit doc.
SCD41_PINOUT: dict[int, Pin] = {
    1: Pin("J2", 1, signal=I2cSignal.GND),
    2: Pin("J2", 2, signal=I2cSignal.VCC),
    3: Pin("J2", 3, signal=I2cSignal.SCL),
    4: Pin("J2", 4, signal=I2cSignal.SDA),
}

# BH1750 GY-302 breakout — 5-pin header J3.
#
# ⚠ The usini KiCad footprint numbers its pads OPPOSITE to silkscreen
# reading order. The silkscreen reads "VCC GND SCL SDA ADDR" L→R, but
# the footprint pads at positions (0, 0..-10.16) are numbered:
#   pad 1 → silkscreen ADDR
#   pad 2 → silkscreen SDA
#   pad 3 → silkscreen SCL
#   pad 4 → silkscreen GND
#   pad 5 → silkscreen VCC
# (Confirmed by inspection of
# data/models/bh1750_breakout/module_bh1750.kicad_mod.)
#
# The PINOUT below follows the footprint's pad convention, NOT the
# silkscreen reading order, because the substrate's J3.n pin
# coordinates derive from footprint pad N. Getting this wrong (e.g.
# declaring J3.1 = VCC because the silkscreen says VCC first) silently
# wires every bus signal to the wrong physical pin.
BH1750_PINOUT: dict[int, Pin] = {
    1: Pin("J3", 1, signal=I2cSignal.ADDR),
    2: Pin("J3", 2, signal=I2cSignal.SDA),
    3: Pin("J3", 3, signal=I2cSignal.SCL),
    4: Pin("J3", 4, signal=I2cSignal.GND),
    5: Pin("J3", 5, signal=I2cSignal.VCC),
}
