"""Bus declarations and net resolution.

A `Bus` is the user-facing electrical wiring statement: "the SCD41 and
the BH1750 are both slaves on the ESP32's I²C bus". Each bus kind has a
fixed set of signals (I²C → VCC/GND/SCL/SDA) that the resolver expands
into one `Net` per signal, listing the master pin and every slave pin
that carries that signal.

The router consumes `Net`s, not `Bus`es.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from board.devices import Device, Microcontroller
from board.pins import Pin, Point2D


# ---------------------------------------------------------------------------
# Standard signal sets per bus kind
# ---------------------------------------------------------------------------


_BUS_SIGNALS: dict[str, tuple[str, ...]] = {
    "i2c":  ("VCC", "GND", "SCL", "SDA"),
    "uart": ("VCC", "GND", "TX",  "RX"),
    "spi":  ("VCC", "GND", "SCK", "MOSI", "MISO", "CS"),
}


# Pair groupings within a bus — `(first, second)` tuples that the
# router uses to bundle related signals. The router routes the FIRST
# signal of each pair to claim a trunk corridor, then routes the
# SECOND signal with a parallel-bias A* cost that rewards staying
# alongside the first. Result: VCC + GND stay together, SCL + SDA
# stay together.
_BUS_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "i2c":  (("VCC", "GND"), ("SCL", "SDA")),
    "uart": (("VCC", "GND"), ("TX", "RX")),
    "spi":  (("VCC", "GND"), ("SCK", "MOSI"), ("MISO", "CS")),
}


def bus_signals(kind: str) -> tuple[str, ...]:
    try:
        return _BUS_SIGNALS[kind]
    except KeyError as exc:
        known = ", ".join(sorted(_BUS_SIGNALS))
        raise KeyError(
            f"unknown bus kind {kind!r}; known: {known}"
        ) from exc


def bus_pairs(kind: str) -> tuple[tuple[str, str], ...]:
    """Return the (first, second) pair tuples for this bus kind.
    Signals not listed in any pair fall through to default ordering."""
    return _BUS_PAIRS.get(kind, ())


# ---------------------------------------------------------------------------
# Routing hints — optional per-signal nudges fed to the autorouter
# ---------------------------------------------------------------------------


class HintWaypoint(BaseModel):
    """A `(x, y, layer)` checkpoint the route MUST pass through.

    Accepts either `{x, y, layer}` or the YAML-friendly `[x, y, layer]`
    list form.
    """

    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    layer: Literal[1, 2]

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)) and not isinstance(value, str):
            if len(value) != 3:
                raise ValueError(
                    f"HintWaypoint list form must be [x, y, layer], got {value!r}"
                )
            return {"x": value[0], "y": value[1], "layer": value[2]}
        return value


class RoutingHint(BaseModel):
    """Per-signal nudges to the autorouter.

    `must_pass` — hard requirement. The route visits every waypoint in
    order before reaching each slave. Fails loudly if any leg is
    unroutable.

    `prefer_layer` — soft. Steps on the *other* layer cost more, so A*
    finds a path on the preferred layer when one exists and falls back
    to vias otherwise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    must_pass: tuple[HintWaypoint, ...] = ()
    prefer_layer: Literal[1, 2] | None = None


# ---------------------------------------------------------------------------
# Bus declaration
# ---------------------------------------------------------------------------


class Bus(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["i2c", "uart", "spi"]
    name: str
    master: str                          # DeviceInstance.name on the board
    slaves: tuple[str, ...] = Field(min_length=1)
    # Keyed by signal name (uppercase: "SCL", "SDA", "VCC", "GND", ...).
    # Signals not listed get default routing.
    routing_hints: dict[str, RoutingHint] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Net resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PinEndpoint:
    """One end of a Net — the device instance, the pin, and the absolute
    xy on the substrate (already rotated + translated, and projected down
    through any header to the substrate top)."""

    instance_name: str
    pin: Pin
    position: Point2D


@dataclass(frozen=True)
class Net:
    """One bus signal resolved to concrete endpoints.

    `endpoints[0]` is the master pin (the bus's root). The remaining
    endpoints are slave pins, in the order the slaves appear in the
    Bus declaration. The router builds a tree rooted at the master,
    branching out to every slave.

    `hint` carries optional per-signal routing nudges (must-pass
    waypoints, layer preference). Resolver leaves it `None` when the
    Bus didn't declare a hint for this signal.
    """

    bus_name: str
    signal: str
    endpoints: tuple[PinEndpoint, ...]
    hint: RoutingHint | None = None

    @property
    def master(self) -> PinEndpoint:
        return self.endpoints[0]

    @property
    def slaves(self) -> tuple[PinEndpoint, ...]:
        return self.endpoints[1:]


def resolve_bus(
    bus: Bus,
    instances: Mapping[str, "BoundDevice"],
) -> tuple[Net, ...]:
    """Expand one Bus into one Net per signal.

    `instances` maps DeviceInstance.name → BoundDevice (the bound device
    knows its absolute pin positions on the substrate). Raises
    `ValueError` with a clear message if the master isn't a
    Microcontroller, if a slave is missing, or if any participant lacks
    a pin for a required signal."""
    master_bound = _require_instance(instances, bus.master, role="master")
    if not isinstance(master_bound.device, Microcontroller):
        raise ValueError(
            f"Bus {bus.name!r}: master {bus.master!r} is a "
            f"{type(master_bound.device).__name__}; must be a Microcontroller"
        )
    slave_bounds = [
        _require_instance(instances, name, role=f"slave[{i}]")
        for i, name in enumerate(bus.slaves)
    ]

    nets: list[Net] = []
    for sig in bus_signals(bus.kind):
        master_endpoint = _endpoint_or_fail(master_bound, sig, bus.name, role="master")
        slave_endpoints = [
            _endpoint_or_fail(b, sig, bus.name, role=f"slave {b.instance_name!r}")
            for b in slave_bounds
        ]
        # Hints are keyed by uppercase signal name; tolerate both cases.
        hint = bus.routing_hints.get(sig) or bus.routing_hints.get(sig.upper())
        nets.append(Net(
            bus_name=bus.name,
            signal=sig,
            endpoints=(master_endpoint, *slave_endpoints),
            hint=hint,
        ))
    return tuple(nets)


def _require_instance(
    instances: Mapping[str, "BoundDevice"], name: str, *, role: str
) -> "BoundDevice":
    try:
        return instances[name]
    except KeyError as exc:
        known = ", ".join(sorted(instances))
        raise KeyError(
            f"Bus {role} {name!r} not found among device instances "
            f"({known})"
        ) from exc


def _endpoint_or_fail(
    bound: "BoundDevice", signal: str, bus_name: str, *, role: str
) -> PinEndpoint:
    pin = bound.device.pin_by_role(signal)
    if pin is None:
        raise ValueError(
            f"Bus {bus_name!r}: {role} ({bound.instance_name!r}, "
            f"device={bound.device.name!r}) has no pin with role {signal!r}"
        )
    return PinEndpoint(
        instance_name=bound.instance_name,
        pin=pin,
        position=bound.absolute_pin_position(pin),
    )


# ---------------------------------------------------------------------------
# BoundDevice — a DeviceInstance + its absolute substrate positions.
# Defined here (and not in board.py) so the resolver can typecheck it
# without a circular import.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundDevice:
    instance_name: str
    device: Device
    position: Point2D
    rotation_deg: int

    def absolute_pin_position(self, pin: Pin) -> Point2D:
        return self.device.pin_position_at(self.position, self.rotation_deg, pin)
