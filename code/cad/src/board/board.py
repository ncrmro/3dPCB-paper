"""Board — top-level user-facing object.

A Board is what a YAML file declares: a base plate plus a list of placed
devices wired together by one or more buses. `bind_devices()` resolves
device-instance positions into absolute substrate coordinates; the bus
resolver then turns each Bus into one or more Nets that the router and
builder consume.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from board.buses import BoundDevice, Bus, Net, resolve_bus
from board.devices import DEVICE_REGISTRY, Device, Microcontroller, Rect
from board.mounts import Header
from board.pins import Point2D


class Level(BaseModel):
    """One axis-aligned Z-band slab.

    `perimeter` is the slab's xy footprint and `z_start < z_end` is its
    vertical extent. v1 only supports rectangular perimeters; the
    builder raises if a future schema slips in a non-Rect.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    perimeter: Rect
    z_start: float
    z_end: float

    @model_validator(mode="after")
    def _z_ascending(self) -> Level:
        if self.z_end <= self.z_start:
            raise ValueError(
                f"Level {self.name!r}: z_end ({self.z_end}) must be > "
                f"z_start ({self.z_start})"
            )
        return self

    @property
    def thickness(self) -> float:
        return self.z_end - self.z_start


class DimOverrides(BaseModel):
    """Overrides for the small fixed-dimension knobs the builder needs.

    Anything left at None falls back to a built-in default in
    `build.py::resolve_dims()`. Keep this list minimal — every entry
    here is a dial the user can spin from YAML, which means every entry
    has to make sense to a user staring at a board they want to print.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_width: float | None = None
    channel_depth: float | None = None
    via_diameter: float | None = None
    hole_diameter: float | None = None
    pocket_clearance: float | None = None
    overcut: float | None = None
    buffer: float | None = None  # universal min clearance; derives the rest
    edge_clearance: float | None = None
    pitch: float | None = None  # breadboard module (2.54 mm)
    pitch_subdivisions: float | None = None  # routing cells per pitch; res = pitch / this
    # Which autorouter to use. None falls back to the global default in
    # resolve_dims (voxel). The lattice engine routes on-pitch by construction.
    router_engine: Literal["voxel", "lattice"] | None = None

    def applied(self) -> dict[str, float]:
        # Only the numeric dimension knobs feed ResolvedDims' float fields;
        # router_engine is threaded separately (it isn't a dimension).
        return {
            k: v for k, v in self.model_dump().items()
            if v is not None and k != "router_engine"
        }


class DeviceInstance(BaseModel):
    """One placed device on the board."""

    model_config = ConfigDict(frozen=True)

    name: str                                       # local id used by buses (`u1`, `scd41`)
    device: str                                     # key in DEVICE_REGISTRY
    position: Point2D
    rotation: Literal[0, 90, 180, 270] = 0
    header: Header | None = None

    @field_validator("device")
    @classmethod
    def _device_known(cls, value: str) -> str:
        if value not in DEVICE_REGISTRY:
            known = ", ".join(sorted(DEVICE_REGISTRY)) or "<empty>"
            raise ValueError(
                f"device {value!r} not in DEVICE_REGISTRY (known: {known})"
            )
        return value

    @field_validator("position", mode="before")
    @classmethod
    def _coerce_position(cls, value: Any) -> Any:
        # Allow the YAML-friendly {x, y} dict form (Pydantic handles this
        # automatically), AND a 2-element list [x, y].
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return {"x": value[0], "y": value[1]}
        return value

    def resolved_device(self) -> Device:
        return DEVICE_REGISTRY[self.device]


class Board(BaseModel):
    """Top-level board declaration."""

    model_config = ConfigDict(frozen=True)

    name: str
    levels: tuple[Level, ...] = Field(min_length=1)
    devices: tuple[DeviceInstance, ...] = Field(min_length=1)
    buses: tuple[Bus, ...] = ()
    dim: DimOverrides = Field(default_factory=DimOverrides)

    @model_validator(mode="after")
    def _unique_device_names(self) -> Board:
        names = [d.name for d in self.devices]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(
                f"DeviceInstance.name must be unique on a Board; "
                f"duplicates: {sorted(dupes)}"
            )
        return self

    @model_validator(mode="after")
    def _snap_devices_to_pitch(self) -> Board:
        """Snap each device so its pin lattice lands on the breadboard grid.

        The pins within a device already sit on a `pitch` (2.54 mm) grid, so
        we shift the whole device as a GROUP by the residual between its
        first pin and the board grid — aligning every pin to the breadboard
        grid. (Rounding the reference point instead would leave the pins
        off-grid, since the reference point isn't itself a pin.) On by
        default; a board sets `dim.pitch` to change the module.
        """
        pitch = self.dim.pitch or 2.54
        snapped = []
        changed = False
        for d in self.devices:
            device = d.resolved_device()
            if not device.pins:
                snapped.append(d)
                continue
            ref = device.pin_position_at(d.position, d.rotation, device.pins[0])
            dx = round(ref.x / pitch) * pitch - ref.x
            dy = round(ref.y / pitch) * pitch - ref.y
            if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                changed = True
                d = d.model_copy(update={"position": Point2D(
                    x=round(d.position.x + dx, 4),
                    y=round(d.position.y + dy, 4),
                )})
            snapped.append(d)
        if changed:
            object.__setattr__(self, "devices", tuple(snapped))
        return self

    @model_validator(mode="after")
    def _snap_perimeter_to_pitch(self) -> Board:
        """Grow the base plate outward to the enclosing pitch rectangle.

        The routing-grid origin is the base perimeter's min corner, so for
        pins (already on pitch) to map to exact lattice nodes the perimeter
        edges must themselves be pitch multiples. Growing — never shrinking —
        keeps every device inside, never clips routable area, and only widens
        edge clearance (it grows away from the parts). Idempotent once the
        perimeter is on pitch.
        """
        pitch = self.dim.pitch or 2.54
        base = self.levels[0]
        p = base.perimeter
        x_min = math.floor(p.x_min / pitch) * pitch
        x_max = math.ceil(p.x_max / pitch) * pitch
        y_min = math.floor(p.y_min / pitch) * pitch
        y_max = math.ceil(p.y_max / pitch) * pitch
        if (abs(x_min - p.x_min) < 1e-9 and abs(x_max - p.x_max) < 1e-9
                and abs(y_min - p.y_min) < 1e-9 and abs(y_max - p.y_max) < 1e-9):
            return self
        grown = base.model_copy(update={"perimeter": Rect(
            cx=round((x_min + x_max) / 2, 6),
            cy=round((y_min + y_max) / 2, 6),
            w=round(x_max - x_min, 6),
            h=round(y_max - y_min, 6),
        )})
        object.__setattr__(self, "levels", (grown, *self.levels[1:]))
        return self

    @model_validator(mode="after")
    def _buses_reference_known_devices(self) -> Board:
        instance_names = {d.name for d in self.devices}
        for bus in self.buses:
            missing = []
            if bus.master not in instance_names:
                missing.append(f"master {bus.master!r}")
            for s in bus.slaves:
                if s not in instance_names:
                    missing.append(f"slave {s!r}")
            if missing:
                known = ", ".join(sorted(instance_names))
                raise ValueError(
                    f"Bus {bus.name!r} references unknown devices: "
                    f"{', '.join(missing)} (known: {known})"
                )
            master_device = DEVICE_REGISTRY[
                next(d.device for d in self.devices if d.name == bus.master)
            ]
            if not isinstance(master_device, Microcontroller):
                raise ValueError(
                    f"Bus {bus.name!r}: master {bus.master!r} resolves to "
                    f"device {master_device.name!r} which is a "
                    f"{type(master_device).__name__}, not a Microcontroller"
                )
        return self

    # -----------------------------------------------------------------
    # Resolution helpers — consumed by the router + the build pipeline.
    # -----------------------------------------------------------------

    def bound_devices(self) -> dict[str, BoundDevice]:
        """Map instance-name → BoundDevice (= device + absolute position)."""
        return {
            d.name: BoundDevice(
                instance_name=d.name,
                device=d.resolved_device(),
                position=d.position,
                rotation_deg=d.rotation,
            )
            for d in self.devices
        }

    def nets(self) -> tuple[Net, ...]:
        """Resolve every Bus into Nets (one per bus signal)."""
        bound = self.bound_devices()
        all_nets: list[Net] = []
        for bus in self.buses:
            all_nets.extend(resolve_bus(bus, bound))
        return tuple(all_nets)

    def bus_endpoint_xys(self) -> set[tuple[float, float]]:
        """Set of `(round(x, 3), round(y, 3))` keys for every pin that
        any bus actually wires up. Used by the builder + reports to
        skip drilling holes for unconnected device pins (e.g. the
        20+ unused ESP32-C3 SuperMini GPIO pins) — drilling them adds
        print time and weakens the substrate for no functional gain.
        """
        return {
            (round(ep.position.x, 3), round(ep.position.y, 3))
            for net in self.nets()
            for ep in net.endpoints
        }
