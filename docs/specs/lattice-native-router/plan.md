# Lattice-native autorouter

## Context

Device pins are snapped to the 2.54 mm breadboard pitch
(`board.py:_snap_devices_to_pitch`) and, since the commensurate-grid change,
land exactly on routing-grid cells (`ResolvedDims.res = pitch / pitch_subdivisions
= 0.508 mm`). But the router still searches that fine grid and is free to place
runs, corners, and vias on any sub-cell, so trunk vias drift one sub-cell
(~508 µm) off the pitch columns their pins live on. An audit of
`i2c_midline_sensors` found only the *pins* on the breadboard grid: ~half the
runs, ~60 % of corners, and 5/8 vias are off-pitch, and the perimeter is off-pitch
entirely.

A post-hoc snap pass would patch this after the fact. Instead we route **natively
on the 2.54 mm lattice** so runs, corners, and vias land on-pitch by construction.

This continues `breadboard-native-routing-grid` (the commensurate-grid foundation)
and completes the `breadboard-canonical-substrate` initiative's unfinished Phase 4
(perimeter → pitch) and Phase 5 (vectorized 45°).

## Why the coarse lattice loses no routability

`wall_floor = channel_width + buffer = 0.8 + 1.0 = 1.8 mm` (min cross-net
centreline gap). Adjacent pitch columns are 2.54 mm apart, so they clear with
0.74 mm slack — automatically. Half-pitch lanes (1.27 mm) are *below* the wall
floor, so two parallel wires can never legally sit there. **2.54 mm is the finest
legal lane spacing**, so routing on the pitch lattice forfeits no routability; it
bakes the clearance in. The fine 0.508 mm grid is retained only as a clearance
oracle.

## Design

### Coarse lattice graph (`src/router/lattice.py`, new)
Node `(layer, ix, iy)` with `layer ∈ {0,1}` (emit `WireSegment.layer = layer+1`)
and integer pitch indices off a pitch-anchored origin. A pin at `k·pitch` maps to
an exact node. Moves: cardinal `(±1,0)/(0,±1)`, **diagonal `(±1,±1)`**, and a via
(layer flip) at a node. Cost reuses the spirit of the voxel weights
(`_W_STEP=1.0`, `_W_VIA=1.5`, `_W_BEND=0.05`, `_edge_penalty`), diagonal ≈
`√2·_W_STEP`; `prefer_layer → layer_step_mul` reused. A* (`_lattice_astar`) is
modelled on `astar._astar`, but a candidate *edge* is tested for clearance by the
oracle rather than against a precomputed blocked array.

### Clearance oracle
Keep the fine `Grid` as the backing store (`_build_grid` already snaps origin to
res and `block_rect`/`block_circle` are the sub-pitch rasterisers we need — an
adjacent column clears by only 0.74 mm, so a pitch-resolution oracle is too
coarse). Slim it to static blockers (edge strips, pockets, foreign-pin cells) plus
a per-cell `owner_id` array (`-1` = free/static, else net id). A candidate edge
collides iff a covered cell's owner is a *different* net or static.
- `run_clear(a,b,layer)` — cardinal reuses the axis-aligned halo bbox of
  `blocking._block_path` in read mode; diagonal reuses its half-res swept-rect
  branch.
- `via_clear(node)` — `block_circle` rasterisation in read mode, both layers.
- Commit a routed net's halo via `_block_path` branches, tagging `owner_id`. A
  net's own pins/trunk read as free (owner == self), so trunk sharing needs no
  explicit exemption.

### 45° and the wall floor
Two parallel diagonals one pitch apart are `2.54/√2 = 1.7961 mm` — 4 µm under the
1.8 mm wall floor; the material wall is 0.996 mm vs the 1.0 mm buffer, physically
identical and far inside FDM tolerance (~0.4 mm). `_inv_wall_floor`
(`cli_report.py`) and `test_wire_to_wire_wall_floor` get a small documented
tolerance (compare against `wall_floor_mm − 0.01`) so pitch-spaced diagonal
bundles pass. This is the only invariant on a knife-edge; cardinal parallels keep
0.74 mm slack.

### Preserved policy
- Net priority / 3-phase / pair bundling — `schedule.py` (`_ordered_bus_actions`,
  `_net_priority`), grid-agnostic, reused as-is.
- Multi-slave trunk sharing — multi-source A* from the committed trunk node set.
- Layer preference (`RoutingHint.prefer_layer`) and `must_pass` waypoints
  (snapped to nearest node) — reused.
- Dense-pin perpendicular approach — dropped in v1: the sub-pitch no-mans-land
  collision it prevented cannot occur when pins are nodes one pitch apart; only
  "foreign pin node is blocked" is retained.

### Integration
New `route_board(board, dims)` in `lattice.py` emitting via
`paths.waypoints_to_path` (which enforces 45/90 and via-shares-xy at construction,
so those gates pass by construction). Dispatch inside `autoroute.route_board` on a
new `DimOverrides.router_engine: Literal["voxel","lattice"]`, keeping all call
sites stable. Prerequisite: `_snap_perimeter_to_pitch` validator on `Board` grows
the base perimeter outward to the enclosing pitch-multiple rectangle (grow-only:
never clips routable area, never moves devices, grows away from parts). Once the
lattice is default and gates pass, the voxel A* and the ~10 fine-grid cleanup
passes are deleted.

## Phases (each behaviour-change is its own commit)

| Phase | Change | Commit type |
|---|---|---|
| P1 | `_snap_perimeter_to_pitch` (grow to pitch); voxel still default | `feat(board)` |
| P2 | `lattice.py` graph + oracle + 45° A* + `test_lattice_router.py` (unwired) | `feat(router)` |
| P3 | lattice orchestration (trunk sharing) + wall_floor tolerance; validate both specs via lattice engine | `feat(router)` |
| P4 | dispatcher + flip default to lattice; fix `must_pass`/`prefer_layer` tests | `feat(router)` |
| P5 | delete voxel A* + collapse/align/dense-pin passes (keep `_path_to_waypoints`) | `refactor(router)` |

## Verification (per phase)
- `code/cad/bin/test` (parametrised over `specs/*.yaml`) and `code/cad/bin/lint` green.
- `code/cad/bin/substrate-report` → `code/web/src/reports/substrate_*.json`: no new
  invariant violations vs the prior baseline; `drilled_holes_match_vias` confirms
  the via drift is gone.
- `process-compose process restart prebuild-cad` regenerates all GLBs cleanly.
- Gallery: OLED-column vias centred on their pin columns; bus bundles chamfer
  together. P5 additionally requires reports byte-identical to P4.
