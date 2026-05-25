"""Unit tests for the declarative circuit spec (Pydantic + YAML).

Focus: parse / validate / round-trip — geometry equivalence with the
hand-coded `Tier2SubstrateOption2` is enforced by
`test_spec_matches_option2` at the bottom of this file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from circuit import (
    CircuitSpec,
    build_substrate,
    load_spec,
    route_to_signal_path,
)
from circuit.models import Rect, Route, Waypoint
from netlist import I2cSignal, Pin


# ---------------------------------------------------------------------------
# Minimal spec dict — used as a baseline that downstream tests mutate
# ---------------------------------------------------------------------------


def _minimal_spec_dict() -> dict:
    return {
        "name": "test",
        "levels": [
            {
                "name": "base",
                "perimeter": {"cx": 0, "cy": 0, "w": 68, "h": 50},
                "z_start": -1.5,
                "z_end": 1.5,
            },
        ],
        "devices": [],
        "routes": [],
    }


# ---------------------------------------------------------------------------
# Waypoint forms
# ---------------------------------------------------------------------------


def test_waypoint_list_form():
    wp = Waypoint.model_validate([-12.22, -17, 1])
    assert wp.x == -12.22
    assert wp.y == -17
    assert wp.layer == 1


def test_waypoint_dict_form():
    wp = Waypoint.model_validate({"x": 0, "y": 0, "layer": 2})
    assert wp.layer == 2


def test_waypoint_bad_layer_rejected():
    with pytest.raises(ValidationError):
        Waypoint.model_validate([0, 0, 3])


def test_waypoint_short_list_rejected():
    with pytest.raises(ValidationError):
        Waypoint.model_validate([0, 0])


# ---------------------------------------------------------------------------
# Pin reference resolution
# ---------------------------------------------------------------------------


def test_pin_reference_string():
    d = _minimal_spec_dict()
    d["devices"].append({"name": "j1a", "pin_holes": ["J1A.1"]})
    spec = CircuitSpec.model_validate(d)
    pin = spec.devices[0].pin_holes[0]
    assert isinstance(pin, Pin)
    assert pin.ref == "J1A"
    assert pin.number == 1


def test_pin_reference_malformed_rejected():
    d = _minimal_spec_dict()
    d["devices"].append({"name": "broken", "pin_holes": ["J1A_no_dot"]})
    with pytest.raises(ValidationError):
        CircuitSpec.model_validate(d)


# ---------------------------------------------------------------------------
# Validator: device level out of range
# ---------------------------------------------------------------------------


def test_device_level_out_of_range_rejected():
    d = _minimal_spec_dict()
    d["devices"].append({"name": "esp32", "levels": [3]})  # only 1 level
    with pytest.raises(ValidationError) as exc:
        CircuitSpec.model_validate(d)
    assert "out of range" in str(exc.value)


# ---------------------------------------------------------------------------
# Validator: Level z_end > z_start
# ---------------------------------------------------------------------------


def test_level_zero_height_rejected():
    d = _minimal_spec_dict()
    d["levels"][0]["z_end"] = d["levels"][0]["z_start"]
    with pytest.raises(ValidationError) as exc:
        CircuitSpec.model_validate(d)
    assert "z_end" in str(exc.value)


# ---------------------------------------------------------------------------
# Validator: route waypoint off the board
# ---------------------------------------------------------------------------


def test_route_off_board_rejected():
    d = _minimal_spec_dict()
    d["routes"].append({
        "signal": "SDA",
        "legs": [[
            [-12.22, -17, 1],
            # board is x∈[-34, +34], edge_clearance default 0.8 →
            # x=+34 is outside the [-33.2, +33.2] interior.
            [+34, -17, 1],
        ]],
    })
    with pytest.raises(ValidationError) as exc:
        CircuitSpec.model_validate(d)
    assert "outside board" in str(exc.value)


# ---------------------------------------------------------------------------
# Validator: signal must be a known I2cSignal
# ---------------------------------------------------------------------------


def test_unknown_signal_rejected():
    d = _minimal_spec_dict()
    d["routes"].append({
        "signal": "I2C_SOMETHING",
        "legs": [[[0, 0, 1], [1, 1, 1]]],
    })
    with pytest.raises(ValidationError):
        CircuitSpec.model_validate(d)


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


def test_round_trip_minimal():
    d = _minimal_spec_dict()
    spec = CircuitSpec.model_validate(d)
    dumped = spec.model_dump(mode="json")
    spec2 = CircuitSpec.model_validate(dumped)
    assert spec == spec2


# ---------------------------------------------------------------------------
# YAML round-trip — full tier2_option2.yaml file
# ---------------------------------------------------------------------------


_SPEC_PATH = Path(__file__).resolve().parents[1] / "specs" / "tier2_option2.yaml"


@pytest.mark.skipif(not _SPEC_PATH.exists(), reason="spec file not authored yet")
def test_load_tier2_option2_yaml():
    spec = load_spec(_SPEC_PATH)
    assert spec.name == "tier2_option2"
    assert len(spec.routes) > 0


@pytest.mark.skipif(not _SPEC_PATH.exists(), reason="spec file not authored yet")
def test_round_trip_tier2_option2():
    spec = load_spec(_SPEC_PATH)
    dumped = spec.model_dump(mode="json")
    spec2 = CircuitSpec.model_validate(dumped)
    # Re-serialize and compare YAMLs at the dict level for stability —
    # Waypoint stores as a mapping on dump, so direct equality on
    # spec == spec2 is the right invariant.
    assert spec == spec2


# ---------------------------------------------------------------------------
# Geometry parity vs hand-coded Tier2SubstrateOption2 — the headline check
# ---------------------------------------------------------------------------


_GEOMETRY_TOLERANCE_MM = 1e-3


def _elements_close(a, b) -> bool:
    """Compare a WireSegment / Via pair allowing sub-µm float drift.

    The hand-coded path computes pin xy by accumulating pitches as
    Python floats (`_J1A_X + 17.78` = -12.219999999999999), while the
    YAML carries the rounded literal `-12.22`. The geometric meaning
    is identical; the test allows a 1-µm tolerance per coordinate."""
    from vitamins.substrate import Via, WireSegment

    if type(a) is not type(b):
        return False
    if isinstance(a, WireSegment):
        return (
            a.layer == b.layer
            and abs(a.start.x - b.start.x) < _GEOMETRY_TOLERANCE_MM
            and abs(a.start.y - b.start.y) < _GEOMETRY_TOLERANCE_MM
            and abs(a.end.x - b.end.x) < _GEOMETRY_TOLERANCE_MM
            and abs(a.end.y - b.end.y) < _GEOMETRY_TOLERANCE_MM
        )
    if isinstance(a, Via):
        return (
            abs(a.position.x - b.position.x) < _GEOMETRY_TOLERANCE_MM
            and abs(a.position.y - b.position.y) < _GEOMETRY_TOLERANCE_MM
            and abs(a.diameter - b.diameter) < _GEOMETRY_TOLERANCE_MM
        )
    return a == b


@pytest.mark.skipif(not _SPEC_PATH.exists(), reason="spec file not authored yet")
def test_spec_matches_option2():
    """Element-by-element comparison of the spec-driven SignalPath list
    against the hand-coded `Tier2SubstrateOption2._get_signal_paths()`.

    Both classes feed the same routing-invariant suite, so passing this
    test is the strongest statement that the YAML faithfully describes
    the option-2 geometry."""
    from vitamins.substrate import Tier2SubstrateFromSpec, Tier2SubstrateOption2

    spec_paths = Tier2SubstrateFromSpec()._get_signal_paths()
    ref_paths = Tier2SubstrateOption2()._get_signal_paths()

    # Order is fragile across implementations — index by signal name.
    spec_by_sig = {p.name: p for p in spec_paths}
    ref_by_sig = {p.name: p for p in ref_paths}

    assert set(spec_by_sig) == set(ref_by_sig), (
        f"signal name set differs: spec={sorted(spec_by_sig)} vs "
        f"option-2={sorted(ref_by_sig)}"
    )

    diffs: list[str] = []
    for sig in sorted(spec_by_sig):
        spec_elems = list(spec_by_sig[sig].elements)
        ref_elems = list(ref_by_sig[sig].elements)
        if len(spec_elems) != len(ref_elems):
            diffs.append(
                f"signal {sig!r}: spec has {len(spec_elems)} elements, "
                f"option-2 has {len(ref_elems)}\n"
                f"  spec: {spec_elems}\n"
                f"  ref:  {ref_elems}"
            )
            continue
        for i, (a, b) in enumerate(zip(spec_elems, ref_elems)):
            if not _elements_close(a, b):
                diffs.append(
                    f"signal {sig!r}[{i}]:\n"
                    f"  spec: {a}\n"
                    f"  ref:  {b}"
                )
    assert not diffs, "\n".join(diffs)
