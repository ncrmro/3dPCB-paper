"""Connectivity + geometry tests for the spike substrate's netlist.

Answers the question the user asked: does each wire actually reach every
declared endpoint, AND does no wire overlap another wire / foreign pin /
module pocket? Pure Cartesian math on the `WireSegment` / `Via` /
`Point2D` data the substrate already produces.

Collision helpers (segment/via bbox math, pocket footprints,
through-hole enumeration) live in `router.collisions` so the optimiser
and the test gate share one implementation.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable

import pytest

from netlist import (
    NETS,
    PRIMARY_BUS,
    I2cSignal,
    Pin,
)
from router.collisions import (
    all_through_holes,
    module_pocket_bboxes,
    net_pin_keys,
    pin_key as _key,
    segment_pierces_hole,
    segments_collide,
    via_in_pocket,
    via_overlaps_hole,
)
from vitamins.esp32_pinout import J1A_PINOUT, J1B_PINOUT
from vitamins.oled_ssd1306_pinout import OLED_PINOUT
from vitamins.sensors_pinout import BH1750_PINOUT, SCD41_PINOUT
from vitamins.substrate import (
    Tier1SubstrateDimensions,
    Via,
    WireSegment,
    _build_paths_for_net,
    _pin_position,
)


# ---------------------------------------------------------------------------
# Static netlist invariants
# ---------------------------------------------------------------------------


_ALL_PINOUTS = {
    "J1A": J1A_PINOUT,
    "J1B": J1B_PINOUT,
    "SCD41": SCD41_PINOUT,
    "BH1750": BH1750_PINOUT,
    # OLED PINOUT exists but is not yet on PRIMARY_BUS.devices —
    # the substrate routing code needs an upgrade before we add it.
    # Listing it here exercises the per-pinout invariants (signal
    # uniqueness, bus-signal coverage) before the integration step.
    "OLED": OLED_PINOUT,
}


@pytest.mark.parametrize("name,pinout", list(_ALL_PINOUTS.items()))
def test_pinout_signal_uniqueness(name: str, pinout: dict[int, Pin]) -> None:
    """Each I2cSignal appears on at most one pin per pinout."""
    seen: dict[I2cSignal, int] = {}
    for num, pin in pinout.items():
        if pin.signal is None:
            continue
        prev = seen.get(pin.signal)
        assert prev is None, (
            f"{name} pinout: {pin.signal.name} on pins {prev} and {num}"
        )
        seen[pin.signal] = num


def test_bus_signals_present_on_every_participant() -> None:
    """Every participant on the bus exposes every bus signal."""
    bus = PRIMARY_BUS
    for participant_name, pinout in (
        ("J1A+J1B (ESP32 master)",
         {**J1A_PINOUT, **{1000 + k: v for k, v in J1B_PINOUT.items()}}),
        ("SCD41", SCD41_PINOUT),
        ("BH1750", BH1750_PINOUT),
    ):
        signals_present = {p.signal for p in pinout.values() if p.signal}
        missing = set(bus.signals) - signals_present
        assert not missing, (
            f"{participant_name} pinout missing bus signals {missing}"
        )


def test_oled_pinout_ready_for_primary_bus() -> None:
    """The OLED PINOUT carries every signal PRIMARY_BUS needs.

    OLED is not yet listed in PRIMARY_BUS.devices because the substrate
    routing code (`_build_paths_for_net` in substrate.py) hardcodes
    `net.device_pins[0]` = SCD41 and `[1]` = BH1750. Once that loops
    over an N-device tuple, OLED can be added to PRIMARY_BUS.devices
    and this test plus `test_endpoint_coverage` will exercise it.
    """
    signals = {p.signal for p in OLED_PINOUT.values() if p.signal}
    missing = set(PRIMARY_BUS.signals) - signals
    assert not missing, (
        f"OLED_PINOUT missing bus signals {missing}; "
        f"the pinout is not yet a valid bus participant."
    )


@pytest.mark.parametrize("sig", list(PRIMARY_BUS.signals))
def test_net_signal_agreement(sig: I2cSignal) -> None:
    """The Net assembled for each signal references pins of that signal."""
    net = NETS[sig]
    assert net.master_pin.signal == sig, (
        f"master_pin {net.master_pin} does not carry {sig.name}"
    )
    for i, dp in enumerate(net.device_pins):
        assert dp.signal == sig, (
            f"device_pins[{i}] {dp} does not carry {sig.name}"
        )


# ---------------------------------------------------------------------------
# Connectivity: BFS on the segment+via adjacency graph
# ---------------------------------------------------------------------------


def _build_graph(elements: Iterable) -> dict[tuple[float, float], set[tuple[float, float]]]:
    """Adjacency graph: segments add edges; vias add no edges but their
    `position` is implicitly a shared node across both layers because
    a via punches the full substrate.
    """
    g: dict[tuple[float, float], set[tuple[float, float]]] = defaultdict(set)
    for el in elements:
        if isinstance(el, WireSegment):
            a = _key(el.start)
            b = _key(el.end)
            g[a].add(b)
            g[b].add(a)
        elif isinstance(el, Via):
            # Touching the node forces it into the graph even if no
            # segment uses that exact (x,y) — defensive.
            g[_key(el.position)]  # noqa: B018
    return g


def _bfs(g: dict, start: tuple[float, float]) -> set:
    reached = {start}
    q = deque([start])
    while q:
        n = q.popleft()
        for m in g.get(n, ()):
            if m not in reached:
                reached.add(m)
                q.append(m)
    return reached


@pytest.mark.parametrize("sig", list(PRIMARY_BUS.signals))
def test_endpoint_coverage(sig: I2cSignal) -> None:
    """Every declared device pin is reachable from the master pin."""
    net = NETS[sig]
    paths = _build_paths_for_net(net)
    elements = [e for p in paths for e in p.elements]
    g = _build_graph(elements)

    start = _key(_pin_position(net.master_pin))
    reached = _bfs(g, start)

    for dp in net.device_pins:
        dest = _key(_pin_position(dp))
        assert dest in reached, (
            f"Net {sig.name}: master {net.master_pin.ref}.{net.master_pin.number} "
            f"cannot reach {dp.ref}.{dp.number} at {dest}; reached={sorted(reached)}"
        )


@pytest.mark.parametrize("sig", list(PRIMARY_BUS.signals))
def test_no_dangling_segments(sig: I2cSignal) -> None:
    """Interior graph nodes must have degree ≥ 2; only declared endpoints
    may have degree 1 (the wire physically terminates at a pin pad)."""
    net = NETS[sig]
    paths = _build_paths_for_net(net)
    elements = [e for p in paths for e in p.elements]
    g = _build_graph(elements)

    endpoints = {_key(_pin_position(net.master_pin))} | {
        _key(_pin_position(dp)) for dp in net.device_pins
    }

    for node, neighbours in g.items():
        if not neighbours:
            # Via with no incident segment — defensive only; means a via
            # was placed at a coordinate no WireSegment touches.
            assert node in endpoints, (
                f"Net {sig.name}: isolated graph node at {node}"
            )
            continue
        if len(neighbours) == 1 and node not in endpoints:
            raise AssertionError(
                f"Net {sig.name}: degree-1 interior node at {node} "
                f"(stub terminates in mid-air)"
            )


# ---------------------------------------------------------------------------
# Geometric collisions (AABB sweep)
# ---------------------------------------------------------------------------


# Build a single shared snapshot of every segment + via, tagged with net.
def _all_routed_elements() -> list[tuple[I2cSignal, object]]:
    out: list[tuple[I2cSignal, object]] = []
    for sig, net in NETS.items():
        for path in _build_paths_for_net(net):
            for el in path.elements:
                out.append((sig, el))
    return out


_DIM = Tier1SubstrateDimensions()
_CW = _DIM.channel_width
_HOLE_R = _DIM.hole_diameter / 2
_VIA_R = _DIM.via_diameter / 2


def test_no_same_layer_wire_overlap() -> None:
    """No two segments of different nets overlap on the same layer."""
    elements = _all_routed_elements()
    failures: list[str] = []
    for i, (sig_a, el_a) in enumerate(elements):
        if not isinstance(el_a, WireSegment):
            continue
        for sig_b, el_b in elements[i + 1:]:
            if not isinstance(el_b, WireSegment):
                continue
            if sig_a == sig_b:
                continue
            if segments_collide(el_a, el_b, _CW):
                failures.append(
                    f"{sig_a.name} ↔ {sig_b.name} on L{el_a.layer}: "
                    f"{el_a.start}-{el_a.end} overlaps {el_b.start}-{el_b.end}"
                )
    assert not failures, "Same-layer wire overlap detected:\n  " + "\n  ".join(failures)


def test_no_trunk_through_foreign_pin() -> None:
    """No WireSegment passes through a through-hole that isn't one of
    its net's endpoints. The hole pierces every layer, so this is a
    layer-agnostic check."""
    elements = _all_routed_elements()
    # The OLED's J4 pins are foreign-pin candidates on every other net,
    # so include them in the foreign-hole sweep on PRIMARY_BUS (Tier 2).
    holes = all_through_holes(include_oled=True)
    failures: list[str] = []
    for sig, el in elements:
        if not isinstance(el, WireSegment):
            continue
        endpoints = net_pin_keys(NETS[sig])
        for pin, pos in holes:
            if _key(pos) in endpoints:
                continue
            if segment_pierces_hole(el, pos, _CW, _HOLE_R):
                failures.append(
                    f"{sig.name} L{el.layer} segment {el.start}-{el.end} "
                    f"pierces {pin.ref}.{pin.number} hole at {pos}"
                )
    assert not failures, "Trunk-through-foreign-pin collisions:\n  " + "\n  ".join(failures)


def test_no_via_in_pocket() -> None:
    """No Via lands inside a module pocket footprint."""
    elements = _all_routed_elements()
    pockets = module_pocket_bboxes(_DIM)
    failures: list[str] = []
    for sig, el in elements:
        if not isinstance(el, Via):
            continue
        for module_name, pocket in pockets.items():
            if via_in_pocket(el, pocket, _VIA_R):
                failures.append(
                    f"{sig.name} via at {el.position} overlaps "
                    f"{module_name} pocket {pocket}"
                )
    assert not failures, "Via-in-pocket collisions:\n  " + "\n  ".join(failures)


def test_no_via_on_foreign_pin() -> None:
    """No Via lands on a through-hole belonging to a foreign net."""
    elements = _all_routed_elements()
    holes = all_through_holes(include_oled=True)
    failures: list[str] = []
    for sig, el in elements:
        if not isinstance(el, Via):
            continue
        endpoints = net_pin_keys(NETS[sig])
        for pin, pos in holes:
            if _key(pos) in endpoints:
                continue
            if via_overlaps_hole(el, pos, _VIA_R, _HOLE_R):
                failures.append(
                    f"{sig.name} via at {el.position} too close to "
                    f"{pin.ref}.{pin.number} at {pos}"
                )
    assert not failures, "Via-on-foreign-pin collisions:\n  " + "\n  ".join(failures)


# ---------------------------------------------------------------------------
# KiCad parity
# ---------------------------------------------------------------------------


def test_kicad_derived_labels() -> None:
    """gen_spike_pcb.py's J*_PINS literal values match what `_labels()`
    would render from the canonical PINOUTs. Catches the case where the
    KiCad import side drifts from the AnchorSCAD side."""
    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "gen_spike_pcb",
        os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "kicad", "gen_spike_pcb.py",
        )),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def expected(pinout):
        return {n: (p.signal.value if p.signal else p.function)
                for n, p in pinout.items()}

    assert mod.J1A_PINS == expected(J1A_PINOUT)
    assert mod.J1B_PINS == expected(J1B_PINOUT)
    assert mod.J2_PINS == expected(SCD41_PINOUT)
    assert mod.J3_PINS == expected(BH1750_PINOUT)
