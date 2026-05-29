"""Unit tests for the breadboard-lattice router core (graph + oracle + A*).

These build a synthetic `Grid` directly (no full board) so the oracle and
search are exercised in isolation. Node `(layer, ix, iy)` sits on fine cell
`(ix*N, iy*N)` with `N = pitch/res = 5`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from board.build import resolve_dims
from board.cli_report import _run_invariants
from board.loader import load_board
from router import lattice
from router.grid import Grid
from router.lattice import LatticeGeom, LatticeOracle, _lattice_astar

_SPECS = sorted((Path(__file__).resolve().parent.parent / "specs").glob("*.yaml"))
_HARD_GATES = {
    "angles_45_or_90", "edge_clearance", "wall_floor",
    "drilled_holes_match_vias", "endpoints_connected",
}

PITCH = 2.54
RES = PITCH / 5  # 0.508 mm — commensurate: 5 fine cells per pitch
NO_PINS: frozenset[tuple[int, int, int]] = frozenset()


class _Dims:
    """Minimal stand-in exposing only what the oracle/geom read."""

    pitch = PITCH

    def wall_halo_mm(self, res: float) -> float:
        return 0.8 + 1.0 - res / 2  # channel_width + buffer - res/2 = 1.546

    @property
    def via_halo_mm(self) -> float:
        return 1.25 / 2 + 1.0  # via_diameter/2 + buffer = 1.625


def _grid(span_pitches: int = 10) -> Grid:
    w = h = span_pitches * PITCH
    g = Grid(x_min=0.0, y_min=0.0, width=w, height=h, res=RES)
    nx = int(round(w / RES)) + 1
    ny = int(round(h / RES)) + 1
    g.blocked = [[[False] * nx for _ in range(ny)] for _ in range(2)]
    return g


def _setup(span: int = 10, pins=None):
    g = _grid(span)
    oracle = LatticeOracle(g, set(pins or []), _Dims())
    geom = LatticeGeom(g, PITCH)
    return g, geom, oracle


def test_empty_oracle_allows_run_and_via():
    _g, geom, oracle = _setup()
    assert oracle.run_clear(geom.world(1, 1), geom.world(8, 1), 0, 1, NO_PINS)
    assert oracle.via_clear(geom.world(4, 4), 1, NO_PINS)


def test_parallel_spacing():
    _g, geom, oracle = _setup()
    y1 = 5 * PITCH
    oracle.commit_run((PITCH, y1), (8 * PITCH, y1), 0, net_id=1)
    # One pitch away clears (2.54mm > 1.8mm wall floor).
    assert oracle.run_clear((PITCH, y1 + PITCH), (8 * PITCH, y1 + PITCH), 0, 2, NO_PINS)
    # Half a pitch away lands inside net 1's halo -> blocked for a foreign net.
    assert not oracle.run_clear(
        (PITCH, y1 + PITCH / 2), (8 * PITCH, y1 + PITCH / 2), 0, 2, NO_PINS
    )
    # ...but the SAME net may re-enter its own halo (trunk sharing).
    assert oracle.run_clear(
        (PITCH, y1 + PITCH / 2), (8 * PITCH, y1 + PITCH / 2), 0, 1, NO_PINS
    )


def test_foreign_pin_blocks_run():
    g = _grid()
    pin = {(0, 20, 20), (1, 20, 20)}  # node (4,4) -> fine cell (20,20)
    oracle = LatticeOracle(g, pin, _Dims())
    geom = LatticeGeom(g, PITCH)
    a, b = geom.world(1, 4), geom.world(8, 4)  # horizontal through the pin column
    assert not oracle.run_clear(a, b, 0, net_id=1, own_pins=NO_PINS)
    # The net that owns the pin may terminate on it.
    assert oracle.run_clear(a, b, 0, net_id=1, own_pins=frozenset(pin))


def test_via_blocked_by_pocket_on_l2():
    g = _grid()
    g.blocked[1][20][20] = True  # pocket removes L2 at node (4,4)
    oracle = LatticeOracle(g, set(), _Dims())
    geom = LatticeGeom(g, PITCH)
    assert not oracle.via_clear(geom.world(4, 4), 1, NO_PINS)
    assert oracle.via_clear(geom.world(2, 2), 1, NO_PINS)


def test_astar_finds_straight_path():
    _g, geom, oracle = _setup()
    path = _lattice_astar(geom, oracle, [(0, 1, 1)], {(0, 8, 1)},
                          net_id=1, own_pins=NO_PINS)
    assert path is not None
    assert path[0] == (0, 1, 1)
    assert path[-1] == (0, 8, 1)


def test_astar_uses_diagonal_shortcut():
    _g, geom, oracle = _setup()
    path = _lattice_astar(geom, oracle, [(0, 1, 1)], {(0, 5, 5)},
                          net_id=1, own_pins=NO_PINS)
    assert path is not None
    moved_diag = any(
        abs(path[i + 1][1] - path[i][1]) == 1 and abs(path[i + 1][2] - path[i][2]) == 1
        for i in range(len(path) - 1)
    )
    assert moved_diag, "octile A* should take a 45° diagonal when it is cheaper"


def test_astar_vias_around_a_foreign_wall():
    _g, geom, oracle = _setup()
    # A foreign net lays a horizontal wall across layer 0 at iy=5.
    oracle.commit_run((0.0, 5 * PITCH), (10 * PITCH, 5 * PITCH), 0, net_id=9)
    # Net 1 must get from below the wall to above it on column ix=2.
    path = _lattice_astar(geom, oracle, [(0, 2, 2)], {(0, 2, 8)},
                          net_id=1, own_pins=NO_PINS)
    assert path is not None
    used_via = any(path[i + 1][0] != path[i][0] for i in range(len(path) - 1))
    assert used_via, "should dive to the other layer to cross the foreign wall"


@pytest.mark.parametrize("spec", _SPECS, ids=[p.stem for p in _SPECS])
def test_lattice_routes_production_boards(spec):
    """The lattice router routes every production board end-to-end and its
    output passes every hard clearance gate (the same invariants the report
    uses). wall_floor_cross_layer is advisory and not asserted."""
    board = load_board(spec)
    dims = resolve_dims(board)
    paths = lattice.route_board(board, dims)
    assert paths, "lattice router returned no paths"
    results = {inv["key"]: inv for inv in _run_invariants(board, paths, dims)}
    for key in _HARD_GATES:
        assert results[key]["passed"], (
            f"{spec.stem}: {key} failed — {results[key]['message']}"
        )
