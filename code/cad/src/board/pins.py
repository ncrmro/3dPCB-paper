"""Pin primitives.

A `Pin` is one electrical contact on a `Device`, with a fixed position
in the device's local frame (origin = device reference point). The pin's
`role` is the matching key buses use to wire devices together — an I2C
bus looks for `role="SCL"` on each participant; a UART bus looks for
`role="TX"` on the master and `role="RX"` on the slave (and vice versa).

`PinGroup` is metadata: which standard signal family this pin belongs to.
Buses don't dispatch on it directly, but it's a useful filter (e.g. "show
me every I2C pin on this device") and a sanity check ("this pin is in the
GPIO group but a bus tried to wire it as SCL").
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class PinGroup(str, Enum):
    """Signal-family classification for a pin.

    Inheriting from `str` keeps the YAML round-trip painless — the
    enum value serialises as its string member.
    """

    POWER_5V = "5V"
    POWER_3V3 = "3V3"
    GND = "GND"
    I2C = "I2C"
    UART = "UART"
    SPI = "SPI"
    GPIO = "GPIO"
    NC = "NC"  # not connected / no function — placeholder


class Point2D(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float
    y: float


class Pin(BaseModel):
    """One electrical contact in the device's local frame.

    `role` is the bus-side identifier (case-insensitive on lookup).
    Standard roles per bus kind:

      i2c  → "VCC", "GND", "SCL", "SDA"
      uart → "VCC", "GND", "TX",  "RX"
      spi  → "VCC", "GND", "SCK", "MOSI", "MISO", "CS"

    A pin not used by any bus may carry any role string ("GPIO5",
    "ADDR", "NC", "5V_IN"); those pins are simply not matched when a
    bus is resolved.
    """

    model_config = ConfigDict(frozen=True)

    index: int          # 1-based pin number within the device's header
    role: str           # bus-side identifier; see docstring
    group: PinGroup
    position: Point2D   # device-local (x, y), origin = device reference point
