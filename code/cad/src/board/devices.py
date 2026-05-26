"""Device primitives + registry.

A `Device` is a piece of off-the-shelf hardware (microcontroller, sensor
breakout, display) described by its physical footprint and its pin list.
Concrete devices are registered with `DEVICE_REGISTRY` at module import
time so the YAML can pick one by name.

Two subclasses encode bus role:

  - `Microcontroller` — can be a Bus master.
  - `Sensor`          — can only be a Bus slave.

Buses enforce this at resolve time: a `Bus` with `master=` referencing
a `Sensor` fails loudly rather than silently producing a half-wired net.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from board.pins import Pin, Point2D


class Rect(BaseModel):
    """Axis-aligned rectangle in some local frame.

    Reused for device footprints, level perimeters, and connector bodies.
    """

    model_config = ConfigDict(frozen=True)

    cx: float
    cy: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)

    @property
    def x_min(self) -> float:
        return self.cx - self.w / 2

    @property
    def x_max(self) -> float:
        return self.cx + self.w / 2

    @property
    def y_min(self) -> float:
        return self.cy - self.h / 2

    @property
    def y_max(self) -> float:
        return self.cy + self.h / 2

    def contains_xy(self, x: float, y: float, *, slack: float = 1e-6) -> bool:
        return (
            self.x_min - slack <= x <= self.x_max + slack
            and self.y_min - slack <= y <= self.y_max + slack
        )


class Device(BaseModel):
    """Description of one off-the-shelf hardware part.

    All positions are in the device-local frame, where (0, 0) is the
    device's reference point. The reference point is the device's
    *physical anchor* on the substrate:

      - Flat-mounted devices (ESP32, SCD41, BH1750) → PCB centre.
      - Header-mounted devices (OLED) → the header's pin-row centre,
        because that's what physically sits on the substrate. The
        device PCB itself cantilevers off the header.

    `pin1_position` documents which pin is the "first" one — used for
    orientation by the visualiser; the bus resolver doesn't care.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    footprint: Rect
    pcb_thickness: float = Field(gt=0)
    pins: tuple[Pin, ...]

    def pin_by_role(self, role: str) -> Pin | None:
        """Find the pin with this role (case-insensitive). Returns None
        if no match — buses use this to detect missing bus signals."""
        target = role.upper()
        matches = [p for p in self.pins if p.role.upper() == target]
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(
                f"Device {self.name!r}: {len(matches)} pins carry role "
                f"{role!r}; expected at most one"
            )
        return matches[0]

    def pin_position_at(
        self,
        instance_position: Point2D,
        rotation_deg: int,
        pin: Pin,
    ) -> Point2D:
        """Project this device's pin into substrate coordinates."""
        return _rotate_then_translate(
            pin.position, rotation_deg, instance_position
        )


class Microcontroller(Device):
    """Device that can act as a Bus master."""


class Sensor(Device):
    """Device that can only act as a Bus slave."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


DEVICE_REGISTRY: dict[str, Device] = {}


def register_device(device: Device) -> Device:
    """Register a device under its name. Idempotent on identical re-import
    (same name + same model dump), but rejects two different devices that
    share a name."""
    existing = DEVICE_REGISTRY.get(device.name)
    if existing is not None:
        if existing.model_dump() != device.model_dump():
            raise ValueError(
                f"Device name collision: {device.name!r} already registered "
                f"with different data"
            )
        return existing
    DEVICE_REGISTRY[device.name] = device
    return device


def get_device(name: str) -> Device:
    try:
        return DEVICE_REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(DEVICE_REGISTRY)) or "<empty>"
        raise KeyError(
            f"unknown device {name!r}; known: {known}"
        ) from exc


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _rotate_then_translate(
    p: Point2D, rotation_deg: int, origin: Point2D
) -> Point2D:
    """Rotate a device-local point around (0, 0) by `rotation_deg`, then
    translate by `origin`. Rotation is restricted to 90° increments — a
    Pydantic Literal on DeviceInstance enforces that upstream."""
    if rotation_deg == 0:
        rx, ry = p.x, p.y
    elif rotation_deg == 90:
        rx, ry = -p.y, p.x
    elif rotation_deg == 180:
        rx, ry = -p.x, -p.y
    elif rotation_deg == 270:
        rx, ry = p.y, -p.x
    else:
        raise ValueError(
            f"rotation_deg must be 0/90/180/270, got {rotation_deg}"
        )
    return Point2D(x=rx + origin.x, y=ry + origin.y)
