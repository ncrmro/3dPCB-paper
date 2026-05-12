# Spike plan: KiCad-first substrate compiler

Date: 2026-05-11
Status: proposed

## Goal

A runnable spike that backs three claims in `paper.md`:

1. **§2.1** Multi-orientation layouts emit as easily as aligned ones.
2. **§4** A compiler turns a declarative module + net list into a routed substrate.
3. **§7** Layouts can be **scored** (wire length, thermal coupling, crossings) — making the optimizer's objective function explicit before optimization is real.

## Design philosophy: KiCad-first, substrate-as-embodiment

The electrical design lives in **KiCad** as a normal `.kicad_sch` + `.kicad_pcb` project. The 3D-printed substrate is one possible **physical embodiment** of that design; a fabricated PCB is another. Both consume the same netlist.

Practically:

- **Source of truth:** KiCad project (versioned, edited in the familiar tool).
- **3D placement:** a sidecar YAML keyed by reference designator (`U1`, `J1`, …) giving `position`, `orientation`, and `pinned: bool`.
- **Compiler input:** KiCad netlist + footprints + sidecar + vitamin registry.
- **Compiler output:** substrate `.scad` with channels routed between pad coords derived from KiCad footprint pads transformed through the sidecar's 3D placement.

This reframes §3 of the paper. The "stepping-stone to PCB" mode is not a separate export step — it's the **default state of every design**, because the design was authored in KiCad to begin with. The substrate and the fabricated PCB are sibling embodiments, not sequential phases.

### Inspiration vs dependency

We borrow two ideas from circuit-synth without depending on it:

- `component["PIN_NAME"]` pin access by name.
- KiCad symbols and footprints as the canonical pad source.

We do **not** adopt circuit-synth as a runtime dependency. The substrate compiler is small and the paper's positioning is cleaner if it owns its data model.

## Scope boundaries

- I2C only — four nets (SDA, SCL, 3V3, GND).
- Three modules: ESP32-C3 assembly + SCD41 + BH1750.
- Greedy router, not optimal. Manhattan paths, two routing "layers" (top face / bottom face).
- Output: `.scad` per layout via the existing `cad/bin/render` pipeline.
- No STL, no print this spike.
- Optimizer is a **grid search** over angular placements of unpinned parts. Simulated annealing deferred.

## Phasing

Each phase ends with a runnable artifact reviewable before the next phase starts. Stopping after any phase still leaves the project with something the paper can cite.

### Phase 0 — Author the demo KiCad project

One-time setup. Establishes the canonical electrical design the rest of the spike consumes.

- `kicad/spike/` — `.kicad_sch` + `.kicad_pcb` for ESP32-C3 + SCD41 + BH1750 with the four I2C nets wired.
- Use real symbols/footprints from KiCad's standard libraries where possible; commit any custom symbols for the breakouts.
- The PCB layout itself is throwaway (just needs to exist for ERC/DRC and netlist export); the substrate compiler ignores PCB placement.

### Phase 1 — KiCad ingest + vitamin registry

- `cad/src/kicad_ingest.py` — parses KiCad project (via `kiutils` or netlist export) into `Net` and `Component` records keyed by reference designator. Pin names come from KiCad pad names.
- `cad/src/vitamins/registry.py` — maps KiCad footprint identifier (e.g. `MyLib:SCD41_Breakout`) → AnchorSCAD vitamin class + per-pad local-frame coordinates. Twelve pad coords total (4 pads × 3 modules) — hand-authored for the spike; auto-extraction from `.kicad_mod` is a follow-up.
- `cad/src/layout.py` — `Placement` dataclass: `ref: str`, `position: Vec3`, `orientation: Rot3`, `pinned: bool`. A `Layout` is `{ref: Placement}` plus the KiCad-ingested netlist.
- `cad/tests/test_ingest.py` — smoke test: ingesting the Phase 0 project yields exactly 4 nets and 3 components; every net's pin list resolves to vitamin-local pad coords.

### Phase 2 — Placement sidecar + orientation gallery

The §2.1 demo on its own. If routing turns out to be hard, this phase already proves the orientation claim.

