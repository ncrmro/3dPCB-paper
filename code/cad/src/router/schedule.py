"""Net routing-priority + bus-level pair scheduling.

`_net_priority` is the per-net ordering key (signal nets first, busier
nets first). `_ordered_bus_actions` interleaves a bus's nets so each
pair (VCC/GND, SCL/SDA) routes its first leg uncoupled, then its
second leg with a `parallel_target_signal` hint so the partner cell
set rewards bundled corridors.
"""

from __future__ import annotations

from board.buses import Net, bus_pairs

# Priority order: lower number routes first. Bus signal nets compete for
# the cleanest path; power follows because it's the most forgiving (any
# corridor with width clears the I-rail).
_SIGNAL_PRIORITY: dict[str, int] = {
    "SCL": 0, "SDA": 1, "TX": 0, "RX": 1,
    "VCC": 5, "3V3": 5, "5V": 5, "GND": 6,
}


def _net_priority(net: Net) -> tuple[int, int]:
    sig_priority = _SIGNAL_PRIORITY.get(net.signal, 7)
    # Tie-break: more pins → harder to route, do it first.
    return sig_priority, -len(net.endpoints)


def _ordered_bus_actions(
    bus_kind: str, nets_by_signal: dict[str, Net],
) -> list[tuple[Net, str | None]]:
    """Order one bus's nets into a routing schedule.

    Returns a list of `(net, parallel_target_signal_or_None)` entries:

      1. First signal of every pair (e.g. VCC, SCL for I²C) — sorted by
         _net_priority among themselves. These claim the trunk corridors.
      2. Second signal of every pair (GND, SDA) — each paired with its
         first via `parallel_target_signal`. The router rewards cells
         next to the first's path so the pair stays bundled.
      3. Any unpaired signals — fallback to priority order.
    """
    pairs = bus_pairs(bus_kind)
    paired = {s for pair in pairs for s in pair}
    out: list[tuple[Net, str | None]] = []
    seen: set[str] = set()

    firsts = [p[0] for p in pairs if p[0] in nets_by_signal]
    firsts.sort(key=lambda s: _net_priority(nets_by_signal[s]))
    for sig in firsts:
        out.append((nets_by_signal[sig], None))
        seen.add(sig)

    for first_sig, second_sig in pairs:
        if second_sig not in nets_by_signal:
            continue
        target = first_sig if first_sig in seen else None
        out.append((nets_by_signal[second_sig], target))
        seen.add(second_sig)

    leftover = [
        n for sig, n in nets_by_signal.items()
        if sig not in seen and sig not in paired
    ]
    leftover.sort(key=_net_priority)
    out.extend((n, None) for n in leftover)
    return out
