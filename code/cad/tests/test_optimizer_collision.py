"""Jumper-line through foreign-pin detection."""

from __future__ import annotations

from optimizer.collision import foreign_pins_on_jumper
from optimizer.plan_parser import ParsedPlan, ThroughHole


def _mk_plan(holes):
    return ParsedPlan(
        source_path="<test>",
        board_name="synthetic",
        modules=(),
        nets=(),
        pockets=(),
        through_holes=tuple(holes),
        net_routings=(),
    )


def test_jumper_through_pin_is_flagged():
    plan = _mk_plan([
        ThroughHole(xy=(5.0, -17.0), pin_ref="J2.1", net="vcc", diameter=1.0),
        ThroughHole(xy=(7.54, -17.0), pin_ref="J2.2", net="gnd", diameter=1.0),
        ThroughHole(xy=(1.27, -22.0), pin_ref="J4.3", net="vcc", diameter=1.25),
    ])
    # Jumper from SCD41.J2.2 (GND) to OLED.J4.4 — passes near J2.1 if it
    # routes along y=-17 then south. Test the straight-line case from
    # J2.2 (7.54, -17) → would-be J4.4 (3.81, -22): not straight-through
    # J2.1 unless we go via y=-17. Simulate the "via y=-17" case:
    hits = foreign_pins_on_jumper(
        plan,
        ((7.54, -17.0), (1.27, -17.0)),   # west jumper along y=-17
        exclude_pin_refs=["J2.2"],
    )
    pin_refs = {h.pin_ref for h in hits}
    assert "J2.1" in pin_refs


def test_jumper_clear_of_pins():
    plan = _mk_plan([
        ThroughHole(xy=(100.0, 100.0), pin_ref="J9.1", net="foo", diameter=1.0),
    ])
    hits = foreign_pins_on_jumper(plan, ((0.0, 0.0), (10.0, 0.0)))
    assert hits == []
