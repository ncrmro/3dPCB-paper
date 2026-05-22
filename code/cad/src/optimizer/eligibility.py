"""Eligibility — turn (net, weights, topology) into a Yes/No + reason.

The resolution order is class rule → bus rule (topology) →
per-device override. The conditional `bus_broadcast` rule is the
interesting one: it declines in `per_signal` topology and is subsumed
(no per-pair proposals) in `bundled` topology — bundled mode emits a
single bus-level metric instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .signal_class import SignalClass
from .weights import BusSpec, Weights


@dataclass(frozen=True)
class EligibilityVerdict:
    eligible: bool
    droop_warning: bool = False
    reason: Optional[str] = None      # set when eligible=False
    subsumed_by_bus: Optional[str] = None  # when bundled topology absorbs the signal


# Map a net's *name* (lowercase) to its signal class via the weights'
# bus declarations. Anything unmatched falls through to SINGLETON.
def classify_net(net_name: str, weights: Weights) -> tuple[SignalClass, Optional[str]]:
    """Return (SignalClass, bus_name) for a net by its name."""
    n = _normalize(net_name)
    for bus in weights.buses.values():
        if n in {s.lower() for s in bus.signals}:
            return (bus.signal_class, bus.name)
        if n in {s.lower() for s in bus.power_signals}:
            # Power signals riding alongside a bus_broadcast bus are
            # still POWER_RAIL / GROUND class — their mergeability is
            # governed by their own class, not the bus's.
            klass = SignalClass.GROUND if n in {"gnd", "ground"} else SignalClass.POWER_RAIL
            return (klass, bus.name)
    # Unmatched names: best-effort name-based guess
    if n in {"gnd", "ground"}:
        return (SignalClass.GROUND, None)
    if n in {"vcc", "+3v3", "3v3", "5v", "vbat", "vbus", "vin"}:
        return (SignalClass.POWER_RAIL, None)
    return (SignalClass.SINGLETON, None)


def _normalize(name: str) -> str:
    return name.strip().strip("`").lower()


def evaluate_pair(
    *,
    net_name: str,
    klass: SignalClass,
    bus_name: Optional[str],
    weights: Weights,
    topology_override: Optional[str] = None,
    module_a: str,
    module_b: str,
) -> EligibilityVerdict:
    """Apply class → bus → per-device rules to a candidate pair."""
    rule = weights.class_rules[klass]
    bus = weights.buses.get(bus_name) if bus_name else None
    topology = topology_override or (bus.topology if bus else "per_signal")

    # Per-device override (signal-class keyed) takes the highest precedence.
    for module in (module_a, module_b):
        ov = (weights.per_device_overrides.get(module) or {}).get(klass.value)
        if ov:
            mergeable = str(ov.get("mergeable", "true")).lower() in {"true", "1", "yes"}
            if not mergeable:
                return EligibilityVerdict(
                    eligible=False,
                    reason=ov.get("reason", f"per_device_{module}_override"),
                )

    token = rule.mergeable_token.lower()
    if token == "true":
        return EligibilityVerdict(eligible=True, droop_warning=rule.droop_warning)
    if token == "false":
        return EligibilityVerdict(eligible=False, reason=rule.reason)
    if token == "conditional":
        if klass == SignalClass.BUS_BROADCAST:
            if topology == "bundled":
                return EligibilityVerdict(
                    eligible=False,
                    subsumed_by_bus=bus_name,
                    reason="subsumed_by_bundled_bus",
                )
            return EligibilityVerdict(
                eligible=False,
                reason=rule.reason_when_declined or "conditional_declined",
            )
        return EligibilityVerdict(eligible=True, droop_warning=rule.droop_warning)
    if token == "as_pair":
        # Differential pairs — not implemented at runtime day one.
        return EligibilityVerdict(
            eligible=False,
            reason=rule.reason_when_declined or "pair_atomic_not_implemented",
        )
    return EligibilityVerdict(eligible=False, reason=f"unknown_rule_token_{token}")
