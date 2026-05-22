"""Forward-compatible grammar: SPI / UART / CAN bus declarations parse
but emit `not_yet_implemented` warnings rather than errors.
"""

from __future__ import annotations

from optimizer.weights import _build_weights


def test_unimplemented_classes_emit_warnings():
    raw = {
        "buses": {
            "primary_i2c": {"class": "bus_broadcast", "signals": ["sda", "scl"],
                             "power_signals": ["vcc", "gnd"], "topology": "per_signal"},
            "display_spi": {"class": "bus_broadcast", "signals": ["sck", "mosi", "miso"],
                              "topology": "per_signal"},
            "debug_uart": {"class": "point_to_point",
                            "signals": ["tx", "rx"]},
            "main_can": {"class": "differential_pair",
                          "signals": ["can_h", "can_l"],
                          "topology": "bundled"},
        },
    }
    weights = _build_weights(raw)
    codes = {code for code, _ in weights.unimplemented_class_warnings()}
    assert codes == {"not_yet_implemented"}
    # Two buses have non-implemented classes (uart + can); spi is
    # bus_broadcast so it's implemented even though it appears only
    # in grammar examples in the default file.
    details = [d for _, d in weights.unimplemented_class_warnings()]
    assert any("debug_uart" in d for d in details)
    assert any("main_can" in d for d in details)
    assert not any("display_spi" in d for d in details)


def test_unknown_class_is_skipped_with_warning():
    raw = {
        "buses": {"weird_bus": {"class": "made_up_class", "signals": ["a"]}},
    }
    weights = _build_weights(raw)
    assert "weird_bus" not in weights.buses
    assert any(code == "parser_warning" for code, _ in weights.warnings)
