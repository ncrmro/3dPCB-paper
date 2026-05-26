"""Concrete device registrations.

Importing this module populates `DEVICE_REGISTRY` with every device the
Board YAML can reference. Each device's pinout is declared here in its
own block — the per-row helper `_row()` turns a list of `(role, group)`
tuples into `Pin` instances positioned along a header at the given pitch.

Pinout authority notes are kept inline next to each device so that
auditing "which silkscreen pin is which footprint pad" stays close to
the data, not buried in a separate file.
"""

from __future__ import annotations

from board.devices import (
    DEVICE_REGISTRY,
    Microcontroller,
    Rect,
    Sensor,
    register_device,
)
from board.pins import Pin, PinGroup, Point2D


_PITCH = 2.54  # standard 0.1" header pitch — every starter device


def _row(
    pinout: list[tuple[str, PinGroup]],
    *,
    x: float,
    y0: float,
    axis: str,
) -> list[Pin]:
    """Build a list of `Pin` instances laid out along `axis` from `(x, y0)`.

    Pins are 1-indexed and step at `_PITCH` mm. `axis="+x"` lays them
    rightward (positive X), `axis="+y"` lays them northward (positive Y).
    """
    pins: list[Pin] = []
    for i, (role, group) in enumerate(pinout, start=1):
        offset = (i - 1) * _PITCH
        if axis == "+x":
            pos = Point2D(x=x + offset, y=y0)
        elif axis == "+y":
            pos = Point2D(x=x, y=y0 + offset)
        else:
            raise ValueError(f"unsupported pin-row axis {axis!r}")
        pins.append(Pin(index=i, role=role, group=group, position=pos))
    return pins


# ---------------------------------------------------------------------------
# ESP32-C3 SuperMini
# ---------------------------------------------------------------------------
#
# Footprint: 18 mm wide × 22.5 mm long PCB. Two pin columns running +Y,
# 9 pins each at 2.54 mm pitch. Pin span 8 × 2.54 = 20.32 mm, centred
# on the PCB; columns sit 17.78 mm apart (= 7 × pitch), centred on the
# PCB. Device reference point = PCB centre. Pin 1 is at the USB-C end
# (substrate-south on the starter layout).
#
# SDA = GPIO5 on J1B.1, SCL = GPIO6 on J1B.2 — the I²C bus on this MCU.
# Source: SuperMini README + audit doc.

_ESP32_COL_X = 17.78 / 2
_ESP32_PIN_Y0 = -((9 - 1) * _PITCH) / 2

_ESP32_J1A: list[tuple[str, PinGroup]] = [
    ("5V",     PinGroup.POWER_5V),
    ("GND",    PinGroup.GND),
    ("VCC",    PinGroup.POWER_3V3),
    ("GPIO4",  PinGroup.GPIO),
    ("GPIO3",  PinGroup.GPIO),
    ("GPIO2",  PinGroup.GPIO),
    ("GPIO1",  PinGroup.GPIO),
    ("GPIO0",  PinGroup.GPIO),
    ("NC",     PinGroup.NC),
]
_ESP32_J1B: list[tuple[str, PinGroup]] = [
    ("SDA",    PinGroup.I2C),
    ("SCL",    PinGroup.I2C),
    ("GPIO7",  PinGroup.GPIO),
    ("GPIO8",  PinGroup.GPIO),
    ("GPIO9",  PinGroup.GPIO),
    ("GPIO10", PinGroup.GPIO),
    ("GPIO20", PinGroup.GPIO),
    ("GPIO21", PinGroup.GPIO),
    ("NC2",    PinGroup.NC),
]

register_device(Microcontroller(
    name="esp32_c3_supermini",
    footprint=Rect(cx=0, cy=0, w=18.0, h=22.5),
    pcb_thickness=1.5,
    pins=tuple(
        _row(_ESP32_J1A, x=-_ESP32_COL_X, y0=_ESP32_PIN_Y0, axis="+y")
        + _row(_ESP32_J1B, x=+_ESP32_COL_X, y0=_ESP32_PIN_Y0, axis="+y")
    ),
))


# ---------------------------------------------------------------------------
# SCD41 breakout (Adafruit STEMMA QT 5190)
# ---------------------------------------------------------------------------
#
# Footprint: 13.3 mm × 21.75 mm PCB. 4-pin header along one short edge.
# Silkscreen reads "GND VCC SCL SDA" L→R from pin 1 on the physical
# board (2026-05-19 inspection — supersedes the earlier "VCC GND"
# assumption from the product-page diagram, which lists the rails in
# the OTHER orientation). Pin row sits on the device's south edge.

