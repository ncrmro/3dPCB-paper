"""Per-signal scoring + Tier 1 invariants + Tier 2 regression.

Acceptance bar from issue #42: the two merges the LLM step surfaces
for spike_v2 Tier 2 (GND OLED↔SCD41, VCC OLED↔SCD41) must be
surfaced identically by the static optimizer. Tolerance ±2 mm on
wire saved.
"""

from __future__ import annotations

import os

from optimizer.metrics import before_metrics
from optimizer.plan_parser import parse_plan
from optimizer.proposals import build_proposals
from optimizer.weights import load_weights


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TIER1_PLAN = os.path.join(REPO_ROOT, "printable_pcb", "spike_v2", "substrate_plan.md")
TIER2_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "spike_v2_tier2_with_oled.md")


def test_before_metrics_aggregate_routing_lengths():
    plan = parse_plan(TIER1_PLAN)
    metrics = before_metrics(plan)
    assert len(metrics.per_net_wire_mm) == 4
    assert all(v > 10 for v in metrics.per_net_wire_mm.values())
    assert all(v >= 2 for v in metrics.per_net_vias.values())
    assert metrics.total_wire_mm == sum(metrics.per_net_wire_mm.values())
    assert metrics.total_vias == sum(metrics.per_net_vias.values())


def test_tier2_reproduces_llm_step_merges():
    plan = parse_plan(TIER2_FIXTURE)
    weights = load_weights()
    doc = build_proposals(plan, weights)
    by_sig = {p["signal"]: p for p in doc.proposals}
    # VCC SCD41.J2.1 ↔ OLED.J4.3 — LLM reported ~19 mm
    vcc = by_sig.get("+3V3")
    assert vcc is not None, f"no VCC proposal; got {doc.proposals}"
    assert set(vcc["participants"]) == {"J2.1", "J4.3"}
    assert abs(vcc["wire_saved_mm"] - 19) <= 2
    assert vcc["disposition"] == "auto_merge_with_droop_note"
    # GND SCD41.J2.2 ↔ OLED.J4.4 — LLM reported ~22 mm
    gnd = by_sig.get("GND")
    assert gnd is not None, f"no GND proposal; got {doc.proposals}"
    assert set(gnd["participants"]) == {"J2.2", "J4.4"}
    assert abs(gnd["wire_saved_mm"] - 22) <= 2


def test_tier2_declines_scd41_bh1750_for_collision():
    """LLM step rejected the SCD41↔BH1750 GND merge because the jumper
    would run along y=-17 through J2.3, J2.4, J3.1. The static
    optimizer should make the same call via the collision penalty."""
    plan = parse_plan(TIER2_FIXTURE)
    weights = load_weights()
    doc = build_proposals(plan, weights)
    declines = [d for d in doc.declined if set(d.get("participants", [])) == {"J2.2", "J3.2"}]
    assert declines, f"expected SCD41↔BH1750 GND decline; got {doc.declined}"
    assert any(d["reason"] == "collision_penalty_exceeds_savings" for d in declines)
