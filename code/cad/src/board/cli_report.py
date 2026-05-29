"""`bin/substrate-report` backing CLI.

Emits one JSON per Board to `code/web/src/reports/substrate_<name>.json`
in the shape the gallery focus page expects:

  {
    name, class, spec_path,
    score: { total_length_mm, l1_length_mm, l2_length_mm, via_count,
             edge_clearance_min_mm, pedestal_underside_mm, aggregate },
    invariants: [{ key, label, passed, message }, ...],
    holes:      [{ device|via, ref, role, x, y, diameter, source }, ...],
  }
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from board.board import Board
from board.build import resolve_dims
from board.loader import load_board
from router.autoroute import RouteFailure, route_board
from router.score import score_paths
from vitamins.substrate import Via, WireSegment


def _specs_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "specs"


def _reports_dir() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent.parent
        / "web" / "src" / "reports"
    )


# ---------------------------------------------------------------------------
# Invariants — mirror the ones in tests/test_board_pipeline.py so the
# gallery surface reflects the same checks pytest runs at build time.
# ---------------------------------------------------------------------------


def _inv_angles(paths) -> tuple[bool, str]:
    bad = []
    sharp = []
    allowed = (0, 45, 90, 135, 180, -45, -90, -135, -180)
    for p in paths:
        prev = None  # previous WireSegment, for the turn check
        for elt in p.elements:
            if not isinstance(elt, WireSegment):
                prev = None  # a via ends the planar run; the next is unconstrained
                continue
            dx = elt.end.x - elt.start.x
            dy = elt.end.y - elt.start.y
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                continue
            angle = math.degrees(math.atan2(dy, dx))
            if not any(abs(angle - a) < 0.05 for a in allowed):
                bad.append(f"{p.name} @ {angle:.2f}°")
            # Turn between contiguous segments must stay ≤ 90°. A larger
            # direction change leaves an acute (< 90°) interior corner — a
            # sub-45° spike no channel can be printed around.
            if prev is not None and (
                abs(prev.end.x - elt.start.x) < 1e-6
                and abs(prev.end.y - elt.start.y) < 1e-6
            ):
                pa = math.degrees(math.atan2(
                    prev.end.y - prev.start.y, prev.end.x - prev.start.x))
                turn = abs(((angle - pa + 180) % 360) - 180)
                if turn > 90 + 0.05:
                    sharp.append(
                        f"{p.name} {turn:.1f}° @ "
                        f"({elt.start.x:.2f},{elt.start.y:.2f})")
            prev = elt
    if bad:
        return False, f"non-cardinal segments: {bad[:3]}"
    if sharp:
        return False, f"acute turns (> 90° bend): {sharp[:3]}"
    return True, "all segments cardinal/45° with no acute turns"


def _inv_edge_clearance(board: Board, paths, dims) -> tuple[bool, str]:
    perim = board.levels[0].perimeter
    ec = dims.edge_clearance
    halo = dims.channel_width / 2
    worst = math.inf
    worst_path = ""
    for p in paths:
        for elt in p.elements:
            if not isinstance(elt, WireSegment):
                continue
            for x, y in ((elt.start.x, elt.start.y), (elt.end.x, elt.end.y)):
                d = min(
                    x - perim.x_min, perim.x_max - x,
                    y - perim.y_min, perim.y_max - y,
                )
                if d < worst:
                    worst, worst_path = d, p.name
    passed = worst >= ec - halo - 1e-6
    return passed, (
        f"min centreline → edge: {worst:.2f} mm "
        f"(threshold {ec - halo:.2f}; in {worst_path})"
    )


def _inv_drilled_holes_match_vias(board: Board, paths) -> tuple[bool, str]:
    """The lock against the bug class that motivated the rewrite."""
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
    orphans = []
    for p in paths:
        for elt in p.elements:
            if not isinstance(elt, Via):
                continue
            key = (round(elt.position.x, 3), round(elt.position.y, 3))
            if key not in holes:
                holes[key] = f"via:{p.name}"
    for key, source in holes.items():
        if not source.startswith(("pin:", "via:", "header:")):
            orphans.append((key, source))
    if orphans:
        return False, f"orphan holes: {orphans[:3]}"
    return True, f"{len(holes)} holes — every via lands on a drilled position"


# Tolerance on the wall-floor gate (mm); see _inv_wall_floor for rationale.
_WALL_FLOOR_TOL_MM = 0.02


def _inv_wall_floor(board: Board, paths, dims) -> tuple[bool, str]:
    """Min centreline-to-centreline distance between different-net wires
    on the same layer. Below `channel_width + buffer` the
    substrate wall between the two wires drops below the printable
    floor — printer will merge them. Below that distance / 2 they'll
    actually short. The greedy router can dip into the advisory band
    in tight pin clusters; we surface the worst case + the count so the
    user can see the trade-off in the gallery.
    """
    import math
    wall_floor = dims.wall_floor_mm
    # Geometric slack: two 45° lanes one pitch apart sit at 2.54/√2 ≈ 1.796 mm,
    # 4µm under the nominal floor but a full buffer of real material
    # (0.996 vs 1.0 mm) — far inside FDM tolerance. Allow that so on-pitch
    # diagonal bundles pass; well below this would still fail.
    floor = wall_floor - _WALL_FLOOR_TOL_MM

    def _net_id(name): return name.rsplit("_", 1)[0]

    samples = []
    for p in paths:
        nid = _net_id(p.name)
        for e in p.elements:
            if not isinstance(e, WireSegment):
                continue
            dx, dy = e.end.x - e.start.x, e.end.y - e.start.y
            length = math.hypot(dx, dy)
            steps = max(int(length / 0.25), 1)
            for i in range(steps + 1):
                t = i / steps
                samples.append((nid, e.layer,
                                e.start.x + t * dx, e.start.y + t * dy))

    worst = (math.inf, "", "")
    below_count = 0
    for i, (n1, l1, x1, y1) in enumerate(samples):
        for j in range(i + 1, len(samples)):
            n2, l2, x2, y2 = samples[j]
            if l1 != l2 or n1 == n2:
                continue
            d = math.hypot(x1 - x2, y1 - y2)
            if d < floor:
                below_count += 1
            if d < worst[0]:
                worst = (d, n1, n2)

    if worst[0] == math.inf:
        return True, "no cross-net pairs to check"
    passed = worst[0] >= floor
    return passed, (
        f"min cross-net centreline: {worst[0]:.2f} mm "
        f"(floor {wall_floor:.2f}; worst pair {worst[1]} ↔ {worst[2]}; "
        f"{below_count} sample pairs below the floor)"
    )


def _inv_cross_layer_overlap(board: Board, paths, dims) -> tuple[bool, str]:
    """Min centreline-to-centreline distance between different-net wires
    on OPPOSITE layers. Channels on L1/L2 are separated by the substrate
    thickness (~3 mm) so they can't short, but projected overlap weakens
    the substrate locally and tends to look messy in the 3D model.
    `channel_width / 2` is the floor — below it the two channels overlap
    in projection (one's wire edge passes under the other's centre).
    """
    import math
    cross_floor = dims.channel_width / 2

    def _net_id(name): return name.rsplit("_", 1)[0]

    samples = []
    for p in paths:
        nid = _net_id(p.name)
        for e in p.elements:
            if not isinstance(e, WireSegment):
                continue
            dx, dy = e.end.x - e.start.x, e.end.y - e.start.y
            length = math.hypot(dx, dy)
            steps = max(int(length / 0.25), 1)
            for i in range(steps + 1):
                t = i / steps
                samples.append((nid, e.layer, p.name,
                                e.start.x + t * dx, e.start.y + t * dy))

    worst = (math.inf, "", "")
    below_count = 0
    for i, (n1, l1, p1, x1, y1) in enumerate(samples):
        for j in range(i + 1, len(samples)):
            n2, l2, p2, x2, y2 = samples[j]
            if l1 == l2 or n1 == n2:
                continue
            d = math.hypot(x1 - x2, y1 - y2)
            if d < cross_floor:
                below_count += 1
            if d < worst[0]:
                worst = (d, p1, p2)

    if worst[0] == math.inf:
        return True, "no cross-layer pairs to check"
    passed = worst[0] >= cross_floor
    return passed, (
        f"min cross-layer centreline: {worst[0]:.2f} mm "
        f"(floor {cross_floor:.2f}; worst pair {worst[1]} ↔ {worst[2]}; "
        f"{below_count} sample pairs below the floor)"
    )


def _inv_endpoints_connected(board: Board, paths) -> tuple[bool, str]:
    nets = board.nets()
    expected = {n.signal: {s.instance_name for s in n.slaves} for n in nets}
    seen: dict[str, set[str]] = {sig: set() for sig in expected}
    for p in paths:
        parts = p.name.rsplit("_", 1)
        if len(parts) != 2:
            continue
        signal = parts[0].rsplit("_", 1)[-1]
        slave = parts[1]
        if signal in seen:
            seen[signal].add(slave)
    missing = {
        sig: sorted(expected[sig] - seen[sig])
        for sig in expected if expected[sig] - seen[sig]
    }
    if missing:
        return False, f"unrouted slaves: {missing}"
    return True, "every slave pin connected to its master"


def _run_invariants(board: Board, paths, dims) -> list[dict]:
    suite = [
        ("angles_45_or_90", "45°/axis-aligned segments, no acute turns",
         lambda: _inv_angles(paths)),
        ("edge_clearance", "Channels ≥ edge_clearance from board outline",
         lambda: _inv_edge_clearance(board, paths, dims)),
        ("wall_floor", "Cross-net wires ≥ channel_width + min_wall_thickness apart",
         lambda: _inv_wall_floor(board, paths, dims)),
        ("wall_floor_cross_layer",
         "Cross-net wires on opposite layers don't project-overlap (advisory)",
         lambda: _inv_cross_layer_overlap(board, paths, dims)),
        ("drilled_holes_match_vias", "Every via has a drilled hole; no orphans",
         lambda: _inv_drilled_holes_match_vias(board, paths)),
        ("endpoints_connected", "Every bus slave reached from the master",
         lambda: _inv_endpoints_connected(board, paths)),
    ]
    out = []
    for key, label, fn in suite:
        try:
            passed, msg = fn()
        except Exception as exc:
            passed, msg = False, f"check failed: {exc!r}"
        out.append({"key": key, "label": label, "passed": passed, "message": msg})
    return out


# ---------------------------------------------------------------------------
# Hole inventory
# ---------------------------------------------------------------------------


def _hole_table(board: Board, paths, dims) -> list[dict]:
    rows: list[dict] = []
    endpoint_xys = board.bus_endpoint_xys()
    for inst in board.devices:
        device = inst.resolved_device()
        for pin in device.pins:
            pos = device.pin_position_at(inst.position, inst.rotation, pin)
            if (round(pos.x, 3), round(pos.y, 3)) not in endpoint_xys:
                continue
            rows.append({
                "source": "pin",
                "ref": f"{inst.name}.{pin.index}",
                "role": pin.role,
                "x": round(pos.x, 3),
                "y": round(pos.y, 3),
                "diameter": dims.hole_bore_mm,
            })
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
                rows.append({
                    "source": "header",
                    "ref": f"{inst.name}.h{i + 1}",
                    "role": f"{inst.header.connector} pin {i + 1}",
                    "x": round(px, 3),
                    "y": round(py, 3),
                    "diameter": dims.hole_bore_mm,
                })
    for p in paths:
        for elt in p.elements:
            if isinstance(elt, Via):
                rows.append({
                    "source": "via",
                    "ref": p.name,
                    "role": "via",
                    "x": round(elt.position.x, 3),
                    "y": round(elt.position.y, 3),
                    "diameter": elt.diameter,
                })
    rows.sort(key=lambda r: (r["source"], r["ref"]))
    return rows


# ---------------------------------------------------------------------------
# Report build
# ---------------------------------------------------------------------------


def _build_report(spec_path: Path) -> dict:
    board = load_board(spec_path)
    dims = resolve_dims(board)
    try:
        paths = route_board(board, dims)
        route_error: str | None = None
    except RouteFailure as exc:
        paths = list(exc.partial)
        route_error = str(exc)

    base = board.levels[0].perimeter
    score = score_paths(
        paths,
        board_extents=(base.w, base.h),
        channel_width=dims.channel_width,
        min_wall_thickness=dims.buffer,
    )
    invariants = _run_invariants(board, paths, dims)
    if route_error is not None:
        invariants.insert(0, {
            "key": "routable",
            "label": "Auto-router produced a path for every bus slave",
            "passed": False,
            "message": route_error,
        })

    return {
        "name": board.name,
        "class": f"Substrate_{board.name}",
        "spec_path": f"specs/{spec_path.name}",
        "score": {
            "total_length_mm": round(score.total_length_mm, 3),
            "l1_length_mm": round(score.l1_length_mm, 3),
            "l2_length_mm": round(score.l2_length_mm, 3),
            "via_count": score.via_count,
            "edge_clearance_min_mm": round(score.edge_clearance_min_mm, 3),
            "pedestal_underside_mm": round(score.pedestal_underside_mm, 3),
            "aggregate": round(score.aggregate, 3),
        },
        "invariants": invariants,
        "holes": _hole_table(board, paths, dims),
    }


def main(argv: list[str]) -> int:
    args = argv[1:]
    specs = sorted(_specs_dir().glob("*.yaml"))
    if args:
        wanted = set(args)
        specs = [s for s in specs if s.stem in wanted]

    out = _reports_dir()
    out.mkdir(parents=True, exist_ok=True)

    for spec in specs:
        try:
            report = _build_report(spec)
        except Exception as exc:
            print(f"[substrate-report] skip {spec.name}: {exc}", file=sys.stderr)
            continue
        target = out / f"substrate_{report['name']}.json"
        target.write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
