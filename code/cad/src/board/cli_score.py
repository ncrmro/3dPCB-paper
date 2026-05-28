"""`bin/score-routes` backing CLI — board-based.

Iterates every spec in `code/cad/specs/`, runs the autorouter, and
prints the route-score breakdown so two layouts can be compared. The
score weights live in `router.score`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from board.build import resolve_dims
from board.loader import load_board
from router.autoroute import route_board
from router.score import score_paths


def _specs_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "specs"


def _score_board(spec_path: Path):
    board = load_board(spec_path)
    dims = resolve_dims(board)
    paths = route_board(board, dims)
    base = board.levels[0].perimeter
    return board.name, score_paths(
        paths,
        board_extents=(base.w, base.h),
        channel_width=dims.channel_width,
        min_wall_thickness=dims.buffer,
    )


def main(argv: list[str]) -> int:
    args = argv[1:]
    specs = sorted(_specs_dir().glob("*.yaml"))
    if args:
        wanted = set(args)
        specs = [s for s in specs if s.stem in wanted]
        missing = wanted - {s.stem for s in specs}
        if missing:
            print(f"unknown specs: {sorted(missing)}", file=sys.stderr)
            return 2
    if not specs:
        print("no specs to score", file=sys.stderr)
        return 1

    rows = [_score_board(s) for s in specs]
    longest = max(len(n) for n, _ in rows)
    header = (
        f"{'':<{longest}}  {'length':>7}  {'L1':>6}  {'L2':>6}  "
        f"{'vias':>4}  {'edge':>6}  {'score':>7}"
    )
    print(header)
    print("-" * len(header))
    for n, s in rows:
        print(
            f"{n:<{longest}}  {s.total_length_mm:>7.1f}  "
            f"{s.l1_length_mm:>6.1f}  {s.l2_length_mm:>6.1f}  "
            f"{s.via_count:>4}  {s.edge_clearance_min_mm:>+6.2f}  "
            f"{s.aggregate:>7.1f}"
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
