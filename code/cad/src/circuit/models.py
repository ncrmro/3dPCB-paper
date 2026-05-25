"""Pydantic v2 models for the declarative circuit spec.

A `CircuitSpec` carries:
- a `dim:` block of scalar overrides for `Tier1SubstrateDimensions`
  (nested per-device dataclasses use their own defaults — the YAML
  spec doesn't redescribe them)
- a tuple of `Level`s — each an axis-aligned `Rect` perimeter spanning
  z ∈ [z_start, z_end]
- a tuple of `Device`s — each owns some level indices and may carry
  pin holes referencing the netlist Pins
- a tuple of `Route`s — each is one I2C signal authored as a trunk
  waypoint list plus optional named branch waypoint lists

Validators reject geometry that the routing/voxel suite would later
fail on (off-board waypoints, out-of-range device levels, malformed
layer literals) so the failure surfaces at parse time.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from netlist import I2cSignal, Pin


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------


class Rect(BaseModel):
    """Axis-aligned 2D rectangle. (cx, cy) = centre, (w, h) = extent.

    v1 supports rectangles only. Arbitrary polygons need an OpenSCAD
    polygon() bridge through pythonopenscad — deferred (see
    HARDWARE_BLOCKERS.md). `build.py` raises NotImplementedError if a
    future spec carries a non-Rect perimeter.
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


# ---------------------------------------------------------------------------
# Stack levels
# ---------------------------------------------------------------------------


class Level(BaseModel):
    """One Z-band slab. The perimeter is the slab's xy footprint;
    z_start < z_end gives its vertical extent."""

    model_config = ConfigDict(frozen=True)

    name: str
    perimeter: Rect
    z_start: float
    z_end: float

    @model_validator(mode="after")
    def _z_ascending(self) -> "Level":
        if self.z_end <= self.z_start:
            raise ValueError(
                f"Level {self.name!r}: z_end ({self.z_end}) must be > "
                f"z_start ({self.z_start})"
            )
        return self


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


def _coerce_pin(value: Any) -> Pin:
    """Accept a Pin instance, a 'REF.NUMBER' string, or a dict
    `{ref, number, ...}` (the latter is what model_dump emits on
    round-trip — Pin is a frozen dataclass, so Pydantic serialises
    it as a mapping)."""
    if isinstance(value, Pin):
        return value
    if isinstance(value, dict):
        return Pin(
            ref=value["ref"],
            number=int(value["number"]),
            function=value.get("function") or "spec",
        )
    if isinstance(value, str) and "." in value:
        ref, number = value.split(".", 1)
        try:
            n = int(number)
        except ValueError as exc:
            raise ValueError(
                f"pin reference {value!r}: number after '.' must be int"
            ) from exc
        # Mark as a power/GPIO function placeholder so Pin's
        # post_init check (must have signal or function) passes.
        # The xy resolution path uses ref+number only.
        return Pin(ref=ref, number=n, function="spec")
    raise ValueError(
        f"pin reference must be a Pin or 'REF.NUMBER' string, got {value!r}"
    )


