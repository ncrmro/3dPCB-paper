"""Parser regression against the worktree's spike_v2 (Tier 1) and the
Tier 2 fixture committed under tests/fixtures/.
"""

from __future__ import annotations

import os

import pytest

from optimizer.plan_parser import parse_plan


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TIER1_PLAN = os.path.join(REPO_ROOT, "printable_pcb", "spike_v2", "substrate_plan.md")
TIER2_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "spike_v2_tier2_with_oled.md")


def test_tier1_parses_to_expected_shape():
    plan = parse_plan(TIER1_PLAN)
    assert plan.board_name == "spike_v2"
    columns = {m.column_ref for m in plan.modules}
    assert {"J1A", "J1B", "J2", "J3"} <= columns
    net_names = {n.name for n in plan.nets}
    assert {"+3V3", "GND", "SCL", "SDA"} <= net_names
    # Four routed nets, each with its YAML block
    routing_names = {r.name for r in plan.net_routings}
    assert {"vcc", "gnd", "scl", "sda"} == routing_names


def test_tier1_pin_xy_matches_pitch():
    plan = parse_plan(TIER1_PLAN)
    # SCD41 J2.1 at (5, -17), pitch 2.54, pads +X → J2.2 at (7.54, -17)
    assert plan.pin_xy("J2.1") == pytest.approx((5.0, -17.0))
    assert plan.pin_xy("J2.2") == pytest.approx((7.54, -17.0))
    # ESP32 J1A.3 at (-30, -17 + 2*2.54) = (-30, -11.92)
    assert plan.pin_xy("J1A.3") == pytest.approx((-30.0, -11.92))


def test_tier2_fixture_includes_oled():
    plan = parse_plan(TIER2_FIXTURE)
    columns = {m.column_ref for m in plan.modules}
    assert "J4" in columns
    # OLED row should be recognized; pin-1 at (-3.81, -22)
    j4 = plan.module_by_column("J4")
    assert j4 is not None
    assert j4.pin1_xy == pytest.approx((-3.81, -22.0))


def test_tier1_net_routings_have_nonzero_length():
    plan = parse_plan(TIER1_PLAN)
    for r in plan.net_routings:
        assert r.total_wire_mm() > 0
        assert len(r.vias) >= 1
