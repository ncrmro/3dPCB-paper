"""CLI backing `code/cad/bin/score-routes`.

Kept as a module rather than inlined into the bin script so the
table-rendering code is unit-testable and shell quoting hell is
sidestepped (Python f-strings with embedded single quotes don't
survive bash heredoc embedding).
"""

from __future__ import annotations

import sys

from router.score import score_paths
from vitamins import substrate as S


# (snake_case CLI name → class). Snake names match the gallery
# manifest entries and AnchorSCAD auto-registration.
_CHOICES = {
    "tier2_substrate": S.Tier2Substrate,
    "tier2_substrate_bundled": S.Tier2SubstrateBundled,
    "tier2_substrate_option2": S.Tier2SubstrateOption2,
}


def _pedestal_box(sub):
    """OLED pedestal xy footprint, centred on (0, _J4_Y). Returns
    `None` for substrates without a pedestal (Tier1)."""
    d = sub.dim
    if not hasattr(d, "oled_pedestal_width"):
        return None
    cx, cy = 0.0, S._J4_Y
    hw = d.oled_pedestal_width / 2.0
    hd = d.oled_pedestal_depth / 2.0
    return (cx - hw, cy - hd, cx + hw, cy + hd)


def _score_one(cls):
    sub = cls()
    paths = sub._get_signal_paths()
    return score_paths(
        paths,
        board_extents=(sub.dim.board_w, sub.dim.board_h),
        channel_width=sub.dim.channel_width,
        min_wall_thickness=sub.dim.min_wall_thickness,
        pedestal_box=_pedestal_box(sub),
    )


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        names = list(_CHOICES.keys())
    else:
        names = []
        for a in args:
            if a not in _CHOICES:
                print(
                    f"unknown substrate {a!r}; choices: {list(_CHOICES)}",
                    file=sys.stderr,
                )
                return 2
            names.append(a)

    rows = [(n, _score_one(_CHOICES[n])) for n in names]

    # 23 chars fits the longest registered name (tier2_substrate_option2).
    header = (
        f"{'':<23}  {'length':>7}  {'L1':>6}  {'L2':>6}  "
        f"{'vias':>4}  {'edge':>6}  {'pedestal':>8}  {'score':>7}"
    )
    print(header)
    print("-" * len(header))
    for n, s in rows:
        print(
            f"{n:<23}  {s.total_length_mm:>7.1f}  {s.l1_length_mm:>6.1f}  "
            f"{s.l2_length_mm:>6.1f}  {s.via_count:>4}  "
            f"{s.edge_clearance_min_mm:>+6.2f}  "
            f"{s.pedestal_underside_mm:>8.2f}  {s.aggregate:>7.1f}"
        )

    if len(rows) >= 2:
        best = min(rows, key=lambda r: r[1].aggregate)
        worst = max(rows, key=lambda r: r[1].aggregate)
        if best[1].aggregate < worst[1].aggregate:
            delta = worst[1].aggregate - best[1].aggregate
            print()
            print(
                f"best: {best[0]!r}  (aggregate {best[1].aggregate:.1f}; "
                f"{delta:.1f} below {worst[0]!r})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
