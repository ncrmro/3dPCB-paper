"""Unit tests for the breadboard-lattice router core (graph + oracle + A*).

These build a synthetic `Grid` directly (no full board) so the oracle and
search are exercised in isolation. Node `(layer, ix, iy)` sits on fine cell
`(ix*N, iy*N)` with `N = pitch/res = 5`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from board.build import resolve_dims
from board.buses import Net, PinEndpoint
from board.cli_report import _run_invariants
from board.loader import load_board
from board.pins import Pin, PinGroup, Point2D
from router import lattice
from router.autoroute import RouteFailure
from router.grid import Grid
from router.lattice import (
    LatticeGeom,
    LatticeOracle,
    _blockers_around,
    _lattice_astar,
    _rollback_net,
    _route_bus,
    _route_one_net_lattice,
)

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
    via_diameter = 1.25  # via_halo_mm below assumes this diameter

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


# ---------------------------------------------------------------------------
# Stage B: order-search + rip-up coordinator
#
# `pin` is never dereferenced by the router (only endpoint xy is), so a single
# placeholder Pin is enough to assemble synthetic Nets on the lattice directly.
# ---------------------------------------------------------------------------

_DUMMY_PIN = Pin(index=1, role="X", group=PinGroup.GPIO, position=Point2D(x=0.0, y=0.0))


def _endpoint(geom: LatticeGeom, name: str, ix: int, iy: int) -> PinEndpoint:
    wx, wy = geom.world(ix, iy)
    return PinEndpoint(instance_name=name, pin=_DUMMY_PIN, position=Point2D(x=wx, y=wy))


def _net(geom: LatticeGeom, signal: str, master, *slaves) -> Net:
    eps = [_endpoint(geom, "u1", *master)]
    eps += [_endpoint(geom, f"s{i}", *node) for i, node in enumerate(slaves)]
    return Net(bus_name="primary", signal=signal, endpoints=tuple(eps))


def test_rollback_net_removes_only_that_net():
    _g, geom, oracle = _setup()
    oracle.commit_run(geom.world(1, 1), geom.world(8, 1), 0, net_id=1)
    oracle.commit_run(geom.world(1, 3), geom.world(8, 3), 0, net_id=2)
    _rollback_net(oracle, 1)
    assert all(owner != 1 for owner in oracle.owner.values()), "net 1 copper survived"
    assert any(owner == 2 for owner in oracle.owner.values()), "net 2 wrongly removed"


def test_route_one_net_rolls_back_partial_legs_on_failure():
    """A net whose later leg can't route must leave the oracle exactly as it
    found it — its already-committed earlier legs are dropped — or retries in a
    different order would be poisoned by the half-net's stale halo."""
    _g, geom, oracle = _setup()
    # Impenetrable two-layer foreign wall across iy=5 splits the board.
    for layer in (0, 1):
        oracle.commit_run((0.0, 5 * PITCH), (10 * PITCH, 5 * PITCH), layer, net_id=99)
    # slave0 sits below the wall (routes + commits); slave1 above it (unreachable).
    net = _net(geom, "SDA", (2, 2), (5, 2), (2, 8))
    with pytest.raises(RouteFailure):
        _route_one_net_lattice(geom, oracle, net, net_id=1)
    assert all(owner != 1 for owner in oracle.owner.values()), "partial legs not rolled back"
    assert any(owner == 99 for owner in oracle.owner.values()), "foreign wall disturbed"


def test_blockers_around_detects_committed_neighbour():
    _g, geom, oracle = _setup()
    oracle.commit_run(geom.world(5, 4), geom.world(7, 4), 0, net_id=7)  # just east of (4,4)
    net = _net(geom, "SDA", (4, 4), (4, 1))
    assert 7 in _blockers_around(geom, oracle, net)


def test_route_bus_routes_independent_nets():
    """The coordinator routes a whole bus and hands back the next free net id."""
    _g, geom, oracle = _setup()
    nets = [_net(geom, "SDA", (1, 1), (8, 1)), _net(geom, "GND", (1, 8), (8, 8))]
    paths, next_id = _route_bus(geom, oracle, nets, 0, None, None)
    assert len(paths) == 2  # one leg per single-slave net
    assert next_id == 2
    assert {1, 2} <= set(oracle.owner.values())


def test_route_bus_raises_when_unroutable_after_ripup():
    """Two nets that both require the same dead-end approach node can't be
    ordered apart; order-search fails and rip-up ping-pongs (ripping and
    re-queuing) until its per-net budget is spent, then the bus is reported
    unroutable rather than looping forever."""
    g, geom, oracle = _setup()
    # Collapse to a single live layer — on two layers the nets would just dodge
    # onto opposite sides of the substrate and never actually contend.
    for row in g.blocked[1]:
        for gx in range(len(row)):
            row[gx] = True
    # On the one live layer, node (5,10) is reachable ONLY from the south, via
    # (5,9): wall its other in-bounds neighbours.
    for ix, iy in ((4, 10), (6, 10), (4, 9), (6, 9)):
        g.blocked[0][iy * geom.n][ix * geom.n] = True
    # GND must pass through (5,9) to reach its dead-end slave (5,10); SDA must
    # terminate ON (5,9). Mutually exclusive — no order and no rip-up resolves it.
    nets = [_net(geom, "SDA", (5, 2), (5, 9)), _net(geom, "GND", (5, 1), (5, 10))]
    with pytest.raises(RouteFailure):
        _route_bus(geom, oracle, nets, 0, None, None)


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
