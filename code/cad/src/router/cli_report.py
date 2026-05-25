"""Build per-substrate JSON reports for the gallery focus page.

For every routable substrate class (Tier1/Tier2 hand-coded + every
class auto-derived from `code/cad/specs/*.yaml`) this writes one
report to `code/web/src/reports/<snake_name>.json`. The stem matches
the AnchorSCAD-rendered GLB stem (= manifest entry name), so the
`.astro` focus page can resolve report → manifest entry by file name.

Each report has three sections:

  - `score`: routing-score breakdown returned by `score_paths`
    (total/L1/L2 length, via count, edge clearance, pedestal-underside
    L1, aggregate). Same numbers as `bin/score-routes`.
  - `invariants`: pass/fail for each routing invariant the test fixture
    enforces (45-degree angles, edge clearance, hole-pair clearance,
    voxel overlap, pin connectivity). Failures include a short message
    so the gallery can surface the first violation.
  - `holes`: every drilled hole on the substrate as (name, x, y,
    diameter). Lets the user spot "two close holes" issues without
    re-running the test fixture.

If `_routed_nets()` is empty or `_get_signal_paths()` raises, the
substrate is non-routable and the report is omitted (the focus page
renders a "no routing report available" placeholder when the JSON is
missing).

Spec-driven substrates also carry `spec_path` so the YAML editor on
the focus page can resolve the source file. Hand-coded classes leave
that field absent — the editor shows "not editable" for those.
"""

from __future__ import annotations

import json
import math
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from registry import camel_to_snake
from router.score import score_paths
from vitamins import substrate as S
from vitamins.substrate import (
    Point2D,
    SPEC_SUBSTRATES,
    Tier1Substrate,
    Tier2Substrate,
    Tier2SubstrateBundled,
    Tier2SubstrateFromSpec,
    Tier2SubstrateOption2,
    WireSegment,
    _pin_position,
)
from voxel_grid import (
    voxels_in_pcb_footprint_l2,
    voxels_in_segment,
    voxels_in_through_hole,
)


# cli_report.py → code/cad/src/router/, so parents[4] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_REPORTS_DIR = _REPO_ROOT / "code" / "web" / "src" / "reports"

# Match the test fixture: every hand-coded routable class plus every
# spec-discovered one. The fixture also lists Tier1, but Tier1 has no
# OLED pedestal — the report still works, only `pedestal` is 0.
_BASE_SUBSTRATE_CLASSES = [
    Tier1Substrate,
    Tier2Substrate,
    Tier2SubstrateBundled,
    Tier2SubstrateOption2,
    Tier2SubstrateFromSpec,
]

# Same as test_substrate_routing._ALLOWED_ANGLE_DEGREES.
_ALLOWED_ANGLE_DEGREES = (0.0, 45.0, 90.0, 135.0, 180.0, -45.0, -90.0, -135.0, -180.0)
_ANGLE_TOLERANCE_DEG = 0.05
_PIN_MATCH_TOLERANCE_MM = 0.05

_SIGNAL_PREFIXES = ("vcc", "gnd", "scl", "sda")


# --- pedestal box (copied from router.cli_score to avoid an import cycle) ---


def _pedestal_box(sub):
    d = sub.dim
    if not hasattr(d, "oled_pedestal_width"):
        return None
    cx, cy = 0.0, S._J4_Y
    hw = d.oled_pedestal_width / 2.0
    hd = d.oled_pedestal_depth / 2.0
    return (cx - hw, cy - hd, cx + hw, cy + hd)


# --- per-invariant evaluators (return (passed, message)) ---


def _eval_angles(sub) -> tuple[bool, str]:
    bad: list[str] = []
    for path in sub._get_signal_paths():
        for elem in path.elements:
            if not isinstance(elem, WireSegment):
                continue
            dx = elem.end.x - elem.start.x
            dy = elem.end.y - elem.start.y
            if math.hypot(dx, dy) < 1e-6:
                continue
            angle = math.degrees(math.atan2(dy, dx))
            if not any(abs(angle - a) < _ANGLE_TOLERANCE_DEG for a in _ALLOWED_ANGLE_DEGREES):
                bad.append(
                    f"{path.name} L{elem.layer}: "
                    f"({elem.start.x:.2f},{elem.start.y:.2f})→"
                    f"({elem.end.x:.2f},{elem.end.y:.2f}) at {angle:.2f}°"
                )
    if bad:
        return False, f"{len(bad)} non-45° segment(s); first: {bad[0]}"
    return True, "all segments at 0°/±45°/±90°/±135°/180°"


