"""Voxel-based physical-overlap invariant for routed substrates.

Every routing channel and every drilled hole has a physical extent
(width, depth, layer-band z). Rasterize each into a 3D voxel grid
inflated by half the substrate's `min_wall_thickness` (the FDM
printability floor). If two voxels are claimed by different "owners"
(different signals, or a signal and a foreign pin hole), either the
wires would physically touch and short, OR the substrate wall between
them is below the printable floor and the two voids merge during
printing — failure mode #7 in
`.deepwork/jobs/printable_pcb/job.yml`.

This single test replaces the previous pair of hand-coded geometric
checks (`no_same_layer_crossings` + `no_channel_traverses_foreign_pin_hole`)
because rasterization handles diagonals, vias, partial-overlap, and
any future topology uniformly — no per-shape math.

Tests are parametrized over every routing-capable substrate class.
Each class exposes its hole list via `_drilled_hole_positions()` and
its routed nets via `_routed_nets()`.
"""

from __future__ import annotations

import math

import pytest

from vitamins.substrate import (
    Point2D,
    Tier1Substrate,
    Tier2Substrate,
    Tier2SubstrateBundled,
    WireSegment,
    _pin_position,
)
from voxel_grid import (
    voxels_in_pcb_footprint_l2 as _voxels_in_pcb_footprint_l2,
    voxels_in_segment as _voxels_in_segment,
    voxels_in_through_hole as _voxels_in_through_hole,
    vx_world as _vx_world,
    vy_world as _vy_world,
)


@pytest.fixture(
    params=[Tier1Substrate, Tier2Substrate, Tier2SubstrateBundled],
    ids=lambda cls: cls.__name__,
)
def substrate(request):
    return request.param()


# --- ownership lookup --------------------------------------------------------


_SIGNAL_PREFIXES = ("vcc", "gnd", "scl", "sda")


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
    """Return the routed signal that owns a drilled hole, or None if
    the hole is unrouted (e.g. SCL pin J1B.2 in the bundled topology)."""
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


# --- the test ----------------------------------------------------------------


def test_no_voxel_overlap_between_signals(substrate):
    """Rasterize every routed channel and every drilled hole into a
    3D voxel grid, INFLATED by half the substrate's `min_wall_thickness`
    so the test catches not just zero-distance overlap but also
    sub-printable wall thickness between adjacent voids (failure mode #7).
    Each voxel records its owning signal (or None for an unrouted hole).
    Two voxels with different owners overlapping means EITHER the wires
    physically touch and short, OR the substrate wall between them is
    below the FDM printable floor and the two voids merge during print.

    Same-signal overlap is allowed (a wire entering its own pin hole
    or via is the design intent).

    Board footprints are NOT inflated — they're physical PCBs, not
    substrate voids, so they're subject to direct-contact rules but
    not to wall-thickness rules."""
    paths = substrate._get_signal_paths()
    holes = substrate._drilled_hole_positions()
    sig_map = _pin_signal_map(substrate)
    buffer = substrate.dim.min_wall_thickness / 2.0

    # owner: voxel → (kind, name, signal_or_None)
    owner: dict[tuple[int, int, int], tuple[str, str, str | None]] = {}

    # Sensor PCB footprints at the L2 z-band — boards sitting in
    # pocket cavities. Marked first so wires landing here are flagged
    # as board-contact (signal-less owner). Pin-hole voxels overwrite
    # these (a pin hole inside a pocket is a deliberate cut through
    # the PCB and the wire IS supposed to reach it). Not inflated.
    for board_name, cx, cy, hw, hl in substrate._module_pcb_footprints():
        for v in _voxels_in_pcb_footprint_l2(cx, cy, hw, hl):
            owner[v] = ("board", board_name, None)

    # Holes next (override board voxels at pin xy — the pin hole is
    # a through-hole CUT through the PCB and the wire reaches it).
    # Inflated by `buffer` so a foreign channel passing too close
    # to a pin hole trips on the inflated boundary.
    for pt, name in holes:
        hsig = _hole_signal(name, sig_map)
        diam = _hole_diameter(substrate, name)
        for v in _voxels_in_through_hole(pt.x, pt.y, diam, buffer=buffer):
            owner[v] = ("hole", name, hsig)

    collisions: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    for path in paths:
        psig = _path_signal(path.name)
        for elem in path.elements:
            if not isinstance(elem, WireSegment):
                continue
            for v in _voxels_in_segment(elem, buffer=buffer):
                existing = owner.get(v)
                if existing is None:
                    owner[v] = ("wire", path.name, psig)
                    continue
                kind, name, esig = existing
                if esig == psig:
                    continue  # same signal — OK (or own pin/via)
                key = (path.name, kind, name)
                if key in seen:
                    continue
                seen.add(key)
                wx = _vx_world(v[0])
                wy = _vy_world(v[1])
                if esig is None:
                    collisions.append(
                        f"path {path.name!r} L{elem.layer} intrudes on "
                        f"{kind} {name!r} (unrouted) near ({wx:.2f}, {wy:.2f})"
                    )
                else:
                    collisions.append(
                        f"path {path.name!r} L{elem.layer} collides with "
                        f"{kind} {name!r} signal {esig!r} near ({wx:.2f}, {wy:.2f})"
                    )

    assert not collisions, "\n".join(collisions)


