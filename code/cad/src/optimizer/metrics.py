"""Scoring + bundled-topology TSP.

Per-signal metric:
  - wire_saved_mm = displaced-tail length − jumper length
  - vias_saved   = vias on the displaced tail (typically 1)
  - cost factors in via_cost + jumper_collision_penalty when a foreign
    pin gets crossed

Bundled metric (per bus):
  - enumerate every permutation of the device visit order subject to
    any `visit_order_constraints`, score by sum of pairwise centres
    along the order × conductor count, pick the minimum
  - total_vias = 0 (assumption: bundle stays on L1 in parallel grooves)
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Optional

from .plan_parser import NetRouting, ParsedPlan
from .proximity import _module_key_for, centre_to_centre_mm, module_centre
from .weights import BusSpec, Weights


def manhattan(a: tuple[float, float], b: tuple[float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def distance(a, b, *, weights: Weights) -> float:
    if weights.metrics.distance == "euclidean":
        return euclidean(a, b)
    return manhattan(a, b)


# --- Per-signal "before" metrics ---------------------------------------------


@dataclass(frozen=True)
class BeforeMetrics:
    total_wire_mm: float
    total_vias: int
    per_net_wire_mm: dict[str, float]
    per_net_vias: dict[str, int]


def before_metrics(plan: ParsedPlan) -> BeforeMetrics:
    per_net_wire: dict[str, float] = {}
    per_net_vias: dict[str, int] = {}
    for routing in plan.net_routings:
        per_net_wire[routing.name] = routing.total_wire_mm()
        per_net_vias[routing.name] = len(routing.vias)
    return BeforeMetrics(
        total_wire_mm=sum(per_net_wire.values()),
        total_vias=sum(per_net_vias.values()),
        per_net_wire_mm=per_net_wire,
        per_net_vias=per_net_vias,
    )


# --- Pairwise merge scoring --------------------------------------------------


@dataclass(frozen=True)
class MergeScore:
    wire_saved_mm: float
    vias_saved: int


def score_pairwise_merge(
    plan: ParsedPlan,
    *,
    net_name: str,
    pin_a: str,
    pin_b: str,
    weights: Weights,
) -> Optional[MergeScore]:
    """Estimate wire/vias saved by replacing two tails with one jumper.

    `wire_before` is the sum of the segment lengths attached to the
    two specific pin tails (the south legs in spike_v2's geometry).
    `wire_after` is the jumper distance between the two pins. Anything
    where the existing south-leg-pair structure isn't recognizable
    returns None — the optimizer treats those as not-worth-merging
    rather than guessing.
    """
    a_xy = plan.pin_xy(pin_a)
    b_xy = plan.pin_xy(pin_b)
    if a_xy is None or b_xy is None:
        return None

    canon = _canonical_net_name(net_name)
    routing = next(
        (r for r in plan.net_routings if r.name.lower() == canon), None
    )
    if routing is None:
        return None

    tail_a = _tail_segments_ending_at(routing, a_xy)
    tail_b = _tail_segments_ending_at(routing, b_xy)
    if not tail_a or not tail_b:
        return None

    wire_before = sum(s.length_mm() for s in tail_a) + sum(s.length_mm() for s in tail_b)
    wire_jumper = distance(a_xy, b_xy, weights=weights)
    # Heuristic: a merge keeps the *shorter* tail and replaces the *longer*
    # tail with the jumper. Wire saved = max_tail − jumper.
    longer_tail = max(sum(s.length_mm() for s in tail_a),
                      sum(s.length_mm() for s in tail_b))
    wire_saved = longer_tail - wire_jumper

    # Vias saved: one via per displaced tail's southbound L1 leg
    # (matches the spike_v2 wire/via structure). For the bus_broadcast
    # power signals (vcc/gnd) that always have a southbound via on the
    # tail, 1 via per merge is the right baseline.
    vias_saved = 1 if any(_segment_is_southbound(s) for s in tail_a + tail_b) else 0

    return MergeScore(wire_saved_mm=wire_saved, vias_saved=vias_saved)


_NET_NAME_ALIASES = {
    "+3v3": "vcc", "3v3": "vcc", "vcc": "vcc",
    "gnd": "gnd", "ground": "gnd",
    "scl": "scl", "sda": "sda",
}


def _canonical_net_name(name: str) -> str:
    n = name.strip().strip("`").lower()
    return _NET_NAME_ALIASES.get(n, n)


def _tail_segments_ending_at(routing: NetRouting, pin_xy: tuple[float, float]):
    tol = 0.05
    return [
        s for s in routing.segments
        if (abs(s.end[0] - pin_xy[0]) < tol and abs(s.end[1] - pin_xy[1]) < tol)
        or (abs(s.start[0] - pin_xy[0]) < tol and abs(s.start[1] - pin_xy[1]) < tol)
    ]


def _segment_is_southbound(seg) -> bool:
    return seg.layer == 1 and abs(seg.start[0] - seg.end[0]) < 0.05 and seg.end[1] < seg.start[1]


# --- Bundled topology --------------------------------------------------------


@dataclass(frozen=True)
class BundledBusMetric:
    bus: str
    visit_order: tuple[str, ...]
    conductors: tuple[str, ...]
    total_wire_mm: float
    total_vias: int


def bundled_bus_metric(
    plan: ParsedPlan,
    bus: BusSpec,
    *,
    weights: Weights,
) -> Optional[BundledBusMetric]:
    """Enumerate every device-visit permutation under the bus's
    visit_order_constraints; pick the one with minimum total wire."""
    devices = sorted({
        _module_key_for(m) for m in plan.modules
        if _module_key_for(m) != "ESP32"
    })
    if not devices:
        return None

    start = bus.visit_order_start or "ESP32"
    end = bus.visit_order_end

    best_order: Optional[tuple[str, ...]] = None
    best_wire = float("inf")
    for perm in permutations(devices):
        if end is not None and perm[-1] != end:
            continue
        order = (start,) + perm
        try:
            total = sum(
                centre_to_centre_mm(plan, order[i], order[i + 1])
                for i in range(len(order) - 1)
            )
        except KeyError:
            continue
        if total < best_wire:
            best_wire = total
            best_order = order

    if best_order is None:
        return None
    conductors = tuple(list(bus.signals) + list(bus.power_signals))
    return BundledBusMetric(
        bus=bus.name,
        visit_order=best_order,
        conductors=conductors,
        total_wire_mm=best_wire * max(len(conductors), 1),
        total_vias=0,
    )
