"""Routing cost weights + the shared edge-proximity penalty.

The breadboard-lattice router (`router.lattice`) runs the actual A*; this
module holds the step weights and the soft board-edge penalty it shares,
kept separate so the cost model lives in one place.
"""

from __future__ import annotations

from router.grid import Grid

_W_STEP = 1.0
_W_VIA = 1.5   # cost of a single layer transition — kept low so the router
               # uses BOTH layers instead of packing everything onto one.
_W_EDGE = 3.0
_EDGE_RADIUS_MM = 1.0   # within this distance of the board edge → edge penalty

# Tiebreaker: any direction change costs _W_BEND. Small enough that it never
# overrides a real obstacle (`_W_STEP=1.0` dwarfs it) but it breaks the
# staircase/L-shape tie in favour of the clean L-shape.
_W_BEND = 0.05


def _edge_penalty(g: Grid, gx: int, gy: int) -> float:
    # Penalise cells within _EDGE_RADIUS_MM of the board outline, beyond the
    # hard edge_clearance strip already blocked. Soft cost nudges A* to stay
    # centred when nothing else decides the lane.
    wx, wy = g.to_world(gx, gy)
    perim_dx = min(wx - g.x_min, g.x_min + g.width - wx)
    perim_dy = min(wy - g.y_min, g.y_min + g.height - wy)
    perim = min(perim_dx, perim_dy)
    if perim < _EDGE_RADIUS_MM:
        return _W_EDGE * (1 - perim / _EDGE_RADIUS_MM)
    return 0.0
