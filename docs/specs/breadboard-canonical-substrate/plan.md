# Breadboard-canonical substrate Implementation Plan

## Architecture Overview

### High-Level Design

The substrate compiler is a declarative-spec → solid-geometry pipeline:

```
Board YAML spec ──► Board (pydantic model) ──► resolve_dims() ──► ResolvedDims
                                                                      │
   build_board(board) ──► BoardSubstrate (AnchorSCAD CompositeShape) ◄┘
        │
        ├─ base plate + levels + header pedestals
        ├─ device pockets + pin holes + receptacle bores
        └─ route_board(board, dims) ──► A* router ──► SignalPaths
                                          (grid → astar → blocking →
                                           align → collapse) cut as
                                           channels + vias
        │
        ▼
   STL / 3MF ──► GLB (gallery) + clearance-invariant report (JSON)
```

This feature does not add a new pipeline; it **re-centers the existing one** on
a single dimension source and a breadboard grid, then upgrades the router's
geometry stage from voxel reconstruction to vectorized 45°.

### Component Responsibilities (existing, with this feature's changes)

- **`board/board.py`** — declarative model. Owns `DimOverrides` (the YAML knob
  surface). *Change:* collapse the clearance family to a `buffer` knob + a
  `pitch` knob; drop the dead `hole_pair_clearance`.
- **`board/build.py`** — `_DEFAULTS`, `ResolvedDims`, `resolve_dims()`, plate /
  pocket / hole / pedestal geometry. *Change:* make `ResolvedDims` the single
  source of every derived clearance and the unified bore; add derived
  properties so each gap is computed once.
- **`board/connectors.py`** — `Connector` catalog (receptacle bore, body,
  height). *Change:* bore derives from the unified hole size; add lead-in +
  grip-target geometry parameters.
- **`router/grid.py`** — static blockers (edge strip, pockets, pin corridors).
  *Change:* edge/pocket inflation derives from `buffer`; remove the duplicated
  pocket-inflation math.
- **`router/blocking.py`** — halo inflation of routed paths. *Change:* wire-halo
  and via-halo derive from one helper on `ResolvedDims`.
- **`router/align.py`** — pitch alignment + raw-halo rebuild. *Change:* consume
  the same halo helper (today it re-derives the formula independently); host the
  synchronized-chamfer slot (Phase 5).
- **`router/collapse.py`** — staircase → 45° geometry. *Change:* Phase 5
  vectorized 45° + synced chamfers.
- **`router/score.py`, `board/cli_report.py`, `cli_score.py`** — scoring +
  invariants. *Change:* read clearances from `ResolvedDims`; drop the shadow
  default literals.

### Integration Points

- **Upstream:** KiCad netlist + placement sidecars define the electrical design
  and component positions (unchanged by this feature; placements gain a snap).
- **Downstream:** the Astro gallery (`code/web/`) consumes generated GLBs;
  reports land in `code/web/src/reports/substrate_*.json`. The clearance report
  is the objective acceptance gate.
- **Dev loop:** process-compose watches `code/cad/src/*.py` + KiCad source and
  re-renders. Must be running so gallery artifacts don't drift.

### Data Flow

A board's `DimOverrides` merge over `_DEFAULTS` into one frozen `ResolvedDims`.
Every consumer (builder geometry, router blockers/halos, scorer, report) reads
its clearances *from that one object* via derived accessors — no consumer
recomputes a clearance from raw constants. See `data-model.md`.

## Technology Stack

Locked by the constitution; no new runtime dependencies are introduced.

### Geometry / modeling
**Chosen:** AnchorSCAD (`anchorscad-core`) + PythonOpenSCAD, manifold3d, trimesh.
**Rationale:** already the substrate's modeling stack; the lead-in/grip features
are ordinary CSG (chamfer + stepped bore) expressible in AnchorSCAD.

### Declarative model + validation
**Chosen:** Pydantic v2 (`DimOverrides`, `Board`, `Connector`).
**Alternatives considered:** a separate dataclass clearance module.
**Rationale:** the knob surface is already Pydantic; adding `buffer`/`pitch` and
removing dead knobs keeps validation and YAML parsing in one place.
**Constitution alignment:** "one knob, derived everywhere" — the validated model
is the single source.