def _eval_edge_clearance(sub) -> tuple[bool, str]:
    d = sub.dim
    half_w = d.board_w / 2.0
    half_h = d.board_h / 2.0
    ch = d.channel_width / 2.0
    required = d.edge_clearance
    bad: list[str] = []
    for path in sub._get_signal_paths():
        for elem in path.elements:
            if not isinstance(elem, WireSegment):
                continue
            x_min = min(elem.start.x, elem.end.x) - ch
            x_max = max(elem.start.x, elem.end.x) + ch
            y_min = min(elem.start.y, elem.end.y) - ch
            y_max = max(elem.start.y, elem.end.y) + ch
            for edge, clr in (
                ("east", +half_w - x_max),
                ("west", x_min - (-half_w)),
                ("north", +half_h - y_max),
                ("south", y_min - (-half_h)),
            ):
                if clr < required:
                    bad.append(
                        f"{path.name} L{elem.layer} {edge}: clr {clr:+.2f} < {required:.2f}"
                    )
    if bad:
        return False, f"{len(bad)} violation(s); first: {bad[0]}"
    return True, f"all channels ≥ {required:.2f} mm from each edge"


def _eval_hole_pair_clearance(sub) -> tuple[bool, str]:
    d = sub.dim
    required = d.hole_pair_clearance
    holes = sub._drilled_hole_positions()

    def radius(name: str) -> float:
        if name.startswith("J4."):
            return d.receptacle_diameter / 2.0
        if name.endswith("_via"):
            return d.via_diameter / 2.0
        return d.hole_diameter / 2.0

    bad: list[str] = []
    for i, (p1, n1) in enumerate(holes):
        r1 = radius(n1)
        for j in range(i + 1, len(holes)):
            p2, n2 = holes[j]
            r2 = radius(n2)
            wall = math.hypot(p1.x - p2.x, p1.y - p2.y) - r1 - r2
            if wall < required:
                bad.append(
                    f"{n1} & {n2}: wall {wall:+.2f} mm < {required:.2f}"
                )
    if bad:
        return False, f"{len(bad)} pair(s); first: {bad[0]}"
    return True, f"all hole pairs ≥ {required:.2f} mm apart"


def _pin_signal_map(sub) -> dict[str, str]:
    out: dict[str, str] = {}
    for sig, net in sub._routed_nets().items():
        out[f"{net.master_pin.ref}.{net.master_pin.number}"] = sig.name.lower()
        for p in net.device_pins:
            out[f"{p.ref}.{p.number}"] = sig.name.lower()
    return out


def _hole_signal(name: str, pin_sig_map: dict[str, str]) -> str | None:
    if name in pin_sig_map:
        return pin_sig_map[name]
    prefix = name.split("_", 1)[0]
    if prefix in _SIGNAL_PREFIXES:
        return prefix
    return None


def _hole_diameter(sub, name: str) -> float:
    d = sub.dim
    if name.startswith("J4."):
        return d.receptacle_diameter
    if name.endswith("_via"):
        return d.via_diameter
    return d.hole_diameter


def _eval_voxel_overlap(sub) -> tuple[bool, str]:
    """Same logic as `test_no_voxel_overlap_between_signals`, condensed
    into a pass/fail message so the focus page can render a single
    badge per invariant."""
    paths = sub._get_signal_paths()
    holes = sub._drilled_hole_positions()
    sig_map = _pin_signal_map(sub)
    buffer = sub.dim.min_wall_thickness / 2.0

    owner: dict[tuple[int, int, int], tuple[str, str, str | None]] = {}
    for board_name, cx, cy, hw, hl in sub._module_pcb_footprints():
        for v in voxels_in_pcb_footprint_l2(cx, cy, hw, hl):
            owner[v] = ("board", board_name, None)
    for pt, name in holes:
        hsig = _hole_signal(name, sig_map)
        diam = _hole_diameter(sub, name)
        for v in voxels_in_through_hole(pt.x, pt.y, diam, buffer=buffer):
            owner[v] = ("hole", name, hsig)

    collisions: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for path in paths:
        psig = path.name.split("_", 1)[0]
        for elem in path.elements:
            if not isinstance(elem, WireSegment):
                continue
            for v in voxels_in_segment(elem, buffer=buffer):
                existing = owner.get(v)
                if existing is None:
                    owner[v] = ("wire", path.name, psig)
                    continue
                _, name, esig = existing
                if esig == psig:
                    continue
                key = (path.name, existing[0], name)
                if key in seen:
                    continue
                seen.add(key)
                collisions.append(
                    f"{path.name} L{elem.layer} ↔ {existing[0]} {name}"
                )

    if collisions:
        return False, f"{len(collisions)} collision(s); first: {collisions[0]}"
    return True, "no inter-signal voxel overlap"


def _path_endpoints(path) -> set[tuple[float, float]]:
    out: set[tuple[float, float]] = set()
    for elem in path.elements:
        if not isinstance(elem, WireSegment):
            continue
        out.add((round(elem.start.x, 3), round(elem.start.y, 3)))
        out.add((round(elem.end.x, 3), round(elem.end.y, 3)))
    return out


def _pin_is_in_endpoints(pin_xy: Point2D, endpoints) -> bool:
    for ex, ey in endpoints:
        if (
            abs(ex - pin_xy.x) < _PIN_MATCH_TOLERANCE_MM
            and abs(ey - pin_xy.y) < _PIN_MATCH_TOLERANCE_MM
        ):
            return True
    return False


