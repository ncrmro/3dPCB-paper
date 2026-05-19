"""Tests for the greedy routing-hint optimiser.

Three behaviours we care about:

1. **Smoke**: the optimiser converges on a hint set for PRIMARY_BUS
   and the resulting geometry passes the same collision checks the
   hand-authored ROUTING already passes.
2. **Determinism**: same inputs → same outputs (no hash-order or
   set-iteration drift in the search loop).
3. **Constraint sensitivity**: drop a hand-placed foreign pin into a
   corridor and the optimiser routes around it (or fails loudly with
   `OptimiserError`).
"""

from __future__ import annotations

import math

import pytest

from netlist import (
    I2cSignal,
    Net,
    PRIMARY_BUS,
    Pin,
    RoutingHint,
)
from router.collisions import (
    all_through_holes,
    bboxes_overlap,
    module_pocket_bboxes,
    net_pin_keys,
    pin_key,
    segment_bbox,
    segment_pierces_hole,
    segments_collide,
    via_in_pocket,
    via_overlaps_hole,
)
from router.optimiser import (
    OptimisationResult,
    OptimiserError,
    SearchGrid,
    optimise_routing,
    path_length_mm,
)
from vitamins.esp32_pinout import J1A_PINOUT, J1B_PINOUT
from vitamins.oled_ssd1306_pinout import OLED_PINOUT
from vitamins.sensors_pinout import BH1750_PINOUT, SCD41_PINOUT
from vitamins.substrate import (
    Point2D,
    Tier1SubstrateDimensions,
    Via,
    WireSegment,
    _build_paths_for_net,
)


# Use a coarser grid in tests so the suite stays fast (~1s per run).
# The 1.0 mm step covers all the corridor values the hand-authored
# ROUTING uses (-29, -27, -11, -9 and 6, 9, 12, 15) and is still fine
# enough that the optimiser finds collision-free hints for all four
# nets.
_TEST_GRID = SearchGrid(
    north_x_min=-29.0,
    north_x_max=28.0,
    north_x_step=1.0,
    corridor_y_min=6.0,
    corridor_y_max=20.0,
    corridor_y_step=1.0,
)

_DEVICES = {
    "SCD41": SCD41_PINOUT,
    "BH1750": BH1750_PINOUT,
    "OLED": OLED_PINOUT,
}
_MASTER_COLUMNS = {"J1A": J1A_PINOUT, "J1B": J1B_PINOUT}


def _run(extra_foreign_holes=None) -> OptimisationResult:
    return optimise_routing(
        PRIMARY_BUS,
        master_columns=_MASTER_COLUMNS,
        devices=_DEVICES,
        grid=_TEST_GRID,
        extra_foreign_holes=extra_foreign_holes,
    )


def _net_from_hint(sig: I2cSignal, hint: RoutingHint) -> Net:
    # Look up the pins on PRIMARY_BUS the way `_assemble_nets` does.
    master_pin = None
    for col in PRIMARY_BUS.master_columns:
        for p in _MASTER_COLUMNS[col].values():
            if p.signal == sig:
                master_pin = p
    assert master_pin is not None
    device_pins = []
    for dev in PRIMARY_BUS.devices:
        for p in _DEVICES[dev].values():
            if p.signal == sig:
                device_pins.append(p)
                break
    return Net(
        signal=sig,
        master_pin=master_pin,
        device_pins=tuple(device_pins),
        north_x=hint.north_x,
        corridor_y=hint.corridor_y,
        scd_east_on_l2=hint.scd_east_on_l2,
        branch_east_on_l2=hint.branch_east_on_l2,
    )


def _all_elements(hints: dict[I2cSignal, RoutingHint]) -> list[tuple[I2cSignal, object]]:
    out: list[tuple[I2cSignal, object]] = []
    for sig in PRIMARY_BUS.signals:
        net = _net_from_hint(sig, hints[sig])
        for path in _build_paths_for_net(net):
            for el in path.elements:
                out.append((sig, el))
    return out


# ---------------------------------------------------------------------------
# Smoke + collision-clean result
# ---------------------------------------------------------------------------


def test_optimiser_converges_on_primary_bus() -> None:
    """The optimiser returns one `RoutingHint` per bus signal."""
    result = _run()
    assert set(result.hints) == set(PRIMARY_BUS.signals)
    assert result.total_length_mm > 0
    assert result.candidates_considered > 0


