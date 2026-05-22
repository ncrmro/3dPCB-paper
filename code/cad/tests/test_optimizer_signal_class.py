"""Net → signal class mapping under the default weights file."""

from __future__ import annotations

from optimizer.eligibility import classify_net
from optimizer.signal_class import SignalClass
from optimizer.weights import load_weights


def test_default_weights_classify_i2c_signals():
    w = load_weights()
    assert classify_net("sda", w)[0] == SignalClass.BUS_BROADCAST
    assert classify_net("scl", w)[0] == SignalClass.BUS_BROADCAST


def test_default_weights_classify_power_and_ground():
    w = load_weights()
    assert classify_net("vcc", w)[0] == SignalClass.POWER_RAIL
    assert classify_net("+3V3", w)[0] == SignalClass.POWER_RAIL
    assert classify_net("gnd", w)[0] == SignalClass.GROUND


def test_unknown_net_falls_back_to_singleton():
    w = load_weights()
    assert classify_net("J3_ADDR", w)[0] == SignalClass.SINGLETON