- Sidecar format: `kicad/spike/placements/{variant}.yaml` — per-ref-des `position` + `orientation_deg` + `pinned`.
- `cad/src/substrate.py` — bounding-box body generator. Polymer block + module inlays at the placements specified by the sidecar. No channels yet.
- `cad/bin/gallery` — renders 3–4 hand-authored sidecars against the Phase 0 KiCad project:
  1. All three modules coplanar, MCU centered (baseline).
  2. BH1750 rotated +Z (light sensor faces up through the lid).
  3. SCD41 on a side wall (environmental sensor faces outward).
  4. MCU rotated so USB-C points at −Y wall.
- Output: `cad/build/gallery/{variant}.scad`.

### Phase 3 — Greedy router

- `cad/src/router.py` — for each net (read from KiCad), greedy Manhattan path between pad world-coordinates (vitamin-local pad coords × placement transform). Two layers (top / bottom face), chosen by simple crossing avoidance. Bend radius and channel-to-channel clearance run as DRC checks that **log warnings, not hard-fail**.
- `cad/src/substrate.py` extended to subtract channel geometry from the body.
- Gallery re-rendered with routed channels visible.

Accepted failure mode: the greedy router will sometimes produce ugly routes. The paper claims a maze router exists; it does not claim this is it.

### Phase 4 — Score function

- `cad/src/score.py` — for a routed layout, compute:
  - total wire length (mm),
  - controller-to-each-sensor through-body distance (thermal proxy),
  - net crossings,
  - longest single-net length (I2C budget).
- `cad/bin/gallery` prints a score table beside each rendered variant.

Why this earns its keep: §2.2 (thermal partitioning) goes from rhetorical to numerical, and the same data feeds Phase 5's optimizer.

### Phase 5 — Pin / optimize loop

- `cad/src/optimizer.py` — given a sidecar with some refs `pinned: true`, grid-search angular orientation and a coarse position grid for unpinned refs; pick the placement minimizing a weighted score from Phase 4.
- `cad/bin/optimize` — CLI: takes a partial sidecar, emits the merged sidecar + `.scad`.
- Worked example: pin the MCU at `(0,0,0)` with USB toward −Y; let the optimizer place SCD41 and BH1750.

Stop condition: the optimizer needs to demonstrably move parts. Proving it finds the true optimum is not in scope.

## Out of scope for this plan

Called out so we don't drift:

- Auto-extracting vitamin pad coords from `.kicad_mod` footprints — follow-up; spike hand-authors 12 coords.
- Tolerance calibration coupon — separate plan, but must precede any physical print.
- SPI / 1-Wire generalization example — separate plan.
- Pressure-fit lid generation — deferred until a layout is print-worthy.
- circuit-synth adoption — evaluated and declined; revisit only if a Phase 6 use case appears.

## Risks and open questions

- **KiCad parsing surface.** `kiutils` (or equivalent) reads `.kicad_sch` / `.kicad_pcb` in pure Python. Need to confirm it handles the symbols/footprints we'll use in Phase 0 without manual fix-ups.
- **Footprint ↔ vitamin alignment.** KiCad footprints describe pads in 2D on the footprint origin; vitamins place pads in 3D in their local frame. The Phase 1 registry has to align these by hand for now. Mismatches surface in `test_ingest`.
- **AnchorSCAD subtraction performance.** Many long channels through a body may render slowly. Acceptable for the spike; a real compiler would use a different geometry kernel.
- **I2C bus topology.** Each I2C net is a tree across multiple modules, not point-to-point. The Phase 3 router must handle multi-stop nets.

## Commit sequence

One conventional-commit per phase, in order:

1. `feat(kicad): add demo project for I2C spike (ESP32-C3 + SCD41 + BH1750)`
2. `feat(cad): KiCad ingest and footprint → vitamin registry`
3. `feat(cad): placement sidecar and orientation gallery`
4. `feat(cad): greedy two-layer Manhattan router`
5. `feat(cad): wire-length, thermal-proxy, and crossing scoring`
6. `feat(cad): grid-search optimizer for unpinned modules`