_SCD41_PCB_W = 21.75
_SCD41_PCB_D = 13.3
_SCD41_PIN_Y = -_SCD41_PCB_W / 2 + _PITCH / 2

_SCD41_J2: list[tuple[str, PinGroup]] = [
    ("GND", PinGroup.GND),
    ("VCC", PinGroup.POWER_3V3),
    ("SCL", PinGroup.I2C),
    ("SDA", PinGroup.I2C),
]

register_device(Sensor(
    name="scd41",
    footprint=Rect(cx=0, cy=0, w=_SCD41_PCB_D, h=_SCD41_PCB_W),
    pcb_thickness=1.6,
    pins=tuple(_row(
        _SCD41_J2,
        x=-((len(_SCD41_J2) - 1) * _PITCH) / 2,
        y0=_SCD41_PIN_Y,
        axis="+x",
    )),
))


# ---------------------------------------------------------------------------
# BH1750 (GY-302) breakout
# ---------------------------------------------------------------------------
#
# Footprint: 14 mm × 18.5 mm PCB. 5-pin header along one short edge.
#
# ⚠ The KiCad footprint numbers its pads OPPOSITE to silkscreen reading
# order. The silkscreen reads "VCC GND SCL SDA ADDR" L→R, but the
# footprint pads at positions (0, 0..-10.16) are numbered:
#   pad 1 → silkscreen ADDR
#   pad 2 → silkscreen SDA
#   pad 3 → silkscreen SCL
#   pad 4 → silkscreen GND
#   pad 5 → silkscreen VCC
# We follow the footprint pad convention, NOT the silkscreen reading
# order — getting this wrong silently wires every bus signal to the
# wrong physical pin.

_BH1750_PCB_W = 18.5
_BH1750_PCB_D = 14.0
_BH1750_PIN_Y = -_BH1750_PCB_W / 2 + _PITCH / 2

_BH1750_J3: list[tuple[str, PinGroup]] = [
    ("ADDR", PinGroup.GPIO),    # per-sensor address-select, not on the bus
    ("SDA",  PinGroup.I2C),
    ("SCL",  PinGroup.I2C),
    ("GND",  PinGroup.GND),
    ("VCC",  PinGroup.POWER_3V3),
]

register_device(Sensor(
    name="bh1750",
    footprint=Rect(cx=0, cy=0, w=_BH1750_PCB_D, h=_BH1750_PCB_W),
    pcb_thickness=1.6,
    pins=tuple(_row(
        _BH1750_J3,
        x=-((len(_BH1750_J3) - 1) * _PITCH) / 2,
        y0=_BH1750_PIN_Y,
        axis="+x",
    )),
))


# ---------------------------------------------------------------------------
# Hosyond 0.96" SSD1306 OLED
# ---------------------------------------------------------------------------
#
# The OLED PCB cantilevers off a 4-pin female header. The device's
# reference point on the substrate is the header's pin-row centre, not
# the OLED PCB centre — what physically sits on the substrate is the
# pedestal under the header, while the OLED PCB extends past it.
#
# Hosyond silkscreen reads "GND VCC SCL SDA" L→R when viewed from the
# display front. Mounting with the silkscreen +X-aligned lands GND on
# the west column. Source: Hosyond Amazon product page (2026-05);
# audit pending physical-board verification.

_OLED_PCB_W = 27.0
_OLED_PCB_D = 28.0
_OLED_PIN_Y = 0.0
_OLED_PCB_CY = _OLED_PCB_D / 2 + _PITCH / 2

_OLED_J4: list[tuple[str, PinGroup]] = [
    ("GND", PinGroup.GND),
    ("VCC", PinGroup.POWER_3V3),
    ("SCL", PinGroup.I2C),
    ("SDA", PinGroup.I2C),
]

register_device(Sensor(
    name="oled_ssd1306",
    footprint=Rect(cx=0, cy=_OLED_PCB_CY, w=_OLED_PCB_W, h=_OLED_PCB_D),
    pcb_thickness=1.6,
    pins=tuple(_row(
        _OLED_J4,
        x=-((len(_OLED_J4) - 1) * _PITCH) / 2,
        y0=_OLED_PIN_Y,
        axis="+x",
    )),
))


# Sanity check: importing this module must leave the registry populated
# with exactly these four devices.
KNOWN_DEVICES = ("esp32_c3_supermini", "scd41", "bh1750", "oled_ssd1306")
assert set(KNOWN_DEVICES).issubset(set(DEVICE_REGISTRY)), (
    f"device_library import failed to register all known devices; "
    f"have {sorted(DEVICE_REGISTRY)}"
)
