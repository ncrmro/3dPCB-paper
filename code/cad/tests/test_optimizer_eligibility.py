"""Per-class eligibility matrix + topology mode behavior."""

from __future__ import annotations

from optimizer.eligibility import evaluate_pair
from optimizer.signal_class import SignalClass
from optimizer.weights import load_weights


def test_ground_eligible_no_droop():
    w = load_weights()
    v = evaluate_pair(
        net_name="gnd",
        klass=SignalClass.GROUND,
        bus_name="primary_i2c",
        weights=w,
        module_a="SCD41",
        module_b="OLED",
    )
    assert v.eligible
    assert not v.droop_warning


def test_power_rail_eligible_with_droop():
    w = load_weights()
    v = evaluate_pair(
        net_name="vcc",
        klass=SignalClass.POWER_RAIL,
        bus_name="primary_i2c",
        weights=w,
        module_a="SCD41",
        module_b="OLED",
    )
    assert v.eligible
    assert v.droop_warning


def test_bus_broadcast_declined_in_per_signal():
    w = load_weights()
    v = evaluate_pair(
        net_name="sda",
        klass=SignalClass.BUS_BROADCAST,
        bus_name="primary_i2c",
        weights=w,
        topology_override="per_signal",
        module_a="ESP32",
        module_b="OLED",
    )
    assert not v.eligible
    assert v.reason == "bus_signal_in_per_signal_topology"


def test_bus_broadcast_subsumed_in_bundled():
    w = load_weights()
    v = evaluate_pair(
        net_name="sda",
        klass=SignalClass.BUS_BROADCAST,
        bus_name="primary_i2c",
        weights=w,
        topology_override="bundled",
        module_a="ESP32",
        module_b="OLED",
    )
    assert not v.eligible
    assert v.subsumed_by_bus == "primary_i2c"


def test_point_to_point_always_declined():
    w = load_weights()
    v = evaluate_pair(
        net_name="uart_tx",
        klass=SignalClass.POINT_TO_POINT,
        bus_name=None,
        weights=w,
        module_a="ESP32",
        module_b="FTDI",
    )
    assert not v.eligible
    assert v.reason == "two_endpoint_net"


def test_per_device_override_flips_a_net():
    # Build a weights dict with a per-device override that refuses
    # power_rail merges on a hypothetical CAMERA module.
    from optimizer.weights import _build_weights
    raw = {
        "buses": {"primary_i2c": {"class": "bus_broadcast", "signals": ["sda", "scl"],
                                   "power_signals": ["vcc", "gnd"], "topology": "per_signal"}},
        "per_device_overrides": {
            "CAMERA": {"power_rail": {"mergeable": False, "reason": "high_inrush"}}
        },
    }
    w = _build_weights(raw)
    v = evaluate_pair(
        net_name="vcc",
        klass=SignalClass.POWER_RAIL,
        bus_name="primary_i2c",
        weights=w,
        module_a="CAMERA",
        module_b="SCD41",
    )
    assert not v.eligible
    assert v.reason == "high_inrush"
