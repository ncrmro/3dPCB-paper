"""Routing grid + static-blocker population.

`Grid` is a 2-layer, fixed-resolution discretisation of the board's base
perimeter. `_build_grid` populates `g.blocked` with the immutable blockers
a route must respect — the edge-clearance strip and each flat-mounted
device's L2 pocket footprint — and returns the device pin-hole cells the
lattice oracle (`router.lattice`) uses for foreign-pin clearance.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from board.board import Board
from board.devices import Rect

# Fallback grid resolution. The real resolution is derived per board from
# the pitch (`ResolvedDims.res = pitch / pitch_subdivisions`) and threaded
# into `Grid.from_board`, so the lattice is commensurate with the
# breadboard grid. This constant is only the default for direct `Grid`
# construction (tests / synthetic grids).
GRID_RES_MM = 0.5


@dataclass
class Grid:
    """Routing grid covering the base level's bounding box, two layers deep."""

    x_min: float
    y_min: float
    width: float     # board extent along x
    height: float    # board extent along y
    res: float = GRID_RES_MM
    # blocked[layer][gy][gx] = True if that cell can't be entered. Layer
    # is 0-indexed internally (0 → physical L1, 1 → physical L2).
    blocked: list[list[list[bool]]] = field(default_factory=list)

    @classmethod
    def from_board(cls, board: Board, res: float = GRID_RES_MM) -> Grid:
        perim = board.levels[0].perimeter
        # Snap the grid origin and far edge onto the global `res` lattice.
        # Device pins are placed on pitch multiples and the pitch is an
        # integer number of `res` cells, so a lattice-aligned origin makes
        # every pin land exactly on a cell — vias and corners stop rounding
        # off the pin column. Snap inward (ceil the min, floor the max) so
        # the grid stays a subset of the board; the < res strip trimmed at
        # each edge already sits inside the edge-clearance keep-out, so no
        # routable area is lost.
        x_min = math.ceil(perim.x_min / res) * res
        y_min = math.ceil(perim.y_min / res) * res
        x_max = math.floor(perim.x_max / res) * res
        y_max = math.floor(perim.y_max / res) * res
        g = cls(
            x_min=x_min, y_min=y_min,
            width=x_max - x_min, height=y_max - y_min,
            res=res,
        )
        nx = int(round(g.width / g.res)) + 1
        ny = int(round(g.height / g.res)) + 1
        g.blocked = [
            [[False] * nx for _ in range(ny)]
            for _ in range(2)
        ]
        return g

    @property
    def nx(self) -> int:
        return len(self.blocked[0][0])

    @property
    def ny(self) -> int:
        return len(self.blocked[0])

    def to_grid(self, x: float, y: float) -> tuple[int, int]:
        gx = int(round((x - self.x_min) / self.res))
        gy = int(round((y - self.y_min) / self.res))
        return gx, gy

    def to_world(self, gx: int, gy: int) -> tuple[float, float]:
        return self.x_min + gx * self.res, self.y_min + gy * self.res

    def in_bounds(self, gx: int, gy: int) -> bool:
        return 0 <= gx < self.nx and 0 <= gy < self.ny

    def block_rect(
        self, rect: Rect, *, inflate: float, layers: Iterable[int]
    ) -> None:
        """Mark every cell inside (rect + inflate) as blocked on the
        listed layers (0/1 = physical L1/L2).
        """
        x_min = rect.x_min - inflate
        x_max = rect.x_max + inflate
        y_min = rect.y_min - inflate
        y_max = rect.y_max + inflate
        gx_lo, gy_lo = self.to_grid(x_min, y_min)
        gx_hi, gy_hi = self.to_grid(x_max, y_max)
        for ly in layers:
            for gy in range(max(gy_lo, 0), min(gy_hi + 1, self.ny)):
                for gx in range(max(gx_lo, 0), min(gx_hi + 1, self.nx)):
                    self.blocked[ly][gy][gx] = True

    def block_circle(
        self, cx: float, cy: float, radius: float, layers: Iterable[int]
    ) -> None:
        """Mark every cell whose centre falls within `radius` of (cx, cy)
        on the listed layers.
        """
        gx_lo, gy_lo = self.to_grid(cx - radius, cy - radius)
        gx_hi, gy_hi = self.to_grid(cx + radius, cy + radius)
        r2 = radius * radius
        for ly in layers:
            for gy in range(max(gy_lo, 0), min(gy_hi + 1, self.ny)):
                for gx in range(max(gx_lo, 0), min(gx_hi + 1, self.nx)):
                    wx, wy = self.to_world(gx, gy)
                    if (wx - cx) ** 2 + (wy - cy) ** 2 <= r2:
                        self.blocked[ly][gy][gx] = True


