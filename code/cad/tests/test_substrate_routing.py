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
)


# Voxel grid resolution. 0.1 mm gives 8 voxels across an 0.8 mm channel
# and 5 voxels across a 1.0 mm pin hole — fine enough that two channels
# laid side-by-side with 0 mm clearance both claim the same boundary
# voxel column and the test flags them.
_VOXEL_RES = 0.1

_BOARD_W = 80.0
_BOARD_H = 50.0
_THICKNESS = 3.0
_CHANNEL_WIDTH = 0.8
_CHANNEL_DEPTH = 0.8


@pytest.fixture(
    params=[Tier1Substrate, Tier2Substrate, Tier2SubstrateBundled],
    ids=lambda cls: cls.__name__,
)
def substrate(request):
    return request.param()


# --- voxel coordinates -------------------------------------------------------


def _to_vx(x: float) -> int:
    return int(math.floor((x + _BOARD_W / 2) / _VOXEL_RES))


def _to_vy(y: float) -> int:
    return int(math.floor((y + _BOARD_H / 2) / _VOXEL_RES))


def _to_vz(z: float) -> int:
    return int(math.floor((z + _THICKNESS / 2) / _VOXEL_RES))


def _vx_world(vx: int) -> float:
    return (vx + 0.5) * _VOXEL_RES - _BOARD_W / 2


def _vy_world(vy: int) -> float:
    return (vy + 0.5) * _VOXEL_RES - _BOARD_H / 2


# --- rasterizers -------------------------------------------------------------


def _voxels_in_segment(seg: WireSegment, buffer: float = 0.0):
    """Yield (vx, vy, vz) for every voxel inside the segment's
    channel-volume inflated by `buffer` mm perpendicular to the
    segment — full inflated width is `_CHANNEL_WIDTH + 2*buffer`,
    depth stays `_CHANNEL_DEPTH` on the appropriate layer face.

    z is NOT inflated: L1 (substrate bottom) and L2 (substrate top)
    are vertically separated by ~1.4 mm of substrate body — a wall
    much thicker than the printable floor, so even a buffered L1
    channel doesn't reach into the L2 z-band."""
    cw = _CHANNEL_WIDTH + 2.0 * buffer
    cd = _CHANNEL_DEPTH
    if seg.layer == 1:
        z_lo = -_THICKNESS / 2
        z_hi = z_lo + cd
    else:
        z_hi = _THICKNESS / 2
        z_lo = z_hi - cd

    dx = seg.end.x - seg.start.x
    dy = seg.end.y - seg.start.y
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux  # unit normal

    bx_lo = min(seg.start.x, seg.end.x) - cw
    bx_hi = max(seg.start.x, seg.end.x) + cw
    by_lo = min(seg.start.y, seg.end.y) - cw
    by_hi = max(seg.start.y, seg.end.y) + cw

    vxl, vxh = _to_vx(bx_lo), _to_vx(bx_hi)
    vyl, vyh = _to_vy(by_lo), _to_vy(by_hi)
    vzl, vzh = _to_vz(z_lo), _to_vz(z_hi)

    half_w = cw / 2
    along_pad = buffer + _VOXEL_RES / 2  # extend segment ends by buffer too
    for vx in range(vxl, vxh + 1):
        wx = _vx_world(vx)
        for vy in range(vyl, vyh + 1):
            wy = _vy_world(vy)
            ax = wx - seg.start.x
            ay = wy - seg.start.y
            along = ax * ux + ay * uy
            if along < -along_pad or along > L + along_pad:
                continue
            perp = abs(ax * nx + ay * ny)
            if perp > half_w:
                continue
            for vz in range(vzl, vzh + 1):
                yield (vx, vy, vz)


def _voxels_in_through_hole(cx: float, cy: float, diam: float, buffer: float = 0.0):
    """Yield voxels for a through-hole cylinder inflated by `buffer`
    mm: substrate-bottom to substrate-top, radius (diam/2 + buffer)
    around (cx, cy)."""
    r = diam / 2 + buffer
    r_sq = r * r
    vxl, vxh = _to_vx(cx - r), _to_vx(cx + r)
    vyl, vyh = _to_vy(cy - r), _to_vy(cy + r)
    vzl, vzh = _to_vz(-_THICKNESS / 2), _to_vz(_THICKNESS / 2 - 1e-9)
    for vx in range(vxl, vxh + 1):
        wx = _vx_world(vx)
        dx_sq = (wx - cx) ** 2
        if dx_sq > r_sq:
            continue
        for vy in range(vyl, vyh + 1):
            wy = _vy_world(vy)
            if dx_sq + (wy - cy) ** 2 > r_sq:
                continue
            for vz in range(vzl, vzh + 1):
                yield (vx, vy, vz)


def _voxels_in_pcb_footprint_l2(cx: float, cy: float, half_w: float, half_l: float):
    """Yield voxels at the L2 z-band inside a module PCB's xy
    footprint. The PCB sits in the pocket cavity at z = +0.7..+1.5,
    occupying the same band as L2 routing channels — any L2 wire
    voxel here would short into the PCB."""
    z_hi = _THICKNESS / 2
    z_lo = z_hi - _CHANNEL_DEPTH
    vxl, vxh = _to_vx(cx - half_w), _to_vx(cx + half_w)
    vyl, vyh = _to_vy(cy - half_l), _to_vy(cy + half_l)
    vzl, vzh = _to_vz(z_lo), _to_vz(z_hi - 1e-9)
    for vx in range(vxl, vxh + 1):
        for vy in range(vyl, vyh + 1):
            for vz in range(vzl, vzh + 1):
                yield (vx, vy, vz)


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