class Device(BaseModel):
    """A device sitting in the stack. `levels` lists the slab indices
    this device occupies (so a 1-level SMT part has one index, a
    pedestal-and-receptacle device may span two)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    levels: tuple[int, ...] = ()
    pocket: Rect | None = None
    pin_holes: tuple[Pin, ...] = ()
    contributes_polygon_to: tuple[int, ...] = ()

    @field_validator("pin_holes", mode="before")
    @classmethod
    def _coerce_pin_list(cls, value: Any) -> Any:
        if value is None:
            return ()
        if isinstance(value, (list, tuple)):
            return tuple(_coerce_pin(p) for p in value)
        return value


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class Waypoint(BaseModel):
    """A (xy, layer) checkpoint. YAML may carry the value either as
    a mapping `{x: -8, y: -23.6, layer: 1}` OR a 3-element list
    `[-8, -23.6, 1]` — both validate to the same object."""

    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    layer: Literal[1, 2]

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, value: Any) -> Any:
        # The 3-element list form is the YAML-friendly default.
        if isinstance(value, (list, tuple)) and not isinstance(value, str):
            if len(value) != 3:
                raise ValueError(
                    f"Waypoint list form must be [x, y, layer], got {value!r}"
                )
            return {"x": value[0], "y": value[1], "layer": value[2]}
        return value


class ViaSpec(BaseModel):
    """A standalone via to inject into a route's SignalPath elements.

    Vias appear separately from waypoint lists because some routes
    (e.g. SCL) have layer transitions that don't emit a path-level
    via — the via is drilled by `_punch_extra_holes` instead. Routes
    that DO want a path-level via (e.g. SDA's central column climb)
    list them here; they're inserted at `after_leg` (index into the
    `legs` list — the via appears immediately after that leg's last
    segment in the SignalPath element list)."""

    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    diameter: float = 1.5
    after_leg: int = 0

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)) and not isinstance(value, str):
            if len(value) == 3:
                return {"x": value[0], "y": value[1], "after_leg": value[2]}
            if len(value) == 4:
                return {
                    "x": value[0], "y": value[1],
                    "diameter": value[2], "after_leg": value[3],
                }
            raise ValueError(
                f"ViaSpec list form must be [x, y, after_leg] or "
                f"[x, y, diameter, after_leg]; got {value!r}"
            )
        return value


class Route(BaseModel):
    """One signal's path as a list of single-layer `legs`.

    Each leg is a waypoint list fed verbatim through
    `router.paths.waypoints_to_path`. The leg's waypoints SHOULD all
    sit on the same layer — a layer change inside a leg would auto-
    emit a Via, which is rarely what hand-coded substrates want.
    Layer changes between legs are silent (no via in the SignalPath)
    unless an explicit `ViaSpec` is listed in `vias` with the right
    `after_leg`.

    This shape is the right unit for forking topologies: two legs
    sharing a fork waypoint produce two segments meeting at that
    point, exactly mirroring the way `_build_oled_only_power_paths`
    forks a SCD41-east-leg off the corridor at the SCD41 column.
    """

    model_config = ConfigDict(frozen=True)

    signal: I2cSignal
    legs: tuple[tuple[Waypoint, ...], ...] = Field(min_length=1)
    vias: tuple[ViaSpec, ...] = ()

    @field_validator("signal", mode="before")
    @classmethod
    def _coerce_signal(cls, value: Any) -> Any:
        if isinstance(value, I2cSignal):
            return value
        if isinstance(value, str):
            # Accept the canonical name ("SDA") OR the .value
            # ("+3V3" for VCC) — round-trip via model_dump(mode='json')
            # emits the .value, so both paths must validate.
            try:
                return I2cSignal[value]
            except KeyError:
                pass
            for sig in I2cSignal:
                if sig.value == value:
                    return sig
            raise ValueError(
                f"unknown I2cSignal name {value!r}; expected one of "
                f"{[s.name for s in I2cSignal]} or "
                f"{[s.value for s in I2cSignal]}"
            )
        return value

    @field_validator("legs", mode="before")
    @classmethod
    def _normalise_legs(cls, value: Any) -> Any:
        # Each leg must itself be a list of waypoint specs. Pydantic
        # validates the waypoints individually; we just ensure the
        # outer shape is a tuple of tuples.
        if value is None:
            return ()
        if isinstance(value, (list, tuple)):
            normed: list[tuple] = []
            for leg in value:
                if not isinstance(leg, (list, tuple)):
                    raise ValueError(
                        f"each leg must be a list of waypoints, got {leg!r}"
                    )
                if len(leg) < 2:
                    raise ValueError(
                        f"each leg needs ≥2 waypoints, got {leg!r}"
                    )
                normed.append(tuple(leg))
            return tuple(normed)
        return value


# ---------------------------------------------------------------------------
# Top-level spec
# ---------------------------------------------------------------------------


class DimOverrides(BaseModel):
    """Scalar overrides for `Tier1SubstrateDimensions`. The full
    dataclass has nested per-device dim sub-dataclasses (esp32, scd41,
    bh1750) that v1 doesn't expose to YAML — we instantiate
    `Tier1SubstrateDimensions(**overrides)` and let those nested
    factories supply defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    board_w: float | None = None
    board_h: float | None = None
    thickness: float | None = None
    hole_diameter: float | None = None
    channel_width: float | None = None
    channel_depth: float | None = None
    via_diameter: float | None = None
    pocket_clearance: float | None = None
    overcut: float | None = None
    min_wall_thickness: float | None = None
    edge_clearance: float | None = None
    esp32_pin_pocket_clearance: float | None = None
    receptacle_diameter: float | None = None
    oled_pedestal_width: float | None = None
    oled_pedestal_depth: float | None = None
    oled_pedestal_height: float | None = None
    oled_support_bump_width: float | None = None
    oled_support_bump_depth: float | None = None
    oled_support_bump_height: float | None = None
    oled_support_bump_x: float | None = None
    oled_support_bump_y: float | None = None

    def to_kwargs(self) -> dict[str, Any]:
        # Drop unset (None) keys so the dataclass defaults stay in
        # control of anything the YAML didn't override.
        return {
            k: v for k, v in self.model_dump().items() if v is not None
        }


