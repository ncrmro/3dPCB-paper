"""CLI entry-point: `python -m router` runs the optimiser on
`PRIMARY_BUS` and prints the recommended hint dict + total wire length
vs the hand-authored baseline.
"""

from __future__ import annotations

import time

from netlist import NETS, PRIMARY_BUS
from router.optimiser import optimise_routing, path_length_mm
from vitamins.esp32_pinout import J1A_PINOUT, J1B_PINOUT
from vitamins.oled_ssd1306_pinout import OLED_PINOUT
from vitamins.sensors_pinout import BH1750_PINOUT, SCD41_PINOUT
from vitamins.substrate import _build_paths_for_net


def main() -> None:
    devices = {
        "SCD41": SCD41_PINOUT,
        "BH1750": BH1750_PINOUT,
        "OLED": OLED_PINOUT,
    }

    print(
        f"Optimising {PRIMARY_BUS.name} "
        f"({len(PRIMARY_BUS.signals)} signals, "
        f"{len(PRIMARY_BUS.devices)} devices)..."
    )
    t0 = time.time()
    result = optimise_routing(
        PRIMARY_BUS,
        master_columns={"J1A": J1A_PINOUT, "J1B": J1B_PINOUT},
        devices=devices,
    )
    elapsed = time.time() - t0

    hand_total = 0.0
    for _sig, net in NETS.items():
        paths = _build_paths_for_net(net)
        elements = [e for p in paths for e in p.elements]
        hand_total += path_length_mm(elements)

    print()
    print(f"Optimised ROUTING for {PRIMARY_BUS.name}:")
    print()
    for sig in PRIMARY_BUS.signals:
        h = result.hints[sig]
        print(
            f"  {sig.name}: RoutingHint("
            f"north_x={h.north_x}, "
            f"corridor_y={h.corridor_y}, "
            f"scd_east_on_l2={h.scd_east_on_l2}, "
            f"branch_east_on_l2={h.branch_east_on_l2})"
        )
    print()
    print("Per-net length (Manhattan + 5 mm/via penalty):")
    for sig in PRIMARY_BUS.signals:
        print(f"  {sig.name}: {result.per_net_length_mm[sig]:7.2f} mm")
    print()
    delta = hand_total - result.total_length_mm
    pct = 100.0 * delta / hand_total if hand_total else 0.0
    verb = "save" if delta > 0 else "add"
    print(
        f"Total wire length: {result.total_length_mm:.2f} mm "
        f"(vs {hand_total:.2f} mm hand-authored — "
        f"{verb} {abs(pct):.1f}%)"
    )
    print(
        f"Search: {result.candidates_considered} candidates in "
        f"{elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
