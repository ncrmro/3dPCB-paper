"""Sensor breakout pin-net assignments.

Lives as a sibling of `sensors.py` (the geometry) so the KiCad
flake's Python can import the PINOUTs without pulling in anchorscad.
"""

from netlist import I2cSignal, Pin


# SCD41 breakout (Adafruit STEMMA QT 5190) — 4-pin header J2,
# silkscreen "VCC GND SCL SDA" L→R from pin 1.
# Source: Adafruit product page + audit doc.
SCD41_PINOUT: dict[int, Pin] = {
    1: Pin("J2", 1, signal=I2cSignal.VCC),
    2: Pin("J2", 2, signal=I2cSignal.GND),
    3: Pin("J2", 3, signal=I2cSignal.SCL),
    4: Pin("J2", 4, signal=I2cSignal.SDA),
}

# BH1750 GY-302 breakout — 5-pin header J3, silkscreen
# "VCC GND SCL SDA ADDR" L→R from pin 1.
# Source: usini/usini_kicad_sensors footprint + audit doc.
BH1750_PINOUT: dict[int, Pin] = {
    1: Pin("J3", 1, signal=I2cSignal.VCC),
    2: Pin("J3", 2, signal=I2cSignal.GND),
    3: Pin("J3", 3, signal=I2cSignal.SCL),
    4: Pin("J3", 4, signal=I2cSignal.SDA),
    5: Pin("J3", 5, signal=I2cSignal.ADDR),
}