# Angle-alignment invariant: every routed segment must run at a
# multiple of 45° (i.e. axis-aligned or exact-45° diagonal). The
# chamfer suggester in voxel_suggester.apply_chamfers preserves
# this by construction — if any future change introduces a segment
# at e.g. 30° or atan2(b, a) for unequal legs, the printed channel
# would no longer match the orthogonal-and-45° design intent.

_ALLOWED_ANGLE_DEGREES = (0.0, 45.0, 90.0, 135.0, 180.0, -45.0, -90.0, -135.0, -180.0)
_ANGLE_TOLERANCE_DEG = 0.05


def test_every_segment_is_45_or_90(substrate):
    """All routed wire segments must align to a 45° multiple."""
    bad: list[str] = []
    for path in substrate._get_signal_paths():
        for elem in path.elements:
            if not isinstance(elem, WireSegment):
                continue
            dx = elem.end.x - elem.start.x
            dy = elem.end.y - elem.start.y
            if math.hypot(dx, dy) < 1e-6:
                continue
            angle = math.degrees(math.atan2(dy, dx))
            if not any(abs(angle - a) < _ANGLE_TOLERANCE_DEG
                       for a in _ALLOWED_ANGLE_DEGREES):
                bad.append(
                    f"path {path.name!r} L{elem.layer}: "
                    f"({elem.start.x:.3f}, {elem.start.y:.3f}) → "
                    f"({elem.end.x:.3f}, {elem.end.y:.3f}) "
                    f"runs at {angle:.3f}° (not a multiple of 45°)"
                )
    assert not bad, (
        "Every WireSegment must run at 0°/±45°/±90°/±135°/±180° — "
        "no arbitrary slopes:\n" + "\n".join(bad)
    )


# Connectivity invariant: every pin claimed by a routed net (master
# pin + every device pin) must be reached by that signal's routed
# path. A pin xy must appear as an endpoint of at least one
# WireSegment in the path matching the signal name. If a net's path
# doesn't reach all its pins, the substrate has a dead-end / missing
# wire — the bus isn't physically complete.

_PIN_MATCH_TOLERANCE_MM = 0.05


def _path_endpoints(path) -> set[tuple[float, float]]:
    """All wire-segment endpoint xys for a path, rounded to a stable
    key for set membership."""
    out: set[tuple[float, float]] = set()
    for elem in path.elements:
        if not isinstance(elem, WireSegment):
            continue
        out.add((round(elem.start.x, 3), round(elem.start.y, 3)))
        out.add((round(elem.end.x, 3), round(elem.end.y, 3)))
    return out


def _pin_is_in_endpoints(pin_xy: Point2D, endpoints: set[tuple[float, float]]) -> bool:
    """True iff some endpoint is within `_PIN_MATCH_TOLERANCE_MM` of
    the pin's xy. Tolerance covers rounding drift from chamfer math."""
    for ex, ey in endpoints:
        if (
            abs(ex - pin_xy.x) < _PIN_MATCH_TOLERANCE_MM
            and abs(ey - pin_xy.y) < _PIN_MATCH_TOLERANCE_MM
        ):
            return True
    return False


def test_every_routed_pin_is_connected(substrate):
    """For each routed net, the master pin AND every device pin must
    be reached by an endpoint of the signal's path."""
    paths_by_sig: dict[str, object] = {}
    for path in substrate._get_signal_paths():
        sig = path.name.split("_", 1)[0]
        paths_by_sig.setdefault(sig, []).append(path)

    unconnected: list[str] = []

    for sig_enum, net in substrate._routed_nets().items():
        sig = sig_enum.name.lower()
        sig_paths = paths_by_sig.get(sig, [])
        if not sig_paths:
            unconnected.append(
                f"signal {sig.upper()}: no routed path emitted for this net"
            )
            continue
        endpoints: set[tuple[float, float]] = set()
        for p in sig_paths:
            endpoints |= _path_endpoints(p)

        all_pins = [net.master_pin, *net.device_pins]
        for pin in all_pins:
            pos = _pin_position(pin)
            if not _pin_is_in_endpoints(pos, endpoints):
                unconnected.append(
                    f"signal {sig.upper()}: pin {pin.ref}.{pin.number} "
                    f"at ({pos.x:.2f}, {pos.y:.2f}) is NOT reached by the "
                    f"routed path — bus is incomplete"
                )

    assert not unconnected, (
        "Every routed pin (master + device) must be the endpoint of at "
        "least one WireSegment in its signal's path:\n"
        + "\n".join(unconnected)
    )