class CircuitSpec(BaseModel):
    """Top-level declarative description of a substrate variant."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    dim: DimOverrides = Field(default_factory=DimOverrides)
    levels: tuple[Level, ...] = Field(min_length=1)
    devices: tuple[Device, ...] = ()
    routes: tuple[Route, ...] = ()

    @model_validator(mode="after")
    def _device_levels_in_bounds(self) -> "CircuitSpec":
        n = len(self.levels)
        for d in self.devices:
            for idx in d.levels:
                if not 0 <= idx < n:
                    raise ValueError(
                        f"Device {d.name!r}: level index {idx} out of range "
                        f"(only {n} levels declared)"
                    )
            for idx in d.contributes_polygon_to:
                if not 0 <= idx < n:
                    raise ValueError(
                        f"Device {d.name!r}: contributes_polygon_to index "
                        f"{idx} out of range (only {n} levels declared)"
                    )
        return self

    @model_validator(mode="after")
    def _routes_inside_board(self) -> "CircuitSpec":
        # The base (level 0) perimeter is the board outline. Every
        # waypoint must sit inside it, less the edge_clearance —
        # catches off-board route authoring before AnchorSCAD ever
        # tries to carve a channel out of empty space.
        if not self.levels:
            return self
        base = self.levels[0].perimeter
        # Pull edge_clearance from the spec's dim override, falling
        # back to Tier1SubstrateDimensions' default. Importing the
        # dataclass at module scope creates a circular import via
        # vitamins.substrate → circuit; defer it here.
        edge = (
            self.dim.edge_clearance
            if self.dim.edge_clearance is not None
            else 0.8
        )
        x_min = base.x_min + edge
        x_max = base.x_max - edge
        y_min = base.y_min + edge
        y_max = base.y_max - edge

        bad: list[str] = []
        for route in self.routes:
            for leg_idx, leg in enumerate(route.legs):
                for i, wp in enumerate(leg):
                    if not (x_min <= wp.x <= x_max and y_min <= wp.y <= y_max):
                        bad.append(
                            f"route {route.signal.name} leg[{leg_idx}][{i}] "
                            f"= ({wp.x:.3f}, {wp.y:.3f}) sits outside board "
                            f"({x_min:.3f}..{x_max:.3f}, "
                            f"{y_min:.3f}..{y_max:.3f}) with "
                            f"edge_clearance={edge:.3f}"
                        )
            for i, via in enumerate(route.vias):
                if not (x_min <= via.x <= x_max and y_min <= via.y <= y_max):
                    bad.append(
                        f"route {route.signal.name} via[{i}] = "
                        f"({via.x:.3f}, {via.y:.3f}) sits outside board "
                        f"({x_min:.3f}..{x_max:.3f}, "
                        f"{y_min:.3f}..{y_max:.3f}) with "
                        f"edge_clearance={edge:.3f}"
                    )
        if bad:
            raise ValueError(
                "routes off-board (centreline test, edge_clearance applied):\n"
                + "\n".join(bad)
            )
        return self
