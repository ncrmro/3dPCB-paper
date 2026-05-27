"""Inflate a routed `SignalPath` into the grid as a halo blocker for
subsequent nets. Pin approach cells are exempt so each pin remains
reachable by its owning net.
"""

from __future__ import annotations

import math

from router.grid import Grid
from vitamins.substrate import SignalPath, Via, WireSegment


def _block_path(g: Grid, path: SignalPath, dims) -> None:
    """Inflate a routed path's segments + vias into the grid as blockers
    for subsequent nets. Pin cells and their immediate approach corridors
    are never blocked — pins must remain reachable by their owning net.

    Halo = `channel_width + min_wall_thickness − g.res/2`. With this
    keep-out, cross-net wires sit at least `wall_floor` apart in open
    space. The dense-pin parallel-axis approach + diagonal buffer
    (set up in `_build_grid`) cover the pin-row no-mans-land where
    halos would otherwise be relaxed.

    Axis-aligned segments halo their bounding rectangle in one shot.
    Diagonal segments (introduced by `_collapse_quadrant_runs`) rasterise
    at half-grid spacing and halo a square around each sample — a swept
    rectangle that hugs the wire instead of its bounding box.
    """
    halo = dims.channel_width + dims.min_wall_thickness - g.res / 2
    via_halo = dims.via_diameter / 2 + dims.min_wall_thickness
    approach = getattr(g, "_pin_approach_cells", set())

    def _block_cell(layer: int, gy: int, gx: int) -> None:
        if not g.in_bounds(gx, gy):
            return
        if (layer, gy, gx) in approach:
            return
        g.blocked[layer][gy][gx] = True

    def _block_square_at(wx: float, wy: float, layer: int) -> None:
        gx_lo, gy_lo = g.to_grid(wx - halo, wy - halo)
        gx_hi, gy_hi = g.to_grid(wx + halo, wy + halo)
        for gy in range(max(gy_lo, 0), min(gy_hi + 1, g.ny)):
            for gx in range(max(gx_lo, 0), min(gx_hi + 1, g.nx)):
                _block_cell(layer, gy, gx)

    for elt in path.elements:
        if isinstance(elt, WireSegment):
            axis_aligned = elt.start.x == elt.end.x or elt.start.y == elt.end.y
            if axis_aligned:
                x_min = min(elt.start.x, elt.end.x) - halo
                x_max = max(elt.start.x, elt.end.x) + halo
                y_min = min(elt.start.y, elt.end.y) - halo
                y_max = max(elt.start.y, elt.end.y) + halo
                gx_lo, gy_lo = g.to_grid(x_min, y_min)
                gx_hi, gy_hi = g.to_grid(x_max, y_max)
                for gy in range(max(gy_lo, 0), min(gy_hi + 1, g.ny)):
                    for gx in range(max(gx_lo, 0), min(gx_hi + 1, g.nx)):
                        _block_cell(elt.layer - 1, gy, gx)
            else:
                # Diagonal: rasterise at half-grid spacing and halo each
                # sample. Adjacent square halos overlap, producing a
                # continuous swept rectangle aligned with the wire.
                # Bounding-box halo would over-block the entire enclosing
                # rectangle of the 45° run.
                length = math.hypot(
                    elt.end.x - elt.start.x, elt.end.y - elt.start.y,
                )
                steps = max(int(length / (g.res / 2)) + 1, 1)
                for i in range(steps + 1):
                    t = i / steps
                    wx = elt.start.x + t * (elt.end.x - elt.start.x)
                    wy = elt.start.y + t * (elt.end.y - elt.start.y)
                    _block_square_at(wx, wy, elt.layer - 1)
        elif isinstance(elt, Via):
            r2 = via_halo * via_halo
            gx_lo, gy_lo = g.to_grid(elt.position.x - via_halo, elt.position.y - via_halo)
            gx_hi, gy_hi = g.to_grid(elt.position.x + via_halo, elt.position.y + via_halo)
            for ly in (0, 1):
                for gy in range(max(gy_lo, 0), min(gy_hi + 1, g.ny)):
                    for gx in range(max(gx_lo, 0), min(gx_hi + 1, g.nx)):
                        wx, wy = g.to_world(gx, gy)
                        if (wx - elt.position.x) ** 2 + (wy - elt.position.y) ** 2 <= r2:
                            _block_cell(ly, gy, gx)
