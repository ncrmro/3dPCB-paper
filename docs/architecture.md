# Project Architecture

Living architecture record for 3dPCB-paper. Captures the substrate-compiler
pipeline and is updated as features land. See `AGENTS.md` / `code/AGENTS.md` for
workspace plumbing and the canonical module breakdown.

## System context

3dPCB-paper compiles a declarative description of an electronics assembly into a
single 3D-printable substrate that unifies PCB layout, harness routing, and
enclosure. The electrical design is authored in KiCad; the substrate is a
**physical embodiment** of that design (a sibling of a fabricated PCB, not a
successor).

```
KiCad design ─┐
(netlist +    │     ┌──────────────── code/cad (substrate compiler) ───────────────┐
 footprints)  ├───► │ Board spec (YAML) → Board model → ResolvedDims → builder +    │
placement     │     │ A* router → AnchorSCAD CompositeShape → STL/3MF → GLB         │
sidecars ─────┘     └───────────────────────────────────────────────────────────────┘
                                         │
                                         ├─► code/web (Astro + bun gallery)
                                         └─► clearance-invariant reports (JSON)
```

## Subsystems

- **`code/kicad/`** — canonical electrical design + per-refdes 3D placement
  sidecars. Own `flake.nix`.
- **`code/cad/`** — the substrate compiler (focus of this document). uv
  workspace member; own `flake.nix` / `pyproject.toml`. Python ≥ 3.13.
- **`code/web/`** — Astro + bun gallery rendering generated GLBs.

## Substrate compiler (`code/cad/src`)

### Declarative model — `board/`
- `board.py` — `Board`, `DeviceInstance`, `Level`, `Bus`, and `DimOverrides`
  (the YAML knob surface), all Pydantic v2.
- `connectors.py` — `Connector` catalog (off-the-shelf headers): bore, body,
  height.
- `devices.py`, `pins.py` — device footprints + pin geometry.

### Dimension resolution — `board/build.py`
- `_DEFAULTS` + `ResolvedDims` + `resolve_dims(board)` — merge per-board
  overrides over defaults into one frozen dimension object.
- `build_board(board)` → `BoardSubstrate` (AnchorSCAD `CompositeShape`): base
  plate, levels, header pedestals, device pockets, pin holes, receptacle bores;
  invokes the router and cuts channels + vias.

### Auto-router — `router/` (A*, split into focused modules)
- `grid.py` — fixed-resolution (0.5 mm) 2-layer grid + static blockers
  (edge strip, device pockets, per-pin approach corridors).
- `astar.py` — A* core.
- `blocking.py` — inflate routed paths into the grid as halos for later nets.
- `align.py` — multi-trunk pitch alignment + raw-halo rebuild.
- `collapse.py` — simplify wiggles, collapse staircases → 45°, chamfer pin
  corners, fold cells → waypoints.
- `autoroute.py` — orchestration (`route_board`, `_finalise_collapse`).
- `paths.py`, `score.py` — path assembly + comparative route scoring.

### Reporting / CLI — `board/cli_*.py`
- `cli_report.py` — clearance-invariant report (edge clearance, wall floor,
  cross-layer overlap) → JSON consumed by the gallery. **The objective
  acceptance gate.**
- `cli_score.py` — route comparison.

### Legacy — `voxel_*.py`
Voxel chamfer/collision helpers, superseded incrementally by vectorized 45°
geometry.

## Dimension model (current → target)

**Today:** clearances are a scattered family (`pocket_clearance`,
`edge_clearance`, `min_wall_thickness`, channel/via halos, pocket margin)
computed independently across `build.py`, `grid.py`, `blocking.py`, `score.py`,
`align.py`, `cli_report.py`. There is no single dial and one formula
(`channel_width + min_wall_thickness − res/2`) is duplicated.

**Target (breadboard-canonical-substrate feature):** a single `buffer` (min
material gap) and a `pitch` (2.54 mm breadboard unit) on `DimOverrides`; every
clearance derived once via accessors on `ResolvedDims`; a unified `hole_diameter`
bore for receptacles/pin-drills/vias; receptacle lead-in + grip geometry on
`Connector`. See `docs/specs/breadboard-canonical-substrate/` (spec, plan,
data-model, research) and the discovery doc `docs/breadboard-model.md`
(Phase 0).

### Components added/modified by this feature
- **Added:** `buffer`, `pitch` knobs; `ResolvedDims` derived accessors
  (`wall_halo_mm`, `via_halo_mm`, `edge_inflate_mm`, `wall_floor_mm`,
  `pocket_margin_mm`, `hole_bore_mm`); `Connector` lead-in + grip fields;
  breadboard snapping in the spec model; synchronized-chamfer slot in
  `_finalise_collapse`.
- **Modified:** all clearance consumers repoint at the accessors; bore sources
  unify; placement/perimeter resolve onto `pitch`.
- **Removed:** dead `hole_pair_clearance`; duplicated halo + pocket-inflation
  math; shadow default literals in `score.py` / `paths.py`.

## Cross-cutting conventions

- **Dev loop:** `nix develop -c process-compose up` — boot before editing
  CAD/KiCad source so gallery GLB/STL artifacts don't drift behind source.
- **Quality gates:** `code/cad/bin/test` (pytest), `bin/lint` (ruff strict +
  ty), clearance-invariant report shows no new violations, GLB regen with no
  exceptions.
- **Sequencing principle:** refactor (behavior-preserving) and behavior change
  never share a commit (see `docs/constitution.md`).
