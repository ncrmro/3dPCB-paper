"""Auto-router entry point.

Resolves a `Board`'s buses into routed `SignalPath`s. The search runs on
the breadboard lattice (`router.lattice`), so every run, corner, and via
lands on the 2.54 mm pitch by construction. This module is the stable
public entry (`route_board`) the builder, substrate report, and score
tool call, plus the shared `RouteFailure` type the lattice router raises.
"""

from __future__ import annotations

from board.board import Board
from board.buses import Net
from vitamins.substrate import SignalPath


class RouteFailure(Exception):
    """A net couldn't be routed. Carries the failing net + partial
    solution so the caller can surface a clear error.
    """

    def __init__(self, net: Net, reason: str, partial: tuple[SignalPath, ...]):
        super().__init__(f"{net.signal} (bus {net.bus_name!r}): {reason}")
        self.net = net
        self.reason = reason
        self.partial = partial


def route_board(board: Board, dims) -> list[SignalPath]:
    """Auto-route every bus on the Board onto the breadboard lattice.

    Entry point used by `board.build.build_board`, the substrate report,
    and the score tool. Delegates to `router.lattice`, which produces
    on-pitch geometry directly — no post-route collapse/align/snap.
    """
    from router import lattice  # local import: lattice imports RouteFailure from here
    return lattice.route_board(board, dims)