def test_optimised_hints_pass_all_collision_gates() -> None:
    """Building the bus with the optimiser's hints produces geometry
    that passes the same four checks the netlist test gate runs.
    """
    result = _run()
    elements = _all_elements(result.hints)

    dim = Tier1SubstrateDimensions()
    cw = dim.channel_width
    hole_r = dim.hole_diameter / 2
    via_r = dim.via_diameter / 2
    holes = all_through_holes()
    pockets = module_pocket_bboxes(dim)

    # (a) same-layer wire overlap between different nets
    for i, (sig_a, el_a) in enumerate(elements):
        if not isinstance(el_a, WireSegment):
            continue
        for sig_b, el_b in elements[i + 1:]:
            if not isinstance(el_b, WireSegment) or sig_a == sig_b:
                continue
            assert not segments_collide(el_a, el_b, cw), (
                f"{sig_a.name} L{el_a.layer} {el_a.start}-{el_a.end} "
                f"overlaps {sig_b.name} {el_b.start}-{el_b.end}"
            )

    # (b) no segment pierces a foreign hole
    for sig, el in elements:
        if not isinstance(el, WireSegment):
            continue
        endpoints = net_pin_keys(_net_from_hint(sig, result.hints[sig]))
        for pin, pos in holes:
            if pin_key(pos) in endpoints:
                continue
            assert not segment_pierces_hole(el, pos, cw, hole_r), (
                f"{sig.name} L{el.layer} {el.start}-{el.end} pierces "
                f"{pin.ref}.{pin.number}"
            )

    # (c) no via in pocket
    for sig, el in elements:
        if not isinstance(el, Via):
            continue
        for module_name, pocket in pockets.items():
            assert not via_in_pocket(el, pocket, via_r), (
                f"{sig.name} via at {el.position} inside {module_name}"
            )

    # (d) no via on foreign hole
    for sig, el in elements:
        if not isinstance(el, Via):
            continue
        endpoints = net_pin_keys(_net_from_hint(sig, result.hints[sig]))
        for pin, pos in holes:
            if pin_key(pos) in endpoints:
                continue
            assert not via_overlaps_hole(el, pos, via_r, hole_r), (
                f"{sig.name} via at {el.position} overlaps "
                f"{pin.ref}.{pin.number}"
            )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_optimiser_is_deterministic() -> None:
    """Two runs with the same inputs produce identical results."""
    a = _run()
    b = _run()
    assert a.hints == b.hints
    assert a.per_net_length_mm == b.per_net_length_mm
    assert math.isclose(a.total_length_mm, b.total_length_mm)


# ---------------------------------------------------------------------------
# Constraint sensitivity
# ---------------------------------------------------------------------------


def test_optimiser_routes_around_blocked_corridor() -> None:
    """Drop a hand-placed foreign pin onto the VCC corridor the
    unblocked optimiser chose, then re-run and assert the new VCC
    corridor avoids that y."""
    baseline = _run()
    vcc_hint_baseline = baseline.hints[I2cSignal.VCC]
    blocked_y = vcc_hint_baseline.corridor_y

    # Place a fake pin near the centre of VCC's chosen corridor,
    # east enough that VCC's east-sweeping corridor would have to
    # pass through it. Block_x picked so it's east of GND/VCC's
    # north_x but west of the easternmost device — i.e. on the
    # corridor's main sweep.
    block_pos = Point2D(x=0.0, y=blocked_y)
    fake_pin = Pin(ref="BLOCK", number=99, function="OBSTRUCTION")
    blocker = [(fake_pin, block_pos)]

    blocked = _run(extra_foreign_holes=blocker)
    vcc_hint_blocked = blocked.hints[I2cSignal.VCC]

    # The optimiser MUST have moved at least one of VCC's corridor
    # parameters off the blocked row (corridor_y or scd_east_on_l2 —
    # the latter sends VCC's corridor to L2 leaving L1 free, but the
    # foreign hole is layer-agnostic, so layer swap alone wouldn't
    # help; corridor_y must change).
    assert vcc_hint_blocked.corridor_y != blocked_y, (
        f"VCC corridor still at y={blocked_y} despite blocker at "
        f"{block_pos}"
    )

    # The new layout still satisfies the collision gate.
    elements = _all_elements(blocked.hints)
    dim = Tier1SubstrateDimensions()
    cw = dim.channel_width
    hole_r = dim.hole_diameter / 2
    holes = all_through_holes(extra=blocker)
    for sig, el in elements:
        if not isinstance(el, WireSegment):
            continue
        endpoints = net_pin_keys(_net_from_hint(sig, blocked.hints[sig]))
        for pin, pos in holes:
            if pin_key(pos) in endpoints:
                continue
            assert not segment_pierces_hole(el, pos, cw, hole_r), (
                f"{sig.name} pierces blocker/foreign pin at {pos}"
            )


def test_optimiser_raises_when_no_layout_fits() -> None:
    """Wall the board off with a row of obstacles spanning every
    corridor_y the grid considers — the optimiser must raise rather
    than silently emit a broken plan.
    """
    # One blocker per corridor_y at x=0 — that's exactly on every
    # candidate corridor's east-sweep path through the centre of
    # the board, so no candidate can survive.
    blockers: list[tuple[Pin, Point2D]] = []
    for cy in _TEST_GRID.corridor_ys():
        blockers.append((
            Pin(ref="WALL", number=int(cy * 10), function="WALL"),
            Point2D(x=0.0, y=cy),
        ))

    with pytest.raises(OptimiserError):
        _run(extra_foreign_holes=blockers)
