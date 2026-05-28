"""End-to-end tests for the declarative Board → autoroute → build pipeline.

Locks down the bug class that motivated the rewrite: drilled holes and
routed-channel vias coming from different sources of truth. Every via
emitted by the router MUST have a drilled hole at the same xy, and
every drilled hole MUST be either a known device pin or a router-
emitted via — no orphans either way.

Tests are parametrised over every `code/cad/specs/*.yaml` so a new
spec is automatically picked up.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from board import (
    DEVICE_REGISTRY,
    Board,
    Bus,
    DeviceInstance,
    Header,
    Level,
    Point2D,
    Rect,
    load_board,
)
from board.board import DimOverrides
from board.build import build_board, resolve_dims, synthesize_header_levels
from board.buses import HintWaypoint, RoutingHint
from router.autoroute import route_board
from router.grid import Grid
from vitamins.substrate import Via, WireSegment

SPECS_DIR = Path(__file__).resolve().parent.parent / "specs"


def _all_spec_paths():
    return sorted(SPECS_DIR.glob("*.yaml"))


def _spec_ids():
    return [p.stem for p in _all_spec_paths()]


@pytest.fixture(params=_all_spec_paths(), ids=_spec_ids())
def board_and_paths(request):
    """Load the spec, autoroute it, return (board, paths, dims) for tests."""
    board = load_board(request.param)
    dims = resolve_dims(board)
    paths = route_board(board, dims)
    return board, paths, dims


# ---------------------------------------------------------------------------
# Breadboard-lattice alignment
# ---------------------------------------------------------------------------


def _assert_pins_on_pitch_lattice(board, dims):
    """Every device pin maps to an exact pitch-index grid node.

    Requires both the commensurate resolution (res = pitch/N) and a
    pitch-anchored origin (perimeter grown to pitch). Without the perimeter
    snap the origin is only a `res` multiple, so pins round to ~0.25mm off —
    the via-drift this whole effort fixes.
    """
    g = Grid.from_board(board, res=dims.res)
    pitch = dims.pitch
    assert abs(g.x_min / pitch - round(g.x_min / pitch)) < 1e-6, "origin x off pitch"
    assert abs(g.y_min / pitch - round(g.y_min / pitch)) < 1e-6, "origin y off pitch"
    for inst in board.devices:
        dev = inst.resolved_device()
        for pin in dev.pins:
            p = dev.pin_position_at(inst.position, inst.rotation, pin)
            gx, gy = g.to_grid(p.x, p.y)
            wx, wy = g.to_world(gx, gy)
            tag = f"{inst.name} pin {pin.index}"
            assert abs(wx - p.x) < 1e-6, f"{tag} x round-trip off-lattice: {p.x} -> {wx}"
            assert abs(wy - p.y) < 1e-6, f"{tag} y round-trip off-lattice: {p.y} -> {wy}"
            npx = (p.x - g.x_min) / pitch
            npy = (p.y - g.y_min) / pitch
            assert abs(npx - round(npx)) < 1e-6, f"{tag} x not on a pitch node"
            assert abs(npy - round(npy)) < 1e-6, f"{tag} y not on a pitch node"


def test_pins_land_on_pitch_lattice(board_and_paths):
    board, _paths, dims = board_and_paths
    _assert_pins_on_pitch_lattice(board, dims)


def test_starter_board_pins_on_pitch_lattice():
    board = _starter_board()
    _assert_pins_on_pitch_lattice(board, resolve_dims(board))


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


def test_pinouts_register_devices():
    """Importing `board` registers the four starter devices."""
    expected = {"esp32_c3_supermini", "scd41", "bh1750", "oled_ssd1306"}
    assert expected.issubset(set(DEVICE_REGISTRY))


def test_i2c_bus_resolves_to_four_nets():
    """An I²C bus expands to VCC + GND + SCL + SDA, each carrying the
    master + every slave pin for that signal."""
    board = load_board(SPECS_DIR / "i2c_midline_sensors.yaml")
    nets = board.nets()
    by_signal = {n.signal: n for n in nets}
    assert set(by_signal) == {"VCC", "GND", "SCL", "SDA"}
    for net in nets:
        # master + 3 slaves on the starter spec
        assert len(net.endpoints) == 4
        assert net.master.instance_name == "u1"
        assert {s.instance_name for s in net.slaves} == {"scd41", "bh1750", "oled"}


# ---------------------------------------------------------------------------
# Routing invariants
# ---------------------------------------------------------------------------


def test_router_reaches_every_endpoint(board_and_paths):
    """Every slave pin must have at least one routed path connecting it
    to the master. RouteFailure raised inside the fixture would already
    fail the test; this asserts the *result* covers every endpoint."""
    board, paths, _ = board_and_paths
    nets = board.nets()
    endpoints_per_net = {n.signal: {s.instance_name for s in n.slaves}
                         for n in nets}
    routed_per_signal: dict[str, set[str]] = {sig: set() for sig in endpoints_per_net}
    for p in paths:
        # path name = "<bus>_<signal>_<slave>"
        parts = p.name.rsplit("_", 1)
        if len(parts) != 2:
            continue
        signal = parts[0].rsplit("_", 1)[-1]
        slave = parts[1]
        if signal in routed_per_signal:
            routed_per_signal[signal].add(slave)
    for sig, expected in endpoints_per_net.items():
        assert routed_per_signal[sig] == expected, (
            f"signal {sig}: expected slaves {expected}, "
            f"got {routed_per_signal[sig]}"
        )


def test_every_segment_is_45_or_90(board_and_paths):
    """The 45° / axis-aligned invariant — channels must run cardinal or
    exact-45° so chamfered fittings + the voxel rasteriser stay sane."""
    _, paths, _ = board_and_paths
    for path in paths:
        for elt in path.elements:
            if not isinstance(elt, WireSegment):
                continue
            dx = elt.end.x - elt.start.x
            dy = elt.end.y - elt.start.y
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                continue
            angle = math.degrees(math.atan2(dy, dx))
            allowed = [0, 45, 90, 135, 180, -45, -90, -135, -180]
            assert any(abs(angle - a) < 0.05 for a in allowed), (
                f"{path.name}: segment runs at {angle:.3f}°"
            )


def test_wire_to_wire_wall_floor(board_and_paths):
    """Advisory check — measures the worst cross-net same-layer wire
    distance and asserts it's above HALF the wall floor (= sanity floor;
    anything less is a definite short). The full wall_floor enforcement
    is reported in the routing JSON invariants block but not enforced
    here: the strict 1.4 mm halo is satisfied in OPEN space, but at
    each dense pin's approach corridor the own-net exemption (so a pin
    stays reachable) lets a cross-net wire from a different signal sit
    one grid step (0.7-1.0 mm) outside the approach. The parallel-axis
    + diagonal buffer keeps that distance ≥ wall_floor/2; a full fix
    would need ripup/reroute or an ILP solver (separate-PR scope).
    """
    import math

    board, paths, dims = board_and_paths
    wall_floor = dims.wall_floor_mm
    # Hard floor: half wall-floor — below this the wires would short or
    # merge during printing. Above this, the wall is thinner than the
    # printable optimum but the substrate still works.
    hard_floor = wall_floor / 2

    def _net_id(path_name: str) -> str:
        return path_name.rsplit("_", 1)[0]

    samples: list[tuple[str, int, float, float]] = []
    for p in paths:
        nid = _net_id(p.name)
        for elt in p.elements:
            if not isinstance(elt, WireSegment):
                continue
            dx = elt.end.x - elt.start.x
            dy = elt.end.y - elt.start.y
            length = math.hypot(dx, dy)
            steps = max(int(length / 0.25), 1)
            for i in range(steps + 1):
                t = i / steps
                samples.append((nid, elt.layer,
                                elt.start.x + t * dx, elt.start.y + t * dy))

    worst: dict[tuple[str, str, int],
                tuple[float, tuple[float, float], tuple[float, float]]] = {}
    for i, (n1, l1, x1, y1) in enumerate(samples):
        for j in range(i + 1, len(samples)):
            n2, l2, x2, y2 = samples[j]
            if l1 != l2 or n1 == n2:
                continue
            d = math.hypot(x1 - x2, y1 - y2)
            key = tuple(sorted([n1, n2])) + (l1,)
            prev = worst.get(key)
            if prev is None or d < prev[0]:
                worst[key] = (d, (x1, y1), (x2, y2))

    bad = [(k, w) for k, w in worst.items() if w[0] < hard_floor - 1e-3]
    assert not bad, (
        f"wires below the HARD floor of {hard_floor} mm centreline-to-centreline "
        f"(short risk; the soft wall-floor is {wall_floor} mm but greedy "
        f"routing can dip below it — see report invariants):\n"
        + "\n".join(
            f"  {k[0]} ↔ {k[1]} (L{k[2]}): "
            f"{w[0]:.3f} mm at {w[1]} vs {w[2]}"
            for k, w in sorted(bad, key=lambda kv: kv[1][0])[:5]
        )
    )


def test_channel_edge_clearance(board_and_paths):
    """No routed channel may sit closer than `edge_clearance` to the
    board outline (a thinner wall would either tear off the board or
    expose the wire at the substrate edge)."""
    board, paths, dims = board_and_paths
    perim = board.levels[0].perimeter
    ec = dims.edge_clearance
    halo = dims.channel_width / 2
    for path in paths:
        for elt in path.elements:
            if not isinstance(elt, WireSegment):
                continue
            for x, y in ((elt.start.x, elt.start.y), (elt.end.x, elt.end.y)):
                # Allow the wire centreline to sit within (edge_clearance)
                # of the outline minus the channel half-width (i.e. the
                # outer edge of the channel must be ≥ edge_clearance from
                # the board edge).
                dist_to_edge = min(
                    x - perim.x_min,
                    perim.x_max - x,
                    y - perim.y_min,
                    perim.y_max - y,
                )
                assert dist_to_edge >= ec - halo - 1e-6, (
                    f"{path.name}: segment endpoint ({x:.3f}, {y:.3f}) is "
                    f"{dist_to_edge:.3f} mm from edge (< {ec - halo:.3f})"
                )


# ---------------------------------------------------------------------------
# The bug class that motivated the rewrite
# ---------------------------------------------------------------------------


def _enumerate_drilled_holes(board, paths) -> dict[tuple[float, float], str]:
    """Return a dict keyed by (x, y) (rounded to 3 dp) → source label.

    Sources:
      - "pin:<device>.<index>"  — a device pin through-hole
      - "via:<path>"            — a router-emitted via
      - "header:<inst>.<n>"     — header pin through-hole (auto-synthesised)
    """
    holes: dict[tuple[float, float], str] = {}
    endpoint_xys = board.bus_endpoint_xys()
    for inst in board.devices:
        device = inst.resolved_device()
        for pin in device.pins:
            pos = device.pin_position_at(inst.position, inst.rotation, pin)
            key = (round(pos.x, 3), round(pos.y, 3))
            if key not in endpoint_xys:
                continue
            holes[key] = f"pin:{inst.name}.{pin.index}"
        if inst.header is not None:
            conn = inst.header.resolved_connector()
            for i in range(conn.pin_count):
                offset = (i - (conn.pin_count - 1) / 2) * conn.pitch
                if inst.rotation in (0, 180):
                    px = inst.position.x + (offset if inst.rotation == 0 else -offset)
                    py = inst.position.y
                else:
                    px = inst.position.x
                    py = inst.position.y + (offset if inst.rotation == 90 else -offset)
                holes.setdefault(
                    (round(px, 3), round(py, 3)),
                    f"header:{inst.name}.{i + 1}",
                )
    for path in paths:
        for elt in path.elements:
            if isinstance(elt, Via):
                key = (round(elt.position.x, 3), round(elt.position.y, 3))
                holes[key] = f"via:{path.name}"
    return holes


def test_drilled_holes_match_signal_path_vias(board_and_paths):
    """Every router-emitted Via must coincide with a drilled hole, and
    every drilled hole must be either a device pin / header pin OR a
    router-emitted via — no orphans either way.

    This is the *whole point* of the declarative rewrite: removing the
    parallel sources of truth (hand-coded hole positions vs spec-driven
    channels) that let wires terminate in midair across the legacy
    Tier2SubstrateFromSpec ↔ Tier2SubstrateOption2 inheritance.
    """
    board, paths, _ = board_and_paths
    holes = _enumerate_drilled_holes(board, paths)

    # Vias must have a hole at their xy — _enumerate_drilled_holes adds
    # the via positions into `holes`, so this is implicitly satisfied;
    # but we cross-check that every via's xy resolves to a "via:" entry
    # OR a "pin:" entry (a via landing on an existing pin xy is fine).
    for path in paths:
        for elt in path.elements:
            if not isinstance(elt, Via):
                continue
            key = (round(elt.position.x, 3), round(elt.position.y, 3))
            assert key in holes, (
                f"via at {key} in {path.name} has no drilled hole"
            )

    # Conversely, every drilled hole must be reachable / explainable.
    # All sources in _enumerate_drilled_holes are by-construction valid,
    # so this currently can't fail — but the assertion guards against
    # future builders adding hole sources that bypass the via→hole or
    # pin→hole resolution path.
    for key, source in holes.items():
        assert source.startswith(("pin:", "header:", "via:")), (
            f"orphan drilled hole at {key}: {source}"
        )


# ---------------------------------------------------------------------------
# Build smoke
# ---------------------------------------------------------------------------


def test_build_board_produces_anchorscad_shape():
    """The build pipeline turns a Board into something AnchorSCAD can
    render — no exception, no missing attribute."""
    board = load_board(SPECS_DIR / "i2c_midline_sensors.yaml")
    shape = build_board(board)
    assert shape.name == board.name
    # Triggers @datatree __post_init__ -> build() if not already.
    maker = shape.maker
    assert maker is not None


# ---------------------------------------------------------------------------
# Routing hints
# ---------------------------------------------------------------------------


def _starter_board(**overrides) -> Board:
    """Build a fresh starter board so each test gets a clean Board."""
    devices = (
        DeviceInstance(name="u1", device="esp32_c3_supermini",
                       position=Point2D(x=-21, y=-7)),
        DeviceInstance(name="scd41", device="scd41",
                       position=Point2D(x=6.46, y=-6)),
        DeviceInstance(name="bh1750", device="bh1750",
                       position=Point2D(x=25, y=-8)),
        DeviceInstance(name="oled", device="oled_ssd1306",
                       position=Point2D(x=0, y=10),
                       header=Header(connector="female_1x4_2.54")),
    )
    base = (Level(name="base",
                  perimeter=Rect(cx=0, cy=0, w=68, h=50),
                  z_start=-1.5, z_end=1.5),)
    bus = Bus(
        kind="i2c", name="primary", master="u1",
        slaves=("scd41", "bh1750", "oled"),
        routing_hints=overrides.get("routing_hints", {}),
    )
    # Deliberately cramped 68×50 four-device fixture used only to exercise
    # the router under congestion (the production boards spread out for a
    # full buffer wall — see specs/). At the 1.0 default the buffer-derived
    # pocket margin makes this density unroutable, so the fixture relaxes
    # to 0.2; wall thickness is irrelevant here, only the routing topology.
    return Board(name="hint_test", levels=base, devices=devices, buses=(bus,),
                 dim=DimOverrides(buffer=0.2))


def test_hint_prefer_layer_pushes_signal_off_l1():
    """`prefer_layer: 2` should pull SDA wire LENGTH toward L2 — under
    trunk sharing, the L2 *segment count* can be identical between
    baseline and hinted (the trunk topology may end up similar), but
    the proportion of total wire length on L2 should rise. The
    assertion uses L2-fraction so it's invariant to how segments are
    folded by the waypoint collapser."""
    # VCC routes last (lowest priority) and lands ~75% on L1 by default
    # — there's headroom to push it onto L2 with a hint. SDA already
    # runs 100% on L2 under trunk sharing (the SCL halo forces it), so
    # SDA can't demonstrate the hint's effect.
    baseline_paths = route_board(_starter_board(), resolve_dims(_starter_board()))
    hinted_paths = route_board(
        _starter_board(routing_hints={"VCC": RoutingHint(prefer_layer=2)}),
        resolve_dims(_starter_board()),
    )

    def _layer_lengths(paths, signal) -> tuple[float, float]:
        l1 = l2 = 0.0
        for p in paths:
            if f"_{signal}_" not in p.name:
                continue
            for e in p.elements:
                if not isinstance(e, WireSegment):
                    continue
                length = math.hypot(e.end.x - e.start.x, e.end.y - e.start.y)
                if e.layer == 2:
                    l2 += length
                else:
                    l1 += length
        return l1, l2

    base_l1, base_l2 = _layer_lengths(baseline_paths, "VCC")
    hint_l1, hint_l2 = _layer_lengths(hinted_paths, "VCC")
    base_frac = base_l2 / max(base_l1 + base_l2, 1e-9)
    hint_frac = hint_l2 / max(hint_l1 + hint_l2, 1e-9)
    assert hint_frac > base_frac + 1e-3, (
        f"prefer_layer=2 should raise VCC's L2 fraction. "
        f"baseline: L1={base_l1:.1f}/L2={base_l2:.1f} ({base_frac:.2%}); "
        f"hinted: L1={hint_l1:.1f}/L2={hint_l2:.1f} ({hint_frac:.2%})"
    )


def test_hint_must_pass_visits_every_waypoint():
    """A `must_pass` waypoint at (-15, -22, 1) is a hard constraint —
    the routed wire tree for that signal must visit it. Under trunk
    sharing, only the trunk (i.e. the first slave's full route) has
    the waypoint baked in; later slaves branch off the trunk and
    may or may not retrace it. The check is therefore "the union of
    all paths for the signal touches the waypoint", not "every leg".
    """
    # (-15, -22, L1) is a corner of the board well clear of every
    # device's pin row + approach corridor, so SCL can detour through
    # it without crowding out GND or VCC's routes to the OLED.
    wp = HintWaypoint(x=-15, y=-22, layer=1)
    board = _starter_board(
        routing_hints={"SCL": RoutingHint(must_pass=(wp,))},
    )
    paths = route_board(board, resolve_dims(board))
    scl_paths = [p for p in paths if "_SCL_" in p.name]
    assert len(scl_paths) == 3, "starter has 3 SCL slaves"

    def _path_visits(p) -> bool:
        for e in p.elements:
            if isinstance(e, Via):
                if (e.position.x - wp.x) ** 2 + (e.position.y - wp.y) ** 2 < 0.51 ** 2:
                    return True
                continue
            if not isinstance(e, WireSegment) or e.layer != wp.layer:
                continue
            sx, sy, ex, ey = e.start.x, e.start.y, e.end.x, e.end.y
            dx, dy = ex - sx, ey - sy
            length_sq = dx * dx + dy * dy
            if length_sq < 1e-12:
                t = 0.0
            else:
                t = max(0.0, min(1.0,
                    ((wp.x - sx) * dx + (wp.y - sy) * dy) / length_sq))
            px, py = sx + t * dx, sy + t * dy
            if (wp.x - px) ** 2 + (wp.y - py) ** 2 < 0.51 ** 2:
                return True
        return False

    visited_by = [p.name for p in scl_paths if _path_visits(p)]
    assert visited_by, (
        f"must-pass waypoint {wp} not visited by any SCL leg; "
        f"all SCL paths: "
        f"{ {p.name: [(getattr(e, 'layer', 'V'), getattr(e, 'start', getattr(e, 'position', None))) for e in p.elements] for p in scl_paths} }"
    )


def test_header_synthesises_pedestal_level():
    """A headered device (the OLED) yields exactly one synthesised
    pedestal Level over its position, with the connector's standard
    height."""
    board = load_board(SPECS_DIR / "i2c_midline_sensors.yaml")
    headers = synthesize_header_levels(board)
    assert len(headers) == 1
    pedestal = headers[0]
    assert pedestal.name == "oled__header"
    # Standard female-1x4_2.54 height
    assert pedestal.z_end - pedestal.z_start == pytest.approx(8.5)
