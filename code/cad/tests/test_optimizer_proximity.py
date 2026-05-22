"""Module-centre proximity + stack overlap."""

from __future__ import annotations

from optimizer.plan_parser import (
    ModuleAnchor,
    NetEndpoints,
    ParsedPlan,
    Pocket,
)
from optimizer.proximity import centre_to_centre_mm, stacks_overlap


def _mk_plan(modules, pockets=()):
    return ParsedPlan(
        source_path="<test>",
        board_name="synthetic",
        modules=tuple(modules),
        nets=(),
        pockets=tuple(pockets),
        through_holes=(),
        net_routings=(),
    )


def test_centre_to_centre_under_threshold():
    plan = _mk_plan(
        modules=[],
        pockets=[
            Pocket(module="A", centre=(0.0, 0.0)),
            Pocket(module="B", centre=(10.0, 0.0)),
        ],
    )
    assert centre_to_centre_mm(plan, "A", "B") == 10.0


def test_centre_to_centre_over_threshold():
    plan = _mk_plan(
        modules=[],
        pockets=[
            Pocket(module="A", centre=(0.0, 0.0)),
            Pocket(module="B", centre=(40.0, 0.0)),
        ],
    )
    assert centre_to_centre_mm(plan, "A", "B") == 40.0


def test_stack_overlap_true_when_cantilevers_overlap():
    plan = _mk_plan(
        modules=[],
        pockets=[
            Pocket(module="OLED", centre=(0.0, -22.0),
                   cantilever_xy_bounds=(-13.5, 13.5, -49.0, -22.0)),
            Pocket(module="SCD41", centre=(8.81, -17.0), width_mm=14.0, height_mm=12.0),
        ],
    )
    assert stacks_overlap(plan, "OLED", "SCD41") is True


def test_stack_overlap_false_when_apart():
    plan = _mk_plan(
        modules=[],
        pockets=[
            Pocket(module="A", centre=(0.0, 0.0), width_mm=5.0, height_mm=5.0),
            Pocket(module="B", centre=(50.0, 50.0), width_mm=5.0, height_mm=5.0),
        ],
    )
    assert stacks_overlap(plan, "A", "B") is False
