"""Signal-class taxonomy + default eligibility rules.

Signals are classified by *electrical role*, not by name. This lets
the same eligibility/topology machinery handle I²C, SPI, UART, CAN
and differential pairs from one YAML grammar.

Day one, only `BUS_BROADCAST`, `POWER_RAIL`, `GROUND`, and `SINGLETON`
are exercised at runtime — the others are valid in the weights file
but produce a `not_yet_implemented` warning so users notice when
their grammar is ahead of the implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SignalClass(Enum):
    POWER_RAIL = "power_rail"
    GROUND = "ground"
    BUS_BROADCAST = "bus_broadcast"
    BUS_ADDRESSED = "bus_addressed"
    POINT_TO_POINT = "point_to_point"
    DIFFERENTIAL_PAIR = "differential_pair"
    LENGTH_MATCHED = "length_matched"
    SINGLETON = "singleton"


# Classes the runtime knows how to score. Anything else parses but
# does not generate proposals; the CLI emits a `not_yet_implemented`
# warning per occurrence.
IMPLEMENTED_CLASSES = frozenset({
    SignalClass.POWER_RAIL,
    SignalClass.GROUND,
    SignalClass.BUS_BROADCAST,
    SignalClass.SINGLETON,
})


@dataclass(frozen=True)
class ClassRule:
    """Default rule for a signal class.

    `mergeable_token` is the literal from the weights YAML:
      - "true"        → always candidate (gated by proximity)
      - "false"       → never candidate; emit `reason`
      - "conditional" → resolves at bus level (see weights.py)
      - "as_pair"     → routed as a pair; declined when solo
    """

    mergeable_token: str
    droop_warning: bool = False
    reason: Optional[str] = None
    reason_when_declined: Optional[str] = None


# Sensible defaults — overridable from the weights file's
# `signal_classes:` block.
DEFAULT_CLASS_RULES: dict[SignalClass, ClassRule] = {
    SignalClass.POWER_RAIL: ClassRule(mergeable_token="true", droop_warning=True),
    SignalClass.GROUND: ClassRule(mergeable_token="true"),
    SignalClass.BUS_BROADCAST: ClassRule(
        mergeable_token="conditional",
        reason_when_declined="bus_signal_in_per_signal_topology",
    ),
    SignalClass.BUS_ADDRESSED: ClassRule(
        mergeable_token="false", reason="per_device_unique"
    ),
    SignalClass.POINT_TO_POINT: ClassRule(
        mergeable_token="false", reason="two_endpoint_net"
    ),
    SignalClass.DIFFERENTIAL_PAIR: ClassRule(
        mergeable_token="as_pair", reason_when_declined="pair_atomic"
    ),
    SignalClass.LENGTH_MATCHED: ClassRule(
        mergeable_token="false", reason="length_match_required"
    ),
    SignalClass.SINGLETON: ClassRule(
        mergeable_token="false", reason="no_shared_trunk"
    ),
}
