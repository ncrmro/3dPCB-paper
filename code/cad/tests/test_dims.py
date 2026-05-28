"""Golden-output guard for the dimension consolidation.

The breadboard-canonical refactor (docs/specs/breadboard-canonical-substrate)
collapses the scattered clearance family into a single `buffer` knob plus
derived accessors on `ResolvedDims`. Phase 1 is *behavior-preserving*: every
derived accessor must reproduce its pre-consolidation numeric value. These
assertions lock that in so a later value change can't silently regress Phase 1.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from board import DEVICE_REGISTRY, Board, DeviceInstance, Level, Point2D, Rect
from board.board import DimOverrides
from board.build import _DEFAULTS, resolve_dims

_A_DEVICE = next(iter(DEVICE_REGISTRY))


def _minimal_board(dim: DimOverrides | None = None) -> Board:
    return Board(
        name="dimtest",
        levels=(Level(name="base", perimeter=Rect(cx=0, cy=0, w=40, h=30),
                      z_start=0.0, z_end=2.0),),
        devices=(DeviceInstance(name="u1", device=_A_DEVICE,
                                position=Point2D(x=0, y=0)),),
        dim=dim or DimOverrides(),
    )


def test_buffer_and_pitch_defaults():
    assert _DEFAULTS["buffer"] == 0.6
    assert _DEFAULTS["pitch"] == 2.54


def test_derived_accessors_reproduce_legacy_values():
    dims = resolve_dims(_minimal_board())
    # Values that previously lived as duplicated literals/formulas across
    # build/grid/blocking/score/align/cli_report.
    assert dims.wall_floor_mm == pytest.approx(1.4)          # 0.8 + 0.6
    assert dims.wall_halo_mm(0.5) == pytest.approx(1.15)     # 0.8 + 0.6 - 0.25
    assert dims.via_halo_mm == pytest.approx(1.35)           # 1.5/2 + 0.6
    assert dims.edge_inflate_mm == pytest.approx(1.0)        # 0.8/2 + 0.6
    assert dims.pocket_margin_mm == pytest.approx(0.7)       # 0.3 + 0.8/2
    assert dims.hole_bore_mm == pytest.approx(1.0)           # hole_diameter


def test_buffer_override_propagates_to_derivations():
    dims = resolve_dims(_minimal_board(DimOverrides(buffer=1.0)))
    assert dims.buffer == 1.0
    assert dims.wall_floor_mm == pytest.approx(1.8)          # 0.8 + 1.0
    assert dims.via_halo_mm == pytest.approx(1.75)           # 0.75 + 1.0


def test_removed_knobs_are_rejected():
    # The dead `hole_pair_clearance` and the renamed `min_wall_thickness`
    # must no longer be accepted (DimOverrides is extra="forbid").
    with pytest.raises(ValidationError):
        DimOverrides(hole_pair_clearance=1.2)
    with pytest.raises(ValidationError):
        DimOverrides(min_wall_thickness=0.6)
