"""Greedy routing-hint optimiser.

Given a `Bus` and the pinouts of its master + devices, enumerate every
`(north_x, corridor_y, scd_east_on_l2)` triple in a small grid, build
the resulting `SignalPath`, and keep the shortest collision-free hint
per net. Nets are committed one at a time in iteration order — later
nets see earlier nets' geometry as fixed obstacles.

Scope is intentionally narrow: parameter enumeration, not maze
routing. The grid is small enough (~10⁴ candidates per net) for
brute-force; if it grows we can swap in a cheaper search without
changing the data model.

Wire-length scoring is computed inline as a Manhattan sum + via
penalty so this module doesn't depend on the parallel
`feat/wire-cut-list` PR's `SignalPath.length_mm` method. When that PR
lands the two implementations can be reconciled — the values agree
modulo the per-via penalty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from netlist import (
    Bus,
    I2cSignal,
    Net,
    Pin,
    RoutingHint,
)
from router.collisions import (
    all_through_holes,
    module_pocket_bboxes,
    path_collides,
)
from vitamins.substrate import (
    Point2D,
    Tier1SubstrateDimensions,
    Via,
    WireSegment,
    _build_paths_for_net,
)


# ---------------------------------------------------------------------------
# Search grid + scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchGrid:
    """Discretised search space over the `RoutingHint` knobs.

    Defaults cover the board interior with 0.5 mm steps — small enough
    to capture every clearance-sensitive value the hand-authored
    ROUTING uses, large enough that the brute-force enumeration runs
    in well under a second per net.
    """
    north_x_min: float = -29.5
    north_x_max: float = 30.0
    north_x_step: float = 0.5
    corridor_y_min: float = 6.0
    corridor_y_max: float = 24.0
    corridor_y_step: float = 0.5

    def north_xs(self) -> list[float]:
        return _frange(self.north_x_min, self.north_x_max, self.north_x_step)

    def corridor_ys(self) -> list[float]:
        return _frange(
            self.corridor_y_min, self.corridor_y_max, self.corridor_y_step
        )


def _frange(lo: float, hi: float, step: float) -> list[float]:
    out: list[float] = []
    n = int(round((hi - lo) / step)) + 1
    for i in range(n):
        out.append(round(lo + i * step, 4))
    return out


# Per-via cost in the scoring function. Each via has both a fabrication
# cost (an extra hole to drill / wire to thread) and a small wire-
# length cost (the wire has to traverse the substrate thickness).
# 5 mm matches the order of magnitude of substrate+pedestal thickness,
# enough that the optimiser prefers fewer vias when wire length is
# close.
_VIA_PENALTY_MM = 5.0


def path_length_mm(elements, via_penalty_mm: float = _VIA_PENALTY_MM) -> float:
    """Manhattan sum over `WireSegment`s + per-`Via` penalty.

    Independent of the parallel `feat/wire-cut-list` PR's
    `SignalPath.length_mm` so this module stands on its own. When
    both land, reconcile to one implementation.
    """
    total = 0.0
    for el in elements:
        if isinstance(el, WireSegment):
            total += abs(el.end.x - el.start.x) + abs(el.end.y - el.start.y)
        elif isinstance(el, Via):
            total += via_penalty_mm
    return total


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


class OptimiserError(RuntimeError):
    """No candidate hint survived the collision filter for some net."""


@dataclass
class OptimisationResult:
    hints: dict[I2cSignal, RoutingHint]
    per_net_length_mm: dict[I2cSignal, float]
    total_length_mm: float
    candidates_considered: int


def optimise_routing(
    bus: Bus,
    master_columns: dict[str, dict[int, Pin]],
    devices: dict[str, dict[int, Pin]],
    *,
    grid: Optional[SearchGrid] = None,
    dim: Optional[Tier1SubstrateDimensions] = None,
    extra_foreign_holes: Optional[list[tuple[Pin, Point2D]]] = None,
    via_penalty_mm: float = _VIA_PENALTY_MM,
) -> OptimisationResult:
    """Optimise routing hints by outer-product enumeration of layer
    choices + inner greedy on (north_x, corridor_y).

    Pure greedy on the full `(north_x, corridor_y, scd_east_on_l2)`
    grid is fragile: the very first net (typically VCC) picks its
    locally-shortest L1 corridor, which then forms an east-west wall
    that blocks every subsequent net from crossing layers cheaply.
    To sidestep this without resorting to a real maze router, we
    enumerate all 2^|signals| `scd_east_on_l2` assignments as an
    outer loop and run a per-(north_x, corridor_y) greedy inside.
    Pick the whole-bus winner.

    For each layer-pattern in `{False, True}^|bus.signals|`:

      1. In `bus.signals` order, for each net:
         a. Enumerate every `(north_x, corridor_y)` in the grid with
            the pattern's fixed `scd_east_on_l2`.
         b. Score the collision-free survivors by
            `path_length_mm` (Manhattan + per-via penalty) and
            commit the shortest.
         c. If no candidate survives, abandon this layer-pattern.

      2. If the whole bus succeeds, total cost = sum of per-net costs.

    Final answer: the layer-pattern with the smallest total cost
    (deterministic tie-break on the layer pattern bits + hint
    tuples).

    `extra_foreign_holes` is used by the constraint test to inject a
    hand-placed pin and assert the optimiser routes around it.
    """
    grid = grid or SearchGrid()
    dim = dim or Tier1SubstrateDimensions()

    holes = all_through_holes(extra=extra_foreign_holes)
    pockets = module_pocket_bboxes(dim)

    cw = dim.channel_width
    hole_r = dim.hole_diameter / 2
    via_r = dim.via_diameter / 2

    n_signals = len(bus.signals)
    candidates_considered = 0
    best_overall: Optional[tuple] = None  # (total, pattern, hints, lens)
    last_failure_reason: Optional[str] = None

    for pattern_bits in range(1 << n_signals):
        pattern = [
            bool(pattern_bits & (1 << i)) for i in range(n_signals)
        ]

        chosen_hints: dict[I2cSignal, RoutingHint] = {}
        per_net_len: dict[I2cSignal, float] = {}
        fixed_elements: list[tuple[I2cSignal, object]] = []
        pattern_ok = True

        for i, sig in enumerate(bus.signals):
            scd_l2 = pattern[i]
            best_net: Optional[tuple[float, RoutingHint, list]] = None

            for nx in grid.north_xs():
                for cy in grid.corridor_ys():
                    candidates_considered += 1
                    hint = RoutingHint(
                        north_x=nx,
                        corridor_y=cy,
                        scd_east_on_l2=scd_l2,
                        branch_east_on_l2=scd_l2,
                    )
                    net = _build_candidate_net(
                        bus, sig, hint, master_columns, devices
                    )
                    if net is None:
                        continue
                    paths = _build_paths_for_net(net)
                    elements = [e for p in paths for e in p.elements]
                    reason = path_collides(
                        elements,
                        net,
                        fixed_elements,
                        holes,
                        pockets,
                        channel_width=cw,
                        hole_radius=hole_r,
                        via_radius=via_r,
                    )
                    if reason is not None:
                        continue
                    score = path_length_mm(elements, via_penalty_mm)
                    key = (score, nx, cy)
                    if best_net is None:
                        best_net = (score, hint, elements)
                    else:
                        cur = (
                            best_net[0], best_net[1].north_x,
                            best_net[1].corridor_y,
                        )
                        if key < cur:
                            best_net = (score, hint, elements)

            if best_net is None:
                last_failure_reason = (
                    f"pattern {pattern}: net {sig.name} has no "
                    f"collision-free candidate"
                )
                pattern_ok = False
                break

            net_score, net_hint, net_elements = best_net
            chosen_hints[sig] = net_hint
            per_net_len[sig] = net_score
            fixed_elements.extend((sig, el) for el in net_elements)

        if not pattern_ok:
            continue

        total = sum(per_net_len.values())
        cand_key = (total, pattern_bits)
        if best_overall is None or cand_key < (
            best_overall[0], best_overall[1]
        ):
            best_overall = (total, pattern_bits, chosen_hints, per_net_len)

    if best_overall is None:
        raise OptimiserError(
            f"No layer-pattern produced a collision-free bus. "
            f"Last failure: {last_failure_reason}"
        )

    total, _pattern_bits, hints, per_net = best_overall
    return OptimisationResult(
        hints=hints,
        per_net_length_mm=per_net,
        total_length_mm=total,
        candidates_considered=candidates_considered,
    )


def _build_candidate_net(
    bus: Bus,
    sig: I2cSignal,
    hint: RoutingHint,
    master_columns: dict[str, dict[int, Pin]],
    devices: dict[str, dict[int, Pin]],
) -> Optional[Net]:
    """Build a `Net` for one signal under a candidate hint.

    Returns None if the bus participants don't actually carry the
    signal — that's a static configuration error, but inside the hot
    enumeration loop we just skip it rather than raise.
    """
    # Find master pin
    master_pin: Optional[Pin] = None
    for col_name in bus.master_columns:
        pinout = master_columns[col_name]
        matches = [p for p in pinout.values() if p.signal == sig]
        if matches:
            if master_pin is not None:
                return None
            master_pin = matches[0]
    if master_pin is None:
        return None

    # Find device pins
    device_pins: list[Pin] = []
    for dev_name in bus.devices:
        pinout = devices[dev_name]
        matches = [p for p in pinout.values() if p.signal == sig]
        if not matches:
            return None
        device_pins.append(matches[0])

    return Net(
        signal=sig,
        master_pin=master_pin,
        device_pins=tuple(device_pins),
        north_x=hint.north_x,
        corridor_y=hint.corridor_y,
        scd_east_on_l2=hint.scd_east_on_l2,
        branch_east_on_l2=hint.branch_east_on_l2,
    )
