"""ESP32-C3 SuperMini pin-net assignments.

Lives as a sibling of `esp32.py` (the geometry) so the KiCad flake's
Python can import the PINOUTs without pulling in anchorscad. The
geometry classes in `esp32.py` re-export these for convenience, but
the canonical source is here.
"""

from netlist import I2cSignal, Pin


# ESP32-C3 SuperMini left column (J1A) — 9 pins, pin 1 at the top
# of the silkscreen pin row. Source: SuperMini README + audit doc.
J1A_PINOUT: dict[int, Pin] = {
    1: Pin("J1A", 1, function="+5V"),
    2: Pin("J1A", 2, signal=I2cSignal.GND),
    3: Pin("J1A", 3, signal=I2cSignal.VCC),
    4: Pin("J1A", 4, function="GPIO4"),
    5: Pin("J1A", 5, function="GPIO3"),
    6: Pin("J1A", 6, function="GPIO2"),
    7: Pin("J1A", 7, function="GPIO1"),
    8: Pin("J1A", 8, function="GPIO0"),
    9: Pin("J1A", 9, function="NC"),
}

# ESP32-C3 SuperMini right column (J1B) — 9 pins. SDA = GPIO5,
# SCL = GPIO6 (the I2C bus on this MCU).
J1B_PINOUT: dict[int, Pin] = {
    1: Pin("J1B", 1, signal=I2cSignal.SDA, function="GPIO5"),
    2: Pin("J1B", 2, signal=I2cSignal.SCL, function="GPIO6"),
    3: Pin("J1B", 3, function="GPIO7"),
    4: Pin("J1B", 4, function="GPIO8"),
    5: Pin("J1B", 5, function="GPIO9"),
    6: Pin("J1B", 6, function="GPIO10"),
    7: Pin("J1B", 7, function="GPIO20"),
    8: Pin("J1B", 8, function="GPIO21"),
    9: Pin("J1B", 9, function="NC2"),
}
