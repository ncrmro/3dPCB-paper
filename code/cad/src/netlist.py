"""Bus-level netlist for the 3dPCB substrate.

Single source of truth for which sensor pin carries which I2C bus
signal. Consumed by both `vitamins/substrate.py` (AnchorSCAD geometry)
and `code/kicad/gen_spike_pcb.py` (KiCad PCB sibling), so the two
embodiments can't drift apart.

Layout:

- Public types (`I2cSignal`, `Pin`, `Bus`, `RoutingHint`, `Net`) are
  defined at the top of the module. Per-sensor PINOUT declarations
  live next to each sensor's geometry class
  (`vitamins/{esp32,sensors}.py`) and import these types.
- `PRIMARY_BUS` + `ROUTING` are the board-specific configuration.
- `NETS: dict[I2cSignal, Net]` is assembled at module load via late
  imports from the vitamins package; a signal missing from any
  participant's pinout raises at import time, not print time.

The breakout-pinout audit (which silkscreen pin maps to which
footprint pad) is recorded in `netlist_audit.md`. Changes to any
sensor's PINOUT MUST be reflected in that audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class I2cSignal(Enum):
    """The canonical I2C bus signals. `.value` is the KiCad net label."""

    VCC = "+3V3"
    GND = "GND"
    SCL = "SCL"
    SDA = "SDA"
    ADDR = "ADDR"  # sensor-local address-select pin; not on the shared bus


@dataclass(frozen=True)
class Pin:
    """One physical pin on a module header.

    Exactly one of `signal` (it's on the bus) or `function` (it's a
    GPIO / power rail / NC) MUST be set. Both is allowed when a bus
    pin also has an MCU-side name worth recording (e.g. SDA on GPIO5).
    """

    ref: str            # column reference ("J1A", "J1B", "J2", "J3")
    number: int         # 1-indexed pin number on that column
    signal: Optional[I2cSignal] = None
    function: Optional[str] = None

    def __post_init__(self) -> None:
        if self.signal is None and self.function is None:
            raise ValueError(
                f"Pin {self.ref}.{self.number}: must declare signal or function"
            )


@dataclass(frozen=True)
class Bus:
    """A logical bus declaration: which signals, which participants."""

    name: str
    signals: tuple[I2cSignal, ...]
    master: str                       # module key (e.g. "ESP32")
    master_columns: tuple[str, ...]   # column refs to scan on master ("J1A", "J1B")
    devices: tuple[str, ...]          # module keys for slaves ("SCD41", "BH1750")


@dataclass(frozen=True)
class RoutingHint:
    """Layer-choice + corridor knobs for one net on this board.

    These are imperative knobs encoded as data — the substrate's
    `_build_paths_for_net` reads them directly. When the design moves
    to a real autorouter, this dataclass disappears in favour of
    declared constraints; see plan §"Future work".
    """

    north_x: float
    corridor_y: float
    scd_east_on_l2: bool
    branch_east_on_l2: bool


@dataclass(frozen=True)
class Net:
    """One bus signal resolved to concrete pins + routing fields."""

    signal: I2cSignal
    master_pin: Pin
    device_pins: tuple[Pin, ...]  # one per Bus.devices, in order
    north_x: float
    corridor_y: float
    scd_east_on_l2: bool
    branch_east_on_l2: bool


# ---------------------------------------------------------------------------
# Board configuration (spike board)
# ---------------------------------------------------------------------------


TIER1_BUS = Bus(
    name="tier1_i2c",
    signals=(I2cSignal.VCC, I2cSignal.GND, I2cSignal.SCL, I2cSignal.SDA),
    master="ESP32",
    master_columns=("J1A", "J1B"),
    devices=("SCD41", "BH1750"),
)

TIER2_BUS = Bus(
    name="tier2_i2c",
    signals=(I2cSignal.VCC, I2cSignal.GND, I2cSignal.SCL, I2cSignal.SDA),
    master="ESP32",
    master_columns=("J1A", "J1B"),
    devices=("SCD41", "BH1750", "OLED"),
)

# PRIMARY_BUS is the latest fully-routed bus (currently Tier 2). Tests
# and the KiCad sibling consume PRIMARY_BUS / NETS to validate the
# current target design; the substrate classes pick their bus
# explicitly so each tier renders only its own devices.
PRIMARY_BUS = TIER2_BUS


ROUTING: dict[I2cSignal, RoutingHint] = {
    I2cSignal.VCC: RoutingHint(north_x=-29.0, corridor_y=6.0,
                               scd_east_on_l2=True, branch_east_on_l2=True),
    I2cSignal.GND: RoutingHint(north_x=-27.0, corridor_y=9.0,
                               scd_east_on_l2=True, branch_east_on_l2=True),
    I2cSignal.SCL: RoutingHint(north_x=-11.0, corridor_y=12.0,
                               scd_east_on_l2=True, branch_east_on_l2=True),
    I2cSignal.SDA: RoutingHint(north_x=-9.0,  corridor_y=15.0,
                               scd_east_on_l2=False, branch_east_on_l2=True),
}


# ---------------------------------------------------------------------------
# NETS assembly
# ---------------------------------------------------------------------------


def _find_pin_for_signal(
    pinout: dict[int, Pin], signal: I2cSignal
) -> Optional[Pin]:
    matches = [p for p in pinout.values() if p.signal == signal]
    if len(matches) > 1:
        raise ValueError(
            f"Pinout has {len(matches)} pins carrying {signal.name}; "
            f"expected at most 1"
        )
    return matches[0] if matches else None


def _assemble_nets(
    bus: Bus,
    routing: dict[I2cSignal, RoutingHint],
    master_columns: dict[str, dict[int, Pin]],
    devices: dict[str, dict[int, Pin]],
) -> dict[I2cSignal, Net]:
    """Resolve every bus signal to a `Net` with concrete Pins.

    Fails loudly if any participant's PINOUT doesn't expose every
    bus signal — the import will raise before any geometry is built.
    """
    nets: dict[I2cSignal, Net] = {}
    for sig in bus.signals:
        # exactly one master pin across all master columns
        master_candidates: list[Pin] = []
        for col_name in bus.master_columns:
            p = _find_pin_for_signal(master_columns[col_name], sig)
            if p is not None:
                master_candidates.append(p)
        if not master_candidates:
            raise ValueError(
                f"Bus '{bus.name}' signal {sig.name}: no pin on master "
                f"{bus.master} (columns {bus.master_columns})"
            )
        if len(master_candidates) > 1:
            raise ValueError(
                f"Bus '{bus.name}' signal {sig.name}: multiple master pins "
                f"({master_candidates}); a signal must be on exactly one column"
            )
        master_pin = master_candidates[0]

        # exactly one pin per device
        device_pins: list[Pin] = []
        for dev_name in bus.devices:
            p = _find_pin_for_signal(devices[dev_name], sig)
            if p is None:
                raise ValueError(
                    f"Bus '{bus.name}' signal {sig.name}: device {dev_name} "
                    f"has no pin carrying it"
                )
            device_pins.append(p)

        hint = routing[sig]
        nets[sig] = Net(
            signal=sig,
            master_pin=master_pin,
            device_pins=tuple(device_pins),
            north_x=hint.north_x,
            corridor_y=hint.corridor_y,
            scd_east_on_l2=hint.scd_east_on_l2,
            branch_east_on_l2=hint.branch_east_on_l2,
        )
    return nets


# Per-bus NETS are assembled lazily on first access via module
# `__getattr__`. Eager assembly here would create a circular import:
# this module is imported by vitamins.esp32 / vitamins.sensors at their
# top (to access I2cSignal and Pin), so if we tried to import their
# PINOUTs back here at netlist load time, vitamins.esp32 would still
# be mid-import when the chain re-enters it. Lazy resolution sidesteps
# that cleanly.
_NETS_CACHE: dict[str, dict[I2cSignal, Net]] = {}


def _build_nets_for(bus: Bus) -> dict[I2cSignal, Net]:
    # Import the pure-data PINOUT siblings — they don't pull anchorscad,
    # so this works in both the cad and KiCad flake Python envs.
    from vitamins.esp32_pinout import J1A_PINOUT, J1B_PINOUT  # noqa: E402
    from vitamins.oled_ssd1306_pinout import OLED_PINOUT  # noqa: E402
    from vitamins.sensors_pinout import BH1750_PINOUT, SCD41_PINOUT  # noqa: E402

    pinouts = {
        "SCD41": SCD41_PINOUT,
        "BH1750": BH1750_PINOUT,
        "OLED": OLED_PINOUT,
    }
    return _assemble_nets(
        bus=bus,
        routing=ROUTING,
        master_columns={"J1A": J1A_PINOUT, "J1B": J1B_PINOUT},
        devices={name: pinouts[name] for name in bus.devices},
    )


def __getattr__(name: str):
    """Lazy module attributes — `NETS`, `TIER1_NETS`, `TIER2_NETS`."""
    bus_for_name = {
        "NETS": PRIMARY_BUS,         # alias for current PRIMARY_BUS
        "TIER1_NETS": TIER1_BUS,
        "TIER2_NETS": TIER2_BUS,
    }
    if name in bus_for_name:
        bus = bus_for_name[name]
        if bus.name not in _NETS_CACHE:
            _NETS_CACHE[bus.name] = _build_nets_for(bus)
        return _NETS_CACHE[bus.name]
    raise AttributeError(f"module 'netlist' has no attribute {name!r}")