def _dense_cluster_pin_axes(board: Board) -> dict[tuple[float, float], tuple[int, int]]:
    """Map each dense-cluster pin's `(x, y)` to the perpendicular axis
    `(perp_dx, perp_dy)` along which approach is allowed.

    A "dense cluster" is a single contiguous pin row (≥ 3 endpoints
    within one pin pitch of a common axis). For each such pin, A*
    should approach only along the row's perpendicular axis — entering
    from ±x for a vertical row, ±y for a horizontal row. Forbidding
    parallel-axis approach prevents adjacent pins' wires from sharing
    the no-mans-land just outside the pin row (where halos are by
    design relaxed), which was the root cause of the 0.5 mm cross-net
    collisions in Phases 1–2.
    """
    _ROW_TOLERANCE_MM = 2.54
    endpoints_per_inst: dict[str, list[tuple[str, object]]] = {}
    for net in board.nets():
        for ep in net.endpoints:
            endpoints_per_inst.setdefault(ep.instance_name, []).append(
                (net.signal, ep.position)
            )

    out: dict[tuple[float, float], tuple[int, int]] = {}
    for inst_name, ep_list in endpoints_per_inst.items():
        if len(ep_list) < 3:
            continue
        ys = [p.y for _, p in ep_list]
        xs = [p.x for _, p in ep_list]
        x_spread = max(xs) - min(xs)
        y_spread = max(ys) - min(ys)
        if x_spread >= y_spread:
            minor_spread = y_spread
            perp_dx, perp_dy = 0, 1   # row horizontal → perp = y
        else:
            minor_spread = x_spread
            perp_dx, perp_dy = 1, 0   # row vertical → perp = x
        if minor_spread > _ROW_TOLERANCE_MM:
            continue
        for _, pos in ep_list:
            out[(round(pos.x, 3), round(pos.y, 3))] = (perp_dx, perp_dy)
    return out


def _build_grid(board: Board, dims) -> tuple[Grid, set[tuple[int, int, int]]]:
    """Prepare the routing grid with all static blockers in place.

    Returns (grid, pin_cells). `g.blocked` carries the immutable static
    blockers — the edge-clearance strip, each flat-mounted device's L2
    pocket footprint, and each header-mounted device's L2 connector-body
    footprint. `pin_cells` is every device pin hole: the lattice oracle lets
    a net terminate on its own pin but treats every pin as an obstacle to
    other nets.
    """
    g = Grid.from_board(board, res=dims.res)

    # Edge clearance: forbid a strip along the board outline so channels
    # don't run flush against the edge.
    perim = board.levels[0].perimeter
    ec = dims.edge_clearance
    g.block_rect(
        Rect(cx=perim.cx, cy=perim.y_min + ec / 2, w=perim.w, h=ec),
        inflate=0, layers=(0, 1),
    )
    g.block_rect(
        Rect(cx=perim.cx, cy=perim.y_max - ec / 2, w=perim.w, h=ec),
        inflate=0, layers=(0, 1),
    )
    g.block_rect(
        Rect(cx=perim.x_min + ec / 2, cy=perim.cy, w=ec, h=perim.h),
        inflate=0, layers=(0, 1),
    )
    g.block_rect(
        Rect(cx=perim.x_max - ec / 2, cy=perim.cy, w=ec, h=perim.h),
        inflate=0, layers=(0, 1),
    )

    # Pin-hole cells on both layers. These stay routable (a net ends on its
    # own pin) but the lattice oracle blocks every other net from them.
    pin_cells: set[tuple[int, int, int]] = set()
    for inst in board.devices:
        device = inst.resolved_device()
        for pin in device.pins:
            abs_pos = device.pin_position_at(inst.position, inst.rotation, pin)
            gx, gy = g.to_grid(abs_pos.x, abs_pos.y)
            if not g.in_bounds(gx, gy):
                continue
            pin_cells.add((0, gy, gx))
            pin_cells.add((1, gy, gx))

    # Top-face (L2) keep-outs. A flat-mounted device's pocket cuts away the
    # top face; a header-mounted device's plastic body sits on the top face
    # as a pedestal. Either way an L2 channel can't run under that footprint
    # (it would be buried under the part). L1 stays clear (the substrate
    # floor is intact), so a header pin is reached on the bottom face and
    # connected up through its own through-hole. The pin cell itself stays
    # routable as a via / through-hole target.
    pocket_margin = dims.pocket_margin_mm
    for inst in board.devices:
        if inst.header is not None:
            conn = inst.header.resolved_connector()
            fp_w, fp_h = conn.body_width, conn.body_depth
            cx, cy = inst.position.x, inst.position.y
        else:
            fp = inst.resolved_device().footprint
            fp_w, fp_h = fp.w, fp.h
            cx, cy = inst.position.x + fp.cx, inst.position.y + fp.cy
        if inst.rotation not in (0, 180):
            fp_w, fp_h = fp_h, fp_w
        keepout = Rect(
            cx=cx, cy=cy,
            w=fp_w + 2 * pocket_margin,
            h=fp_h + 2 * pocket_margin,
        )
        gx_lo, gy_lo = g.to_grid(keepout.x_min, keepout.y_min)
        gx_hi, gy_hi = g.to_grid(keepout.x_max, keepout.y_max)
        for gy in range(max(gy_lo, 0), min(gy_hi + 1, g.ny)):
            for gx in range(max(gx_lo, 0), min(gx_hi + 1, g.nx)):
                if (1, gy, gx) in pin_cells:
                    continue
                g.blocked[1][gy][gx] = True

    return g, pin_cells
