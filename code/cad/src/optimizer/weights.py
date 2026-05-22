"""Weights YAML schema + loader.

Class-based, per-bus, with per-device overrides. The grammar accepts
every signal class enumerated in `signal_class.py`; runtime support
for non-`IMPLEMENTED_CLASSES` shows up as `not_yet_implemented`
warnings rather than errors so users can author forward-compatible
config files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

from .signal_class import (
    DEFAULT_CLASS_RULES,
    IMPLEMENTED_CLASSES,
    ClassRule,
    SignalClass,
)


DEFAULT_WEIGHTS_PATH = os.path.join(
    os.path.dirname(__file__), "weights.default.yaml"
)


@dataclass(frozen=True)
class BusSpec:
    name: str
    signal_class: SignalClass
    signals: tuple[str, ...]
    power_signals: tuple[str, ...] = ()
    topology: str = "per_signal"  # or "bundled"
    max_total_stub_capacitance_pf: Optional[float] = None
    visit_order_start: Optional[str] = None
    visit_order_end: Optional[str] = None
    # Differential / termination knobs — declared in grammar, not
    # actuated at runtime for the bus_broadcast class.
    termination_value_ohm: Optional[float] = None
    termination_at: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProximityWeights:
    max_centre_to_centre_mm: float = 30.0
    stack_overlap_required: bool = False


@dataclass(frozen=True)
class MetricsWeights:
    distance: str = "manhattan"  # or "euclidean"


@dataclass(frozen=True)
class Weights:
    """Loaded + validated weights configuration."""

    class_rules: dict[SignalClass, ClassRule]
    buses: dict[str, BusSpec]
    wire_cost_per_mm: dict[str, float]  # keyed by SignalClass.value or "default"
    via_cost: float
    jumper_collision_penalty: float
    proximity: ProximityWeights
    metrics: MetricsWeights
    per_device_overrides: dict[str, dict[str, dict]] = field(default_factory=dict)

    # Warnings collected during load (parse-time, not runtime).
    warnings: tuple[tuple[str, str], ...] = ()  # (code, detail) pairs

    def wire_cost_for(self, klass: SignalClass) -> float:
        return self.wire_cost_per_mm.get(
            klass.value, self.wire_cost_per_mm.get("default", 1.0)
        )

    def unimplemented_class_warnings(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for bus in self.buses.values():
            if bus.signal_class not in IMPLEMENTED_CLASSES:
                out.append((
                    "not_yet_implemented",
                    f"bus '{bus.name}' has class {bus.signal_class.value} "
                    "which is declared in grammar but not handled this version",
                ))
        return out


def load_weights(path: Optional[str] = None) -> Weights:
    """Load + validate a weights YAML file. `None` → default config."""
    path = path or DEFAULT_WEIGHTS_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return _build_weights(raw)


def _build_weights(raw: dict) -> Weights:
    warnings: list[tuple[str, str]] = []

    # signal_classes: override defaults if present
    class_rules: dict[SignalClass, ClassRule] = dict(DEFAULT_CLASS_RULES)
    for key, body in (raw.get("signal_classes") or {}).items():
        try:
            klass = SignalClass(key)
        except ValueError:
            warnings.append(("parser_warning", f"unknown signal_class '{key}' — ignored"))
            continue
        class_rules[klass] = ClassRule(
            mergeable_token=str(body.get("mergeable", class_rules[klass].mergeable_token)),
            droop_warning=bool(body.get("droop_warning", class_rules[klass].droop_warning)),
            reason=body.get("reason", class_rules[klass].reason),
            reason_when_declined=body.get(
                "reason_when_declined", class_rules[klass].reason_when_declined
            ),
        )

    # buses
    buses: dict[str, BusSpec] = {}
    for name, body in (raw.get("buses") or {}).items():
        klass_raw = body.get("class")
        if klass_raw is None:
            warnings.append(("parser_warning", f"bus '{name}' missing 'class' — skipped"))
            continue
        try:
            klass = SignalClass(klass_raw)
        except ValueError:
            warnings.append((
                "parser_warning",
                f"bus '{name}' has unknown class '{klass_raw}' — skipped",
            ))
            continue
        signals = tuple(body.get("signals") or ())
        power_signals = tuple(body.get("power_signals") or ())
        topology = body.get("topology", "per_signal")
        visit = body.get("visit_order_constraints") or {}
        term = body.get("termination") or {}
        buses[name] = BusSpec(
            name=name,
            signal_class=klass,
            signals=signals,
            power_signals=power_signals,
            topology=topology,
            max_total_stub_capacitance_pf=body.get("max_total_stub_capacitance_pf"),
            visit_order_start=visit.get("start"),
            visit_order_end=visit.get("end"),
            termination_value_ohm=term.get("value_ohm") if isinstance(term, dict) else None,
            termination_at=tuple(term.get("at") or ()) if isinstance(term, dict) else (),
        )

    # cost model
    wire_cost = raw.get("wire_cost_per_mm") or {}
    if not wire_cost:
        wire_cost = {"default": 1.0}
    wire_cost = {str(k): float(v) for k, v in wire_cost.items()}

    proximity_raw = raw.get("proximity") or {}
    proximity = ProximityWeights(
        max_centre_to_centre_mm=float(proximity_raw.get("max_centre_to_centre_mm", 30.0)),
        stack_overlap_required=bool(proximity_raw.get("stack_overlap_required", False)),
    )

    metrics_raw = raw.get("metrics") or {}
    metrics = MetricsWeights(distance=str(metrics_raw.get("distance", "manhattan")))

    per_device_overrides = raw.get("per_device_overrides") or {}

    return Weights(
        class_rules=class_rules,
        buses=buses,
        wire_cost_per_mm=wire_cost,
        via_cost=float(raw.get("via_cost", 3.0)),
        jumper_collision_penalty=float(raw.get("jumper_collision_penalty", 50.0)),
        proximity=proximity,
        metrics=metrics,
        per_device_overrides=per_device_overrides,
        warnings=tuple(warnings),
    )
