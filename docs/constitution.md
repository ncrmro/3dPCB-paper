# Project Constitution

## Overview

3dPCB-paper is a research paper plus spike CAD compiler for a parametric
3D-printed substrate that unifies PCB layout, harness routing, and enclosure
into one declarative artifact. The validation target is an ESP32-C3 Supermini
+ SCD41 (CO2/temp/humidity) + BH1750 (light) over I2C.

This constitution governs the **breadboard-canonical substrate** initiative:
consolidating the scattered clearance family into a single universal `buffer`,
unifying hole sizes to 1.25 mm with receptacle lead-ins, anchoring the whole
design on the 2.54 mm breadboard grid, and moving from staircased voxel
reconstruction toward vectorized 45° edges. It sets the principles that all
specs and implementations under this initiative must honor.

## Development Priorities

In priority order for this initiative:

1. **Declarative tweakability** — the print must be fast to iterate. One
   `buffer` knob and YAML per-board overrides replace scattered, hardcoded
   clearance constants. There is a single source of truth for each dimension.
2. **Printability (FDM)** — geometry must survive a 0.4 mm-nozzle FDM printer
   with default slicer settings. Clearances and bores are tied to measured
   tolerances, not theoretical minimums.
3. **Breadboard-canonical geometry** — 2.54 mm pitch is the canonical sizing
   and coordinate system; placements, perimeter, and bus spacing resolve to
   pitch multiples; runs and corners are represented as true vectors rather
   than reconstructed from voxels.

Behavior-preserving refactor discipline is a supporting practice (see
Governance) rather than a top-line priority.

## Technology Stack

### Languages
- Python: `>= 3.13`

### Frameworks / libraries
- AnchorSCAD (`anchorscad-core`) + PythonOpenSCAD: solid modeling → STL/3MF
- Pydantic v2: declarative board/dimension model with validation
- NumPy, NetworkX: routing + geometry math
- trimesh, manifold3d, lxml: 3MF → GLB conversion preserving per-face color
- PyYAML: declarative board specs
- bun + Astro: web gallery (`code/web/`)

### Source layout (authoritative: `AGENTS.md`, `code/AGENTS.md`)
- `code/cad/src/board/` — declarative model (`board.py`, `connectors.py`) +
  builder (`build.py`) + CLI entry points (`cli_report.py`, `cli_score.py`)
- `code/cad/src/router/` — A* auto-router split into focused modules
  (`grid.py`, `blocking.py`, `score.py`, `collapse.py`, `align.py`,
  `astar.py`, `autoroute.py`, `paths.py`)
- `code/cad/src/vitamins/` — COTS module models
- `code/cad/src/voxel_*.py` — legacy chamfer/collision helpers (being
  superseded by vectorized 45° geometry)

### Infrastructure
- Nix devshell per subproject (`flake.nix`); run via `nix develop -c <cmd>`
- uv workspace (shared venv at `code/.venv/`)
- process-compose is the default dev loop — boot it before editing CAD/KiCad
  source so gallery GLB/STL artifacts don't drift behind the source

## Quality Standards

### Code quality
- Ruff in strict mode (line length 100, target `py313`) and `ty` type-check;
  both run via `code/cad/bin/lint`.
- Single source of truth for each dimension. A clearance, bore, or halo is
  defined once and derived elsewhere — no parallel hardcoded copies that can
  drift (e.g. the halo formula must not be duplicated across modules).
- Comments explain **why**, not what; no references to the current PR/fix in
  source comments.

### Testing requirements
- `code/cad/bin/test` (pytest) MUST be green at every phase.
- `nix develop -c process-compose process restart prebuild-cad` MUST
  regenerate all substrate GLBs with no exceptions.
- Substrate reports (`code/web/src/reports/substrate_*.json`) MUST show no new
  clearance-invariant violations after a change.
- Behavior-preserving phases (consolidation/refactor) MUST keep numeric router
  output identical; a cleanup that changes geometry is not behavior-preserving
  and must be sequenced as its own behavior-changing phase.

### Printability standards (FDM, validation hardware)
- Minimum reliable CAD through-hole for a standard DuPont pin: **1.25 mm**
  (validated via receptacle coupon v2, 2026-05-19). Holes below ~0.8 mm vanish
  under default slicer settings.
- Default universal `buffer` (minimum solid material between any feature pair):
  **1.0 mm**, rationale tied to the measured ~0.4 mm worst-case over-extrusion.
- Receptacle bores get a lead-in chamfer so DuPont pins self-guide and seat.
- FDM tolerance numbers are **printer- and slicer-dependent**: any new hardware
  re-runs the coupon. Defaults encode the validation hardware's numbers, not
  universal truths (`docs/fdm_tolerance_notes.md` is the record).

## Governance

### Sequencing (locked by the breadboard plan)
- **Docs + specs first.** Write the discovery doc and the declarative
  dimension schema before changing any router/builder behavior. Simplification
  and behavior changes follow the written record.
- Phased delivery: simplification (behavior-preserving) → universal buffer
  enforcement → unified holes + lead-in → breadboard snapping → vectorized 45°
  edges + synced bus chamfers. Each phase is independently test-green.

### Branching & commits
- Conventional Commits: `type(scope): subject`
  (`feat`/`fix`/`refactor`/`chore`/`docs`/`test`/`ci`/`perf`/`build`).
- One logical change per commit. Main branch is the integration branch;
  implementation happens on branches/worktrees.

### Review requirements
- Lint (`bin/lint`) and tests (`bin/test`) must pass before merge.
- The clearance-invariant report is the objective gate for routing changes:
  no new violations is a hard requirement, reviewed alongside the visual gallery
  diff.

### Specification maintenance
- Specs and governance live under `docs/` (constitution at `docs/constitution.md`;
  feature specs under `docs/specs/[feature]/`).
- Board specs remain declarative YAML at `code/cad/specs/*.yaml`; dimension
  knobs are overridable per-board via `Board.dim`.
- When a dimension's derivation or default changes, the spec and
  `docs/fdm_tolerance_notes.md` are updated in the same change.

## Principles

1. **One knob, derived everywhere.** Every feature-pair clearance derives from
   a single `buffer`; every hole from a single bore. Adding a dimension should
   touch one definition, not three.
2. **The breadboard is the ruler.** 2.54 mm pitch is the canonical unit.
   Placements and perimeter snap to it so geometry "clicks together" and 45°
   runs become expressible as true vectors.
3. **Print-validated, not theory-validated.** Defaults encode measured FDM
   behavior on real hardware. A number without a coupon or a measurement is a
   guess, and is flagged as such.
4. **Refactor and behavior change are never the same commit.** A
   consolidation that preserves output ships separately from a phase that
   intentionally changes geometry, so regressions are attributable.
5. **The written model leads the code.** The discovery doc and dimension schema
   are authored before the router churns, and stay the canonical reference.
