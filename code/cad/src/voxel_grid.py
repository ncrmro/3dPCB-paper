"""Voxel rasterizers for substrate features at 0.1 mm resolution.

Shared between the routing-overlap test (`tests/test_substrate_routing.py`)
and the routing suggester (`voxel_suggester.py`). A feature here means
a substrate void — a channel, a through-hole, a via, or a pocket —
or a non-void marker like a module PCB footprint at the L2 z-band.

The grid is anchored at substrate centre (0, 0, 0). Voxel
coordinates (vx, vy, vz) are integers; `_to_vx/y/z` and `_vx/y_world`
convert between voxel indices and world mm.

Each rasterizer yields voxel indices. The CALLER decides what to do
with them (mark in an owner dict, count, check collisions).

Inflation:
    `_voxels_in_segment` and `_voxels_in_through_hole` accept a
    `buffer` kwarg that inflates the feature by that many mm in
    xy (z is not inflated — L1 and L2 z-bands are 1.4 mm apart, much
    more than the printable wall floor). Buffer is half the
    substrate's `min_wall_thickness` (i.e. 0.3 mm for the default
    0.6 mm floor) — see failure mode #7 in
    `.deepwork/jobs/printable_pcb/job.yml`.
"""

from __future__ import annotations

import math

from vitamins.substrate import WireSegment

# Grid resolution: 0.1 mm gives 8 voxels across an 0.8 mm channel
# and 5 voxels across a 1.0 mm pin hole — fine enough that two
# channels laid side-by-side with 0 mm clearance both claim the
# same boundary voxel column.
VOXEL_RES = 0.1

BOARD_W = 80.0
BOARD_H = 50.0
THICKNESS = 3.0
CHANNEL_WIDTH = 0.8
CHANNEL_DEPTH = 0.8


# --- voxel coordinates -------------------------------------------------------


def to_vx(x: float) -> int:
    return int(math.floor((x + BOARD_W / 2) / VOXEL_RES))


def to_vy(y: float) -> int:
    return int(math.floor((y + BOARD_H / 2) / VOXEL_RES))


def to_vz(z: float) -> int:
    return int(math.floor((z + THICKNESS / 2) / VOXEL_RES))


def vx_world(vx: int) -> float:
    return (vx + 0.5) * VOXEL_RES - BOARD_W / 2


def vy_world(vy: int) -> float:
    return (vy + 0.5) * VOXEL_RES - BOARD_H / 2


# --- rasterizers -------------------------------------------------------------


def voxels_in_segment(seg: WireSegment, buffer: float = 0.0):
    """Yield (vx, vy, vz) for every voxel inside the segment's
    channel-volume inflated by `buffer` mm perpendicular to the
    segment — full inflated width is `CHANNEL_WIDTH + 2*buffer`,
    depth stays `CHANNEL_DEPTH` on the appropriate layer face.

    z is NOT inflated: L1 (substrate bottom) and L2 (substrate top)
    are vertically separated by ~1.4 mm of substrate body, much
    more than the printable wall floor.
    """
    cw = CHANNEL_WIDTH + 2.0 * buffer
    cd = CHANNEL_DEPTH
    if seg.layer == 1:
        z_lo = -THICKNESS / 2
        z_hi = z_lo + cd
    else:
        z_hi = THICKNESS / 2
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

    vxl, vxh = to_vx(bx_lo), to_vx(bx_hi)
    vyl, vyh = to_vy(by_lo), to_vy(by_hi)
    vzl, vzh = to_vz(z_lo), to_vz(z_hi)

    half_w = cw / 2
    along_pad = buffer + VOXEL_RES / 2
    for vx in range(vxl, vxh + 1):
        wx = vx_world(vx)
        for vy in range(vyl, vyh + 1):
            wy = vy_world(vy)
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


def voxels_in_through_hole(cx: float, cy: float, diam: float, buffer: float = 0.0):
    """Yield voxels for a through-hole cylinder inflated by `buffer`
    mm: substrate-bottom to substrate-top, radius (diam/2 + buffer)
    around (cx, cy).
    """
    r = diam / 2 + buffer
    r_sq = r * r
    vxl, vxh = to_vx(cx - r), to_vx(cx + r)
    vyl, vyh = to_vy(cy - r), to_vy(cy + r)
    vzl, vzh = to_vz(-THICKNESS / 2), to_vz(THICKNESS / 2 - 1e-9)
    for vx in range(vxl, vxh + 1):
        wx = vx_world(vx)
        dx_sq = (wx - cx) ** 2
        if dx_sq > r_sq:
            continue
        for vy in range(vyl, vyh + 1):
            wy = vy_world(vy)
            if dx_sq + (wy - cy) ** 2 > r_sq:
                continue
            for vz in range(vzl, vzh + 1):
                yield (vx, vy, vz)


def voxels_in_pcb_footprint_l2(cx: float, cy: float, half_w: float, half_l: float):
    """Yield voxels at the L2 z-band inside a module PCB's xy
    footprint. The PCB sits in the pocket cavity at z = +0.7..+1.5,
    occupying the same band as L2 routing channels — any L2 wire
    voxel here would short into the PCB.

    See `docs/module_back_conductivity.md` for the conservative-vs-
    refined model discussion (currently conservative).
    """
    z_hi = THICKNESS / 2
    z_lo = z_hi - CHANNEL_DEPTH
    vxl, vxh = to_vx(cx - half_w), to_vx(cx + half_w)
    vyl, vyh = to_vy(cy - half_l), to_vy(cy + half_l)
    vzl, vzh = to_vz(z_lo), to_vz(z_hi - 1e-9)
    for vx in range(vxl, vxh + 1):
        for vy in range(vyl, vyh + 1):
            for vz in range(vzl, vzh + 1):
                yield (vx, vy, vz)
