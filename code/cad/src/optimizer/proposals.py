"""Top-level orchestration — turn a parsed plan + weights into a
proposals YAML document.

Day-one runtime exercises the bus_broadcast / power_rail / ground /
singleton signal classes. Other classes parse into the weights spec
but contribute `not_yet_implemented` warnings rather than proposals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Optional

import yaml

from .collision import REMEDIATIONS, foreign_pins_on_jumper
from .eligibility import classify_net, evaluate_pair
from .metrics import (
    BundledBusMetric,
    bundled_bus_metric,
    before_metrics,
    score_pairwise_merge,
)
from .plan_parser import NetEndpoints, ParsedPlan
from .proximity import _module_key_for, centre_to_centre_mm, stacks_overlap
from .signal_class import IMPLEMENTED_CLASSES, SignalClass
from .weights import BusSpec, Weights


@dataclass
class ProposalsDocument:
    proposals: list[dict] = field(default_factory=list)
    declined: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    metrics_alternative: Optional[dict] = None
    warnings: list[dict] = field(default_factory=list)

    def to_yaml(self) -> str:
        body: dict[str, Any] = {
            "proposals": self.proposals,
            "declined": self.declined,
            "metrics": self.metrics,
        }
        if self.metrics_alternative is not None:
            body["metrics_alternative"] = self.metrics_alternative
        if self.warnings:
            body["warnings"] = self.warnings
        return yaml.safe_dump(body, sort_keys=False, default_flow_style=False)


def build_proposals(
    plan: ParsedPlan,
    weights: Weights,
    *,
    topology_override: Optional[str] = None,
) -> ProposalsDocument:
    doc = ProposalsDocument()

    # Surface load-time warnings up front
    for code, detail in plan.warnings:
        doc.warnings.append({"code": code, "detail": detail})
    for code, detail in weights.warnings:
        doc.warnings.append({"code": code, "detail": detail})
    for code, detail in weights.unimplemented_class_warnings():
        doc.warnings.append({"code": code, "detail": detail})

    # Compute "before" totals from the per-net YAML routing blocks
    before = before_metrics(plan)

    # Iterate every net in section 3 → classify → enumerate candidate
    # cross-module pairs → eligibility → proximity → score → emit.
    total_wire_saved = 0.0
    total_vias_saved = 0
    for net in plan.nets:
        klass, bus_name = classify_net(net.name, weights)
        bus = weights.buses.get(bus_name) if bus_name else None
        topology = topology_override or (bus.topology if bus else "per_signal")
        if klass not in IMPLEMENTED_CLASSES:
            doc.declined.append({
                "bus": bus_name,
                "signal": net.name,
                "reason": f"class_{klass.value}_not_implemented",
            })
            continue

        candidate_pairs = list(_cross_module_pairs(plan, net))
        if not candidate_pairs:
            continue

        for (pin_a, pin_b, module_a, module_b) in candidate_pairs:
            verdict = evaluate_pair(
                net_name=net.name,
                klass=klass,
                bus_name=bus_name,
                weights=weights,
                topology_override=topology_override,
                module_a=module_a,
                module_b=module_b,
            )
            if not verdict.eligible:
                doc.declined.append({
                    "bus": bus_name,
                    "signal": net.name,
                    "participants": [pin_a, pin_b],
                    "reason": verdict.reason or "ineligible",
                })
                continue

            d = centre_to_centre_mm(plan, module_a, module_b)
            if d > weights.proximity.max_centre_to_centre_mm:
                doc.declined.append({
                    "bus": bus_name,
                    "signal": net.name,
                    "participants": [pin_a, pin_b],
                    "reason": f"proximity_{d:.1f}mm_exceeds_{weights.proximity.max_centre_to_centre_mm:.1f}mm",
                })
                continue
            if weights.proximity.stack_overlap_required and not stacks_overlap(
                plan, module_a, module_b
            ):
                doc.declined.append({
                    "bus": bus_name,
                    "signal": net.name,
                    "participants": [pin_a, pin_b],
                    "reason": "stack_overlap_required_not_satisfied",
                })
                continue

            score = score_pairwise_merge(
                plan, net_name=net.name, pin_a=pin_a, pin_b=pin_b, weights=weights
            )
            if score is None or score.wire_saved_mm <= 0:
                doc.declined.append({
                    "bus": bus_name,
                    "signal": net.name,
                    "participants": [pin_a, pin_b],
                    "reason": "no_wire_saving_in_current_routing",
                })
                continue

            a_xy = plan.pin_xy(pin_a)
            b_xy = plan.pin_xy(pin_b)
            collision_hits = foreign_pins_on_jumper(
                plan, (a_xy, b_xy), exclude_pin_refs=(pin_a, pin_b)
            )

            # Disqualify on collision when the penalty outweighs savings.
            wire_cost = weights.wire_cost_for(klass)
            via_value = score.vias_saved * weights.via_cost
            collision_cost = len(collision_hits) * weights.jumper_collision_penalty
            effective_value = score.wire_saved_mm * wire_cost + via_value - collision_cost
            if collision_hits and effective_value <= 0:
                doc.declined.append({
                    "bus": bus_name,
                    "signal": net.name,
                    "participants": [pin_a, pin_b],
                    "reason": "collision_penalty_exceeds_savings",
                    "jumper_through_pins": [h.pin_ref for h in collision_hits],
                })
                continue

            proposal: dict[str, Any] = {
                "bus": bus_name,
                "signal": net.name,
                "participants": [pin_a, pin_b],
                "wire_saved_mm": round(score.wire_saved_mm, 2),
                "vias_saved": score.vias_saved,
                "disposition": "auto_merge_with_droop_note" if verdict.droop_warning else "auto_merge",
            }
            if collision_hits:
                proposal["collision_risk"] = {
                    "jumper_through_pin": collision_hits[0].pin_ref,
                    "remediations": list(REMEDIATIONS),
                }
            doc.proposals.append(proposal)
            total_wire_saved += score.wire_saved_mm
            total_vias_saved += score.vias_saved

    doc.metrics = {
        "topology": topology_override or "per_signal",
        "total_wire_mm_before": round(before.total_wire_mm, 2),
        "total_wire_mm_after": round(before.total_wire_mm - total_wire_saved, 2),
        "total_vias_before": before.total_vias,
        "total_vias_after": before.total_vias - total_vias_saved,
    }

    # Bundled-mode metric block — emitted when ANY bus is set to bundled
    # (directly or via override).
    bundled_metrics: dict[str, Any] = {}
    for bus in weights.buses.values():
        eff = topology_override or bus.topology
        if eff != "bundled":
            continue
        if bus.signal_class not in IMPLEMENTED_CLASSES:
            continue
        m = bundled_bus_metric(plan, bus, weights=weights)
        if m is None:
            continue
        bundled_metrics[bus.name] = {
            "visit_order": list(m.visit_order),
            "conductors": list(m.conductors),
            "total_wire_mm": round(m.total_wire_mm, 2),
            "total_vias": m.total_vias,
            "termination": None,
        }
    if bundled_metrics:
        doc.metrics_alternative = {
            "topology": "bundled",
            "buses": bundled_metrics,
        }

    return doc


def _cross_module_pairs(plan: ParsedPlan, net: NetEndpoints):
    """Yield (pin_a, pin_b, module_a, module_b) for every pin pair on
    different modules. Pin pairs on the same column are skipped."""
    refs_with_modules = []
    for ref in net.pin_refs:
        anchor = None
        col = ref.split(".")[0]
        anchor = plan.module_by_column(col)
        if anchor is None:
            continue
        refs_with_modules.append((ref, _module_key_for(anchor)))
    for (a, ma), (b, mb) in combinations(refs_with_modules, 2):
        if ma == mb:
            continue
        yield (a, b, ma, mb)
