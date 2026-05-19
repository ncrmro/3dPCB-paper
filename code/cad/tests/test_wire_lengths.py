"""Per-net wire-length sanity tests for the routed substrate.

Guards against silent breakage of `SignalPath.length_mm` (e.g. forgetting
to count vias, swapping Manhattan for Euclidean, off-by-one on segments).
The "wildly broken" bound is intentionally loose — it's a tripwire, not
a tight spec.
"""

from __future__ import annotations

import math

import pytest

from netlist import NETS, PRIMARY_BUS, I2cSignal
from vitamins.substrate import (
    Tier1SubstrateDimensions,
    Via,
    WireSegment,
    _VIA_WIRE_EXTENT_MM,
    _build_paths_for_net,
)


_DIM = Tier1SubstrateDimensions()

# Board diagonal sets an order-of-magnitude floor on what counts as
# "absurdly long". A single net with 4 vias + a full lap around the
# board would be ~10*4 + 2*(80+50) = 300 mm; we allow up to 350 mm so
# any future device that needs a wider sweep doesn't trip the tripwire,
# while a forgotten *= 10 or sum-over-paths-twice still fails loud.
_BOARD_DIAGONAL = math.hypot(_DIM.board_w, _DIM.board_h)
_MAX_NET_LENGTH_MM = 350.0


@pytest.mark.parametrize("sig", list(PRIMARY_BUS.signals))
def test_net_length_positive(sig: I2cSignal) -> None:
    """Every routed net consumes at least some wire."""
    net = NETS[sig]
    paths = _build_paths_for_net(net)
    total = sum(p.length_mm() for p in paths)
    assert total > 0, f"Net {sig.name}: length {total} is not positive"


@pytest.mark.parametrize("sig", list(PRIMARY_BUS.signals))
def test_net_length_under_sanity_bound(sig: I2cSignal) -> None:
    """No single net should require more wire than a small multiple of
    the board diagonal — if it does, the geometry or the length
    calculation is broken."""
    net = NETS[sig]
    paths = _build_paths_for_net(net)
    total = sum(p.length_mm() for p in paths)
    assert total < _MAX_NET_LENGTH_MM, (
        f"Net {sig.name}: length {total:.2f} mm exceeds sanity bound "
        f"{_MAX_NET_LENGTH_MM} mm (board diagonal {_BOARD_DIAGONAL:.2f} mm)"
    )


def test_length_matches_manual_sum() -> None:
    """Hand-recomputed Manhattan + via sum agrees with `length_mm` for
    the VCC net. Pins the formula so a future refactor of `length_mm`
    can't silently change the answer."""
    net = NETS[I2cSignal.VCC]
    paths = _build_paths_for_net(net)
    assert len(paths) == 1, "VCC net should produce exactly one SignalPath"
    path = paths[0]

    manual = 0.0
    for el in path.elements:
        if isinstance(el, WireSegment):
            manual += abs(el.end.x - el.start.x) + abs(el.end.y - el.start.y)
        elif isinstance(el, Via):
            manual += _VIA_WIRE_EXTENT_MM

    assert path.length_mm() == pytest.approx(manual)


def test_length_zero_via_extent_drops_via_contribution() -> None:
    """Passing `via_z_extent_mm=0` reduces the result to the pure
    Manhattan segment sum — a useful invariant for callers that want
    just the in-plane channel length."""
    net = NETS[I2cSignal.VCC]
    path = _build_paths_for_net(net)[0]

    seg_only = sum(
        abs(el.end.x - el.start.x) + abs(el.end.y - el.start.y)
        for el in path.elements
        if isinstance(el, WireSegment)
    )
    n_vias = sum(1 for el in path.elements if isinstance(el, Via))

    assert path.length_mm(via_z_extent_mm=0.0) == pytest.approx(seg_only)
    # Sanity: changing via extent moves the total by exactly n_vias*extent.
    assert path.length_mm(via_z_extent_mm=7.0) == pytest.approx(
        seg_only + 7.0 * n_vias
    )
