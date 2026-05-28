"""Routing grid + static-blocker population.

`Grid` is a 2-layer, fixed-resolution discretisation of the board's base
perimeter. `_build_grid` populates it with the immutable blockers a route
must respect: edge-clearance strips, device pockets, and per-pin
"approach corridors" that keep each pin reachable by its owning net even
after surrounding cells get crowded.

Dynamic attributes (`_pin_approach_cells`, `_pin_approach_by_pin`,
`_pin_buffer_by_pin`) are stashed on the Grid by `_build_grid` and read
by the A* core + the post-route blocker. Lifting them into proper
dataclass fields is a follow-up.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from board.board import Board
from board.devices import Rect

GRID_RES_MM = 0.5

# Per-pin "approach corridor" depth in grid cells. The owning net is
# always allowed to step on these cells (so a pin remains reachable
# even after neighbouring halos crowd in); other nets are excluded.
# Pin pitch on STEMMA QT sensors is 2.54 mm = 5 grid cells at 0.5 mm
# resolution, so a 3-cell corridor leaves 2 cells of slack between
# adjacent pins' corridors — enough for the wall floor not to collapse
# at the pin row.
APPROACH_DEPTH = 3

# Parallel-axis reserve at a dense-cluster pin: how many cells along the
# row direction get added to the owning net's approach (so cross-nets
# can't sit that close). ±1 keeps cross-net wires at 1.0 mm — below the
# 1.4 mm wall_floor. ±2 keeps them at ≥ 1.5 mm, satisfying wall_floor
# while still permitting routability at the 5-cell pin pitch (own
# parallel reserves of adjacent pins fill the gap exactly with no
# overlap; cross-net wires must leave the row before crossing the pin
# pitch midpoint).
DENSE_PIN_PARALLEL_RESERVE = 2


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
    def from_board(cls, board: Board) -> Grid:
        perim = board.levels[0].perimeter
        g = cls(
            x_min=perim.x_min, y_min=perim.y_min,
            width=perim.w, height=perim.h,
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

    Returns (grid, pin_cells) where pin_cells is the set of cells that
    represent device pin holes — A* may *enter* these cells but they
    don't act as obstacles for the net that targets them. Other nets
    treat them as blocked.
    """
    g = Grid.from_board(board)

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

    # Pin-hole cells — they're "soft" blockers (route endpoints land on
    # them) so we don't pre-block them here, but we record them so the
    # router knows which cells are valid termini. We also reserve a
    # one-cell halo around each pin as a "pin approach corridor" — the
    # path-blocking logic below skips these cells so a pin always
    # remains reachable from at least one cardinal direction even after
    # adjacent nets have routed through nearby cells. The approach also
    # protects pin reachability from pocket blocking below.
    # Pin cells + per-pin 1-cell approach corridors.
    #
    # Approach corridor depth tradeoff: deeper corridors keep pins
    # reachable when prior nets' halos crowd in, but if two adjacent
    # pins' corridors OVERLAP, two cross-net wires can route through
    # the overlap and the wall floor between them collapses to 0.5 mm.
    #
    # SCD41/BH1750 pin pitch is 2.54 mm = 5 grid cells at 0.5 mm
    # resolution. A 1-cell cardinal corridor (pin ±1 in x and y) means
    # adjacent pins' corridors sit 2 cells apart — no overlap, no
    # wall-floor collapse, and each pin keeps at least one free
    # approach cell on each layer for A* to step from.
    dense_axes = _dense_cluster_pin_axes(board)
    bus_endpoint_xys: set[tuple[float, float]] = set()
    for net in board.nets():
        for ep in net.endpoints:
            bus_endpoint_xys.add(
                (round(ep.position.x, 3), round(ep.position.y, 3))
            )

    # Pre-compute the L2-pocket forbidden footprint for each
    # flat-mounted device. A flat-mounted device (no header) has its
    # pocket carved into the top face of the substrate, removing L2
    # there. We forbid L2 routing inside the carved pocket *plus*
    # `channel_width/2` of margin so the wire EDGE (centreline +
    # channel_width/2) doesn't cross into the pocket. (Adding a full
    # min_wall_thickness wall on top would be ideal but breaks
    # routability on tight boards — defer to a board-spec knob if a
    # specific design needs more wall.)
    #
    # Pin approach corridors must NOT extend into this forbidden
    # region on L2 — a wire there would either float in air (in the
    # pocket) or partially overhang it (in the margin). On L1 the
    # substrate is intact, so the wire approaches from underneath via
    # a via.
    pocket_margin = dims.pocket_margin_mm
    pocket_by_device: dict[str, Rect] = {}
    for inst in board.devices:
        if inst.header is not None:
            continue
        device = inst.resolved_device()
        fp = device.footprint
        if inst.rotation in (0, 180):
            w, h = fp.w, fp.h
        else:
            w, h = fp.h, fp.w
        pocket_by_device[inst.name] = Rect(
            cx=inst.position.x + fp.cx,
            cy=inst.position.y + fp.cy,
            w=w + 2 * pocket_margin,
            h=h + 2 * pocket_margin,
        )

    pin_cells: set[tuple[int, int, int]] = set()
    pin_approach_by_pin: dict[
        tuple[float, float], set[tuple[int, int, int]]
    ] = {}
    pin_buffer_by_pin: dict[
        tuple[float, float], set[tuple[int, int, int]]
    ] = {}
    for inst in board.devices:
        device = inst.resolved_device()
        own_pocket = pocket_by_device.get(inst.name)
        for pin in device.pins:
            abs_pos = device.pin_position_at(inst.position, inst.rotation, pin)
            gx, gy = g.to_grid(abs_pos.x, abs_pos.y)
            if not g.in_bounds(gx, gy):
                continue
            key = (round(abs_pos.x, 3), round(abs_pos.y, 3))
            for ly in (0, 1):
                pin_cells.add((ly, gy, gx))
            if key not in bus_endpoint_xys:
                continue   # unrouted pin — drilled hole only, no corridor

            dense_axis = dense_axes.get(key)
            if dense_axis is not None:
                perp_dx, perp_dy = dense_axis
                axes = ((perp_dx, perp_dy), (-perp_dx, -perp_dy))
            else:
                axes = ((-1, 0), (1, 0), (0, -1), (0, 1))
            approach: set[tuple[int, int, int]] = set()
            for ly in (0, 1):
                for ddx, ddy in axes:
                    for k in range(1, APPROACH_DEPTH + 1):
                        nx, ny = gx + ddx * k, gy + ddy * k
                        if not g.in_bounds(nx, ny):
                            continue
                        # L2 approach can't extend into our own pocket:
                        # the substrate is carved away there, so a wire
                        # on L2 would have nothing to sit on. Force the
                        # approach to come via L1 instead (which the
                        # via from L2 naturally provides at the pin).
                        if ly == 1 and own_pocket is not None:
                            wx, wy = g.to_world(nx, ny)
                            if (own_pocket.x_min <= wx <= own_pocket.x_max
                                    and own_pocket.y_min <= wy <= own_pocket.y_max):
                                continue
                        approach.add((ly, ny, nx))
            # For dense pins also reserve parallel-axis neighbours as
            # part of the owning net's approach — own net can traverse
            # them, but other nets' `extra_blocked` includes them so a
            # cross-net wire can't sit close along the row (where halo
            # doesn't reach because of the own_pin_cells exemption).
            # Depth `DENSE_PIN_PARALLEL_RESERVE` controls the
            # wall-floor distance along the row.
            if dense_axis is not None:
                par_dx, par_dy = perp_dy, perp_dx
                for ly in (0, 1):
                    for s in (-1, 1):
                        for k in range(1, DENSE_PIN_PARALLEL_RESERVE + 1):
                            nx, ny = gx + s * k * par_dx, gy + s * k * par_dy
                            if g.in_bounds(nx, ny):
                                approach.add((ly, ny, nx))
                # Diagonal "buffer" cells around the dense pin go into
                # `other_net_buffer_by_pin` (consumed via
                # `extra_blocked` in `_route_one_net`). Own net is not
                # given access — these are pure exclusion for cross-net
                # wires that would otherwise sit diagonally adjacent to
                # the pin.
                buffer: set[tuple[int, int, int]] = set()
                for ly in (0, 1):
                    for ddx in (-1, 0, 1):
                        for ddy in (-1, 0, 1):
                            if ddx == 0 and ddy == 0:
                                continue
                            nx, ny = gx + ddx, gy + ddy
                            if g.in_bounds(nx, ny):
                                buffer.add((ly, ny, nx))
                # Remove cells that are already in approach (own can
                # step there) — the buffer adds the diagonals only.
                buffer -= approach
                pin_buffer_by_pin.setdefault(key, set()).update(buffer)
            pin_approach_by_pin[key] = approach
    g._pin_approach_cells = {c for s in pin_approach_by_pin.values() for c in s}
    g._pin_approach_by_pin = pin_approach_by_pin
    g._pin_buffer_by_pin = pin_buffer_by_pin

    # Hard blockers — cells the post-route collapse must NEVER step on,
    # even when they sit inside the path's own exclusive halo. These
    # are physical impossibilities (no substrate, or board edge), not
    # neighbour-wire halos. Populated below as pockets + edge strips
    # get blocked.
    hard_blocked: set[tuple[int, int, int]] = set()
    for ly in (0, 1):
        for gy in range(g.ny):
            for gx in range(g.nx):
                if g.blocked[ly][gy][gx]:
                    hard_blocked.add((ly, gy, gx))

    # Device pockets — for flat-mounted devices, the pocket cuts away
    # the top face of the substrate, so L2 (top) channels can't pass
    # through the pocket xy. L1 stays clear (the substrate floor is
    # intact under flat-mounted devices). The pin cell itself remains
    # exempt as a routing target; the approach corridor was already
    # pruned of pocket-interior cells above, so a wire targeting the
    # pin on L2 must arrive via a via from L1.
    for name, pocket in pocket_by_device.items():
        del name  # iteration target only; the pocket Rect is what we use
        gx_lo, gy_lo = g.to_grid(pocket.x_min, pocket.y_min)
        gx_hi, gy_hi = g.to_grid(pocket.x_max, pocket.y_max)
        for gy in range(max(gy_lo, 0), min(gy_hi + 1, g.ny)):
            for gx in range(max(gx_lo, 0), min(gx_hi + 1, g.nx)):
                if (1, gy, gx) in pin_cells:
                    continue
                g.blocked[1][gy][gx] = True
                hard_blocked.add((1, gy, gx))

    g._hard_blocked = hard_blocked
    return g, pin_cells