def _eval_pin_connectivity(sub) -> tuple[bool, str]:
    paths_by_sig: dict[str, list] = {}
    for path in sub._get_signal_paths():
        sig = path.name.split("_", 1)[0]
        paths_by_sig.setdefault(sig, []).append(path)

    known_unconnected = set(sub._known_unconnected_pins())
    missing: list[str] = []
    for sig_enum, net in sub._routed_nets().items():
        sig = sig_enum.name.lower()
        sig_paths = paths_by_sig.get(sig, [])
        if not sig_paths:
            missing.append(f"{sig.upper()}: no path")
            continue
        endpoints: set[tuple[float, float]] = set()
        for p in sig_paths:
            endpoints |= _path_endpoints(p)
        for pin in [net.master_pin, *net.device_pins]:
            key = (sig_enum.name, pin.ref, pin.number)
            if key in known_unconnected:
                continue
            if not _pin_is_in_endpoints(_pin_position(pin), endpoints):
                missing.append(f"{sig.upper()}: {pin.ref}.{pin.number} unreached")
    if missing:
        return False, f"{len(missing)} unconnected; first: {missing[0]}"
    return True, "all routed pins reached by their signal path"


_INVARIANTS = (
    ("angles_45_or_90", "45° / 90° segments", _eval_angles),
    ("edge_clearance", "Edge clearance", _eval_edge_clearance),
    ("hole_pair_clearance", "Hole-pair clearance", _eval_hole_pair_clearance),
    ("voxel_overlap", "No inter-signal voxel overlap", _eval_voxel_overlap),
    ("pin_connectivity", "Pin connectivity", _eval_pin_connectivity),
)


# --- aggregate report ---


def _try_instantiate(cls):
    try:
        return cls()
    except Exception:
        return None


def _report_for(name: str, cls) -> dict | None:
    sub = _try_instantiate(cls)
    if sub is None:
        return None
    if not getattr(sub, "_routed_nets", None):
        return None
    nets = sub._routed_nets()
    if not nets:
        return None
    try:
        paths = sub._get_signal_paths()
    except Exception as exc:
        print(f"[substrate-report] {name}: _get_signal_paths failed: {exc}", file=sys.stderr)
        return None

    score = score_paths(
        paths,
        board_extents=(sub.dim.board_w, sub.dim.board_h),
        channel_width=sub.dim.channel_width,
        min_wall_thickness=sub.dim.min_wall_thickness,
        pedestal_box=_pedestal_box(sub),
    )

    invariants = []
    for key, label, fn in _INVARIANTS:
        try:
            passed, message = fn(sub)
        except Exception as exc:
            passed, message = False, f"evaluator raised: {exc}"
        invariants.append({"key": key, "label": label, "passed": passed, "message": message})

    holes = sub._drilled_hole_positions()
    hole_rows = [
        {
            "name": hn,
            "x": round(pt.x, 3),
            "y": round(pt.y, 3),
            "diameter": round(_hole_diameter(sub, hn), 3),
        }
        for pt, hn in holes
    ]

    spec_path = None
    if hasattr(sub, "spec_path"):
        # Spec-driven classes carry the rel path under code/cad/specs/.
        spec_path = getattr(sub, "spec_path", None)

    return {
        "name": name,
        "class": cls.__name__,
        "spec_path": spec_path,
        "score": {
            "total_length_mm": round(score.total_length_mm, 2),
            "l1_length_mm": round(score.l1_length_mm, 2),
            "l2_length_mm": round(score.l2_length_mm, 2),
            "via_count": score.via_count,
            "edge_clearance_min_mm": round(score.edge_clearance_min_mm, 3),
            "pedestal_underside_mm": round(score.pedestal_underside_mm, 3),
            "aggregate": round(score.aggregate, 2),
        },
        "invariants": invariants,
        "holes": hole_rows,
    }


def _name_for(cls) -> str:
    """Mirror registry.camel_to_snake so the report stem matches the
    AnchorSCAD-rendered GLB stem (and the manifest entry name)."""
    return camel_to_snake(cls.__name__)


def _all_classes() -> Iterable[tuple[str, type]]:
    seen: set[str] = set()
    for cls in _BASE_SUBSTRATE_CLASSES:
        name = _name_for(cls)
        if name in seen:
            continue
        seen.add(name)
        yield name, cls
    for cls in SPEC_SUBSTRATES.values():
        name = _name_for(cls)
        if name in seen:
            continue
        seen.add(name)
        yield name, cls


def main(argv: list[str]) -> int:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    for name, cls in _all_classes():
        try:
            report = _report_for(name, cls)
        except Exception as exc:
            print(f"[substrate-report] {name}: report failed: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            report = None
        if report is None:
            skipped += 1
            print(f"[substrate-report] skip {name} (not routable)")
            continue
        (_REPORTS_DIR / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n")
        written += 1
        print(
            f"[substrate-report] wrote {name}.json — "
            f"score={report['score']['aggregate']:.1f} "
            f"holes={len(report['holes'])} "
            f"invariants={sum(1 for inv in report['invariants'] if inv['passed'])}"
            f"/{len(report['invariants'])} pass"
        )
    print(f"[substrate-report] done: {written} written, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
