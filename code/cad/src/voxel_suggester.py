"""Routing-suggestion pass — advisory companion to the voxel-overlap
gate at `tests/test_substrate_routing.py`.

For each axis-aligned L-bend in a routed path, rasterize the diagonal
(45°) alternative that cuts the corner and check whether it still
passes the wall-buffer test against ALL other features (foreign
signals' channels, foreign pin holes, module boards). If the
diagonal is clear, emit a suggestion with the wire-length savings.

This is a NON-failing advisory — the substrate doesn't need to
follow the suggestions, and not all suggestions are net-positive
(an axis-aligned route is often easier to thread bare wire through
manually). The pass surfaces opportunities; humans pick which to
take.

Same-signal voxel overlap is allowed (a diagonal that crosses its
own segments' inflated rasterization is the design intent — they
belong to the same wire).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from vitamins.substrate import (
    Point2D,
    SignalPath,
    Tier1Substrate,
    Tier2Substrate,
    Tier2SubstrateBundled,
    WireSegment,
)
from voxel_grid import (
    voxels_in_pcb_footprint_l2,
    voxels_in_segment,
    voxels_in_through_hole,
)


_SIGNAL_PREFIXES = ("vcc", "gnd", "scl", "sda")


@dataclass
class ChamferSuggestion:
    """One advisory: replace two axis-aligned segments at `path_name`
    with a single diagonal from `seg1.start` to `seg2.end`."""
    path_name: str
    layer: int
    elbow: Point2D
    seg1: WireSegment
    seg2: WireSegment
    diagonal_length: float
    original_length: float

    @property
    def saved_mm(self) -> float:
        return self.original_length - self.diagonal_length


def _is_right_angle(seg1: WireSegment, seg2: WireSegment) -> bool:
    """True iff seg1 and seg2 form a right angle (one runs along a
    coordinate axis, the other along the perpendicular one), are on
    the same layer, and seg1.end == seg2.start."""
    if seg1.layer != seg2.layer:
        return False
    if seg1.end != seg2.start:
        return False
    dx1 = seg1.end.x - seg1.start.x
    dy1 = seg1.end.y - seg1.start.y
    dx2 = seg2.end.x - seg2.start.x
    dy2 = seg2.end.y - seg2.start.y
    is_axis_aligned_1 = (abs(dx1) < 1e-6) != (abs(dy1) < 1e-6)
    is_axis_aligned_2 = (abs(dx2) < 1e-6) != (abs(dy2) < 1e-6)
    if not (is_axis_aligned_1 and is_axis_aligned_2):
        return False
    # One must be horizontal and the other vertical (i.e. perpendicular).
    horiz_1 = abs(dy1) < 1e-6
    horiz_2 = abs(dy2) < 1e-6
    return horiz_1 != horiz_2


def _pin_signal_map(sub) -> dict[str, str]:
    out: dict[str, str] = {}
    for sig, net in sub._routed_nets().items():
        out[f"{net.master_pin.ref}.{net.master_pin.number}"] = sig.name.lower()
        for p in net.device_pins:
            out[f"{p.ref}.{p.number}"] = sig.name.lower()
    return out


def _path_signal(path_name: str) -> str:
    return path_name.split("_", 1)[0]


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


def _build_owner_grid(sub) -> dict[tuple[int, int, int], tuple[str, str, str | None]]:
    """Rasterize every existing feature into a voxel-owner dict using
    `sub._get_signal_paths()` as the wire set."""
    return _build_owner_grid_from(sub, sub._get_signal_paths())


def _build_owner_grid_from(
    sub,
    paths: Iterable[SignalPath],
) -> dict[tuple[int, int, int], tuple[str, str, str | None]]:
    """Rasterize boards, holes, and a given path set into a voxel-owner
    dict. Exposed so chamfer-application can rebuild against the
    in-progress (partly chamfered) path list."""
    buffer = sub.dim.min_wall_thickness / 2.0
    owner: dict[tuple[int, int, int], tuple[str, str, str | None]] = {}

    for board_name, cx, cy, hw, hl in sub._module_pcb_footprints():
        for v in voxels_in_pcb_footprint_l2(cx, cy, hw, hl):
            owner[v] = ("board", board_name, None)

    sig_map = _pin_signal_map(sub)
    for pt, name in sub._drilled_hole_positions():
        hsig = _hole_signal(name, sig_map)
        diam = _hole_diameter(sub, name)
        for v in voxels_in_through_hole(pt.x, pt.y, diam, buffer=buffer):
            owner[v] = ("hole", name, hsig)

    for path in paths:
        psig = _path_signal(path.name)
        for elem in path.elements:
            if not isinstance(elem, WireSegment):
                continue
            for v in voxels_in_segment(elem, buffer=buffer):
                if v not in owner:
                    owner[v] = ("wire", path.name, psig)
    return owner


def _diagonal_collides(
    diagonal: WireSegment,
    signal: str,
    owner: dict[tuple[int, int, int], tuple[str, str, str | None]],
    buffer: float,
    original_voxels: set[tuple[int, int, int]],
) -> bool:
    """True iff the diagonal would collide with anything owned by a
    different signal, OR with any None-signal owner (board, unrouted
    hole). Voxels already claimed by the diagonal's own original
    L-bend segments are exempt — those are the voxels the chamfer
    would reclaim."""
    for v in voxels_in_segment(diagonal, buffer=buffer):
        if v in original_voxels:
            continue
        existing = owner.get(v)
        if existing is None:
            continue
        kind, name, esig = existing
        if esig == signal:
            continue
        return True
    return False


def find_chamfer_suggestions(sub, paths: Iterable[SignalPath] | None = None) -> list[ChamferSuggestion]:
    """Return all chamfer opportunities. A chamfer opportunity is an
    L-bend in some routed path whose diagonal alternative passes the
    wall-buffer voxel test against all other features.

    `paths` defaults to `sub._get_signal_paths()` — pass an explicit
    list to inspect non-default path sets (e.g. when applying
    chamfers in `apply_chamfers`, the intermediate orthogonal paths
    must be evaluated, not the post-chamfer ones)."""
    suggestions: list[ChamferSuggestion] = []
    if paths is None:
        paths = list(sub._get_signal_paths())
    else:
        paths = list(paths)
    owner = _build_owner_grid_from(sub, paths)
    buffer = sub.dim.min_wall_thickness / 2.0

    for path in paths:
        psig = _path_signal(path.name)
        wire_segs = [e for e in path.elements if isinstance(e, WireSegment)]

        # Track voxels owned by this path so we can exempt them when
        # testing the diagonal (the diagonal will replace some of
        # those voxels).
        path_voxels: set[tuple[int, int, int]] = set()
        for seg in wire_segs:
            for v in voxels_in_segment(seg, buffer=buffer):
                path_voxels.add(v)

        # Look at consecutive pairs forming a right-angle L.
        for i in range(len(wire_segs) - 1):
            s1 = wire_segs[i]
            s2 = wire_segs[i + 1]
            if not _is_right_angle(s1, s2):
                continue
            # Elbow must be a "free" corner — no other path segment
            # ends or starts at the same xy on the same layer. (A
            # junction with another segment must be preserved.)
            elbow = s1.end
            joined = 0
            for seg in wire_segs:
                if seg is s1 or seg is s2:
                    continue
                if seg.layer != s1.layer:
                    continue
                if seg.start == elbow or seg.end == elbow:
                    joined += 1
            if joined > 0:
                continue

            diagonal = WireSegment(s1.start, s2.end, s1.layer)
            if _diagonal_collides(diagonal, psig, owner, buffer, path_voxels):
                continue

            seg_len = lambda s: math.hypot(s.end.x - s.start.x, s.end.y - s.start.y)
            orig_len = seg_len(s1) + seg_len(s2)
            diag_len = seg_len(diagonal)
            if orig_len - diag_len < 0.1:
                continue  # not a meaningful saving
            suggestions.append(ChamferSuggestion(
                path_name=path.name,
                layer=s1.layer,
                elbow=elbow,
                seg1=s1,
                seg2=s2,
                diagonal_length=diag_len,
                original_length=orig_len,
            ))
    return suggestions


# --- chamfer application ----------------------------------------------------


def _chamfer_path_once(
    path: SignalPath,
    sub,
    owner_without_self: dict[tuple[int, int, int], tuple[str, str, str | None]],
    buffer: float,
) -> tuple[SignalPath, float]:
    """Try to apply one safe chamfer to `path`. Returns the (possibly
    new) path and the saved-mm amount. If no safe chamfer is found,
    returns the original path and 0.

    Strategy: scan consecutive segment pairs left-to-right, take the
    FIRST safe non-junction L-bend whose diagonal passes the
    buffer test. (Greedy — not optimal, but adequate for the
    current paths.)"""
    wire_segs: list[WireSegment] = []
    others: list = []  # non-WireSegment elements (vias) and their indices
    for elem in path.elements:
        if isinstance(elem, WireSegment):
            wire_segs.append(elem)
        else:
            others.append(elem)

    # Own voxels — exempt from the diagonal-collision check.
    own_voxels: set[tuple[int, int, int]] = set()
    for seg in wire_segs:
        for v in voxels_in_segment(seg, buffer=buffer):
            own_voxels.add(v)

    psig = _path_signal(path.name)

    for i in range(len(wire_segs) - 1):
        s1 = wire_segs[i]
        s2 = wire_segs[i + 1]
        if not _is_right_angle(s1, s2):
            continue
        elbow = s1.end
        joined = 0
        for seg in wire_segs:
            if seg is s1 or seg is s2:
                continue
            if seg.layer != s1.layer:
                continue
            if seg.start == elbow or seg.end == elbow:
                joined += 1
        if joined > 0:
            continue

        diagonal = WireSegment(s1.start, s2.end, s1.layer)
        if _diagonal_collides(diagonal, psig, owner_without_self, buffer, own_voxels):
            continue

        seg_len = lambda s: math.hypot(s.end.x - s.start.x, s.end.y - s.start.y)
        orig_len = seg_len(s1) + seg_len(s2)
        diag_len = seg_len(diagonal)
        if orig_len - diag_len < 0.1:
            continue

        # Rebuild the path's elements list, replacing s1 + s2 with the diagonal.
        new_elements = []
        for elem in path.elements:
            if elem is s1:
                new_elements.append(diagonal)
            elif elem is s2:
                continue  # absorbed into diagonal
            else:
                new_elements.append(elem)
        return SignalPath(name=path.name, elements=tuple(new_elements)), orig_len - diag_len

    return path, 0.0


def apply_chamfers(sub, paths: Iterable[SignalPath]) -> list[SignalPath]:
    """Apply all safe 45° chamfers to `paths`. Iterates until no more
    chamfers can be applied — each pass re-builds the owner grid
    against the current (partly chamfered) path set so adjacent
    chamfers can compose.

    Same-signal voxel overlap is allowed; the diagonal only fails if
    it intrudes on a different-signal channel, a foreign pin hole,
    or a module PCB footprint at the L2 z-band."""
    paths = list(paths)
    buffer = sub.dim.min_wall_thickness / 2.0
    # Cap iterations — should converge in O(elbows) but be defensive.
    for _ in range(64):
        any_change = False
        for i, path in enumerate(paths):
            owner = _build_owner_grid_from(
                sub, [p for j, p in enumerate(paths) if j != i]
            )
            new_path, saved = _chamfer_path_once(path, sub, owner, buffer)
            if saved > 0.0:
                paths[i] = new_path
                any_change = True
        if not any_change:
            break
    return paths


# --- markdown report --------------------------------------------------------


def emit_markdown_report(sub_cls_name: str, suggestions: list[ChamferSuggestion]) -> str:
    if not suggestions:
        return f"### {sub_cls_name}\n\nNo chamfer opportunities found.\n"
    lines = [f"### {sub_cls_name}\n"]
    lines.append("| path | layer | elbow (x, y) | original length | diagonal length | saved |")
    lines.append("|---|---|---|---|---|---|")
    total_saved = 0.0
    for s in sorted(suggestions, key=lambda s: -s.saved_mm):
        lines.append(
            f"| {s.path_name} | L{s.layer} | ({s.elbow.x:.2f}, {s.elbow.y:.2f}) | "
            f"{s.original_length:.2f} mm | {s.diagonal_length:.2f} mm | "
            f"{s.saved_mm:.2f} mm |"
        )
        total_saved += s.saved_mm
    lines.append("")
    lines.append(f"**Total potential wire saved: {total_saved:.2f} mm**\n")
    return "\n".join(lines)


def main() -> int:
    classes = [Tier1Substrate, Tier2Substrate, Tier2SubstrateBundled]
    print("# Routing chamfer suggestions\n")
    print("Advisory pass — none of these are required. Each suggestion")
    print("replaces an axis-aligned L-bend in a routed path with a")
    print("single 45° diagonal that still satisfies the printable wall")
    print("buffer (failure mode #7 in `.deepwork/jobs/printable_pcb/job.yml`).")
    print()
    for cls in classes:
        sub = cls()
        suggestions = find_chamfer_suggestions(sub)
        print(emit_markdown_report(cls.__name__, suggestions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
