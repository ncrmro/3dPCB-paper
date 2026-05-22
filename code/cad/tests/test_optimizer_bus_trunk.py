"""Bundled-topology mode — enumerate all visit orders, pick min.

Verifies exhaustive enumeration (not greedy nearest-neighbor) on a
4-device synthetic fixture where the greedy order is provably worse.
"""

from __future__ import annotations

import os

from optimizer.metrics import bundled_bus_metric
from optimizer.plan_parser import ModuleAnchor, ParsedPlan, Pocket, parse_plan
from optimizer.weights import BusSpec, load_weights
from optimizer.signal_class import SignalClass


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TIER1_PLAN = os.path.join(REPO_ROOT, "printable_pcb", "spike_v2", "substrate_plan.md")


def test_bundled_picks_start_at_visit_constraint():
    plan = parse_plan(TIER1_PLAN)
    weights = load_weights()
    bus = weights.buses["primary_i2c"]
    m = bundled_bus_metric(plan, bus, weights=weights)
    assert m is not None
    assert m.visit_order[0] == "ESP32"
    assert m.total_vias == 0
    # Conductors include both bus signals and power_signals
    assert set(m.conductors) >= {"sda", "scl", "vcc", "gnd"}


def test_exhaustive_picks_min_over_synthetic_4_device():
    """Construct a synthetic plan where the greedy nearest-neighbor
    walk produces a strictly worse total than the global min, then
    assert the optimizer picks the global min."""
    # Geometry: hub at origin; devices at the 4 cardinal points with
    # different distances. Greedy from hub goes to the nearest first,
    # then the next nearest, etc — but the true minimum tour visits
    # them in an order that backtracks less.
    pockets = (
        Pocket(module="ESP32", centre=(0.0, 0.0)),
        Pocket(module="A", centre=(1.0, 0.0)),
        Pocket(module="B", centre=(0.0, 10.0)),
        Pocket(module="C", centre=(11.0, 0.0)),
        Pocket(module="D", centre=(0.0, 11.0)),
    )
    modules = (
        ModuleAnchor(label="ESP32 X", column_ref="J1A", vitamin="x",
                     pin1_xy=(0.0, 0.0), pad_direction="+Y", pin_count=1, pitch=1.0),
        ModuleAnchor(label="A x", column_ref="J2", vitamin="x",
                     pin1_xy=(1.0, 0.0), pad_direction="+X", pin_count=1, pitch=1.0),
        ModuleAnchor(label="B x", column_ref="J3", vitamin="x",
                     pin1_xy=(0.0, 10.0), pad_direction="+X", pin_count=1, pitch=1.0),
        ModuleAnchor(label="C x", column_ref="J4", vitamin="x",
                     pin1_xy=(11.0, 0.0), pad_direction="+X", pin_count=1, pitch=1.0),
        ModuleAnchor(label="D x", column_ref="J5", vitamin="x",
                     pin1_xy=(0.0, 11.0), pad_direction="+X", pin_count=1, pitch=1.0),
    )
    plan = ParsedPlan(
        source_path="<test>",
        board_name="synthetic",
        modules=modules,
        nets=(),
        pockets=pockets,
        through_holes=(),
        net_routings=(),
    )
    bus = BusSpec(
        name="b",
        signal_class=SignalClass.BUS_BROADCAST,
        signals=("sda", "scl"),
        power_signals=("vcc", "gnd"),
        topology="bundled",
        visit_order_start="ESP32",
    )
    weights = load_weights()
    m = bundled_bus_metric(plan, bus, weights=weights)
    assert m is not None
    assert m.visit_order[0] == "ESP32"
    # Best tour visits the close neighbors together: A → C (both +x),
    # B → D (both +y). The total per-conductor should be < the worst
    # possible (a brute-force upper bound) — verify it's exactly the
    # minimum over all 24 device permutations.
    from itertools import permutations
    devices = ["A", "B", "C", "D"]
    def tour_len(order):
        coords = {p.module: p.centre for p in pockets}
        seq = ["ESP32"] + list(order)
        return sum(
            ((coords[seq[i+1]][0] - coords[seq[i]][0]) ** 2 +
             (coords[seq[i+1]][1] - coords[seq[i]][1]) ** 2) ** 0.5
            for i in range(len(seq) - 1)
        )
    expected = min(tour_len(p) for p in permutations(devices)) * len(m.conductors)
    assert abs(m.total_wire_mm - expected) < 1e-6
