"""Unit tests for `router.collapse` — the post-route simplification +
staircase → 45° pass.

Each test feeds a hand-crafted cell list (and a stubbed `Grid` for
coordinate conversion) into `_collapse_quadrant_runs` and asserts the
collapse honours pin- and via-approach residuals.
"""

from __future__ import annotations

from router.collapse import _collapse_quadrant_runs
from router.grid import GRID_RES_MM, Grid


def _grid() -> Grid:
    """Small grid that's big enough for the synthetic cell lists below."""
    g = Grid(x_min=0.0, y_min=0.0, width=20.0, height=20.0, res=GRID_RES_MM)
    nx = int(round(g.width / g.res)) + 1
    ny = int(round(g.height / g.res)) + 1
    g.blocked = [
        [[False] * nx for _ in range(ny)]
        for _ in range(2)
    ]
    return g


def _allow_all(layer: int, gy: int, gx: int) -> bool:
    return False


def test_collapse_keeps_via_residual_at_diagonal_start():
    """A monotonic NE staircase that starts at a via cell must keep at
    least one axis-aligned cell of residual before the 45° diagonal,
    so the diagonal can't slice into the via barrel.
    """
    g = _grid()
    # Via at (gx=4, gy=4) — the start of a single-layer NE staircase
    # on layer 0. Layers differ at the boundary between via_pre and
    # the run, so we encode this by including a layer-flip cell pair
    # to mark the via xy.
    via_xy = g.to_world(4, 4)
    own_via_xys = {(round(via_xy[0], 3), round(via_xy[1], 3))}

    # 5-step NE staircase: (4,4) → (4,5) → (5,5) → (5,6) → (6,6) → (6,7)
    cells = [
        (0, 4, 4),  # via cell, layer 0
        (0, 5, 4),
        (0, 5, 5),
        (0, 6, 5),
        (0, 6, 6),
        (0, 7, 6),
    ]

    collapsed = _collapse_quadrant_runs(
        cells, g,
        own_pin_xys=set(),
        own_via_xys=own_via_xys,
        forbidden_check=_allow_all,
    )

    # The first emitted cell after the via cell must still be cardinal
    # (axis-aligned) — i.e. only one of (gy, gx) changes by 1 from the
    # via cell. Without the via residual, the first move could be a
    # diagonal (both gy and gx change by 1).
    via_cell = collapsed[0]
    next_cell = collapsed[1]
    dgx = abs(next_cell[2] - via_cell[2])
    dgy = abs(next_cell[1] - via_cell[1])
    assert (dgx == 0 and dgy == 1) or (dgx == 1 and dgy == 0), (
        f"first move after via must be cardinal, got d=({dgy},{dgx})"
    )


def test_collapse_diagonalizes_when_no_via_or_pin_endpoint():
    """Same staircase without pin/via endpoints collapses freely to a
    diagonal starting at the first cell.
    """
    g = _grid()
    cells = [
        (0, 4, 4),
        (0, 5, 4),
        (0, 5, 5),
        (0, 6, 5),
        (0, 6, 6),
        (0, 7, 6),
    ]
    collapsed = _collapse_quadrant_runs(
        cells, g,
        own_pin_xys=set(),
        own_via_xys=set(),
        forbidden_check=_allow_all,
    )
    # With both endpoints free, the staircase folds to a diagonal —
    # the move immediately after the start cell is a 45° step.
    dgx = abs(collapsed[1][2] - collapsed[0][2])
    dgy = abs(collapsed[1][1] - collapsed[0][1])
    assert dgx == 1 and dgy == 1, (
        f"expected diagonal first move, got d=({dgy},{dgx})"
    )