### Routing geometry (Phase 5)
**Chosen:** vectorized 45° representation anchored on the breadboard grid,
replacing staircase reconstruction from 0.5 mm cells.
**Alternatives considered:** keep the voxel A* and only post-smooth (status quo);
finer voxel grid (more cells, same staircase class of bug).
**Rationale:** breadboard anchoring makes diagonal runs land on exact 45° vectors,
so corners and synchronized bus chamfers fall out as vector ops instead of
cell-list surgery. **Risk:** largest change — sequenced last, behind the locked
docs/spec.

## Implementation Strategy

The phases mirror the constitution's locked sequencing. Each phase ends
test-green with no new report violations.

### Phase 0 — Discovery doc + dimension schema (no behavior change)
Author `docs/breadboard-model.md` (the discovery doc), extend
`docs/vernacular.md` (buffer, pitch, receptacle, lead-in, grip, via, chamfer),
and document the consolidated dimension schema (this plan + `data-model.md`).
Point `code/cad/README.md` at the model. **Already partly satisfied by these
spec artifacts.**

### Phase 1 — Consolidation commit (behavior-preserving)
- Introduce `buffer` defaulting to the **current** `min_wall_thickness` (0.6 mm)
  and `pitch` (2.54 mm) in `_DEFAULTS` / `DimOverrides` / `ResolvedDims`.
- Add derived accessors on `ResolvedDims`: `wall_halo_mm`, `via_halo_mm`,
  `edge_inflate_mm`, `wall_floor_mm`, `pocket_margin_mm` — each the single
  definition of a formula currently duplicated across modules.
- Repoint `blocking.py`, `align.py`, `grid.py`, `score.py`, `cli_report.py` at
  the accessors. Remove the duplicated halo formula (blocking.py ↔ align.py) and
  the duplicated pocket inflation (build.py ↔ grid.py).
- Delete the dead `hole_pair_clearance` knob (defined 3×, consumed 0×).
- Drop shadow default literals in `score.py` / `paths.py` (require dims).
- **Invariant:** numeric router/builder output identical; report unchanged.

### Phase 2 — Universal buffer enforcement (default 1.0 mm)
- Switch `buffer` default to 1.0 mm; fold `pocket_clearance` and `edge_clearance`
  into buffer-derived values (this is the intended behavior change).
- The vias-near-sensors fix (FR-5/US-4) falls out: via↔pocket-edge now respects
  `buffer`.

### Phase 3 — Unified 1.25 mm holes + receptacle lead-in + grip
- Set unified hole size = via size = 1.25 mm (single bore source).
- Add lead-in chamfer (FR-4) and a CAD grip/interference target (FR-12) to the
  receptacle bore in `connectors.py` / pedestal drilling in `build.py`.

### Phase 4 — Breadboard snapping
- Snap device placements (FR-6) and perimeter (FR-7) to `pitch` multiples,
  declaratively in the spec model. Re-route affected boards; verify gallery +
  reports.

### Phase 5 — Vectorized 45° edges + synchronized chamfers
- Represent runs/corners as breadboard-anchored vectors (FR-8).
- Apply synchronized chamfers to every adjacent bus pair (FR-9) after pitch
  alignment, in the slot after `align_cluster_pitch` in `_finalise_collapse`,
  before per-path collapse.

## Failure Behavior (FR-11)

Over-constrained boards must **fail with a clear conflict report**, never
auto-relax and never emit silently-invalid geometry. The router/builder surfaces
the specific feature pair or placement that could not satisfy `buffer` or
`pitch` snapping. This is verified by the clearance-invariant report and a
targeted test that an unroutable buffer raises rather than degrades.

## Testing Strategy

- **Behavior-preserving phases (1):** golden-output assertion — generated
  geometry/route for the reference boards is byte-for-byte (or
  tolerance-for-tolerance) identical before/after. Existing pytest suite green.
- **Behavior-changing phases (2–5):** assert the *new* invariant
  (via↔pocket ≥ buffer; placements on pitch; no staircase; synced chamfer
  alignment) via the report + targeted unit tests.
- **Printability:** receptacle coupon re-print remains the human gate for the
  grip target (documented, hardware-dependent).
- Gate at each phase: `bin/test` green, `process-compose process restart
  prebuild-cad` regenerates all GLBs with no exceptions, reports show no new
  violations.

## Deployment Considerations

No deployment surface — output is generated artifacts (STL/3MF/GLB) consumed by
the gallery and the printer. "Release" is regenerating the gallery via
process-compose and re-printing the reference board.
