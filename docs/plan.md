# Spike plan: orientation gallery + pinned/unpinned router

Date: 2026-05-11
Status: proposed

## Goal

A runnable spike that backs three claims in `paper.md`:

1. **§2.1** Multi-orientation layouts emit as easily as aligned ones.
2. **§4** A compiler turns a declarative module + net list into a routed substrate.
3. **§7** Layouts can be **scored** (wire length, thermal coupling, crossings) — making the optimizer's objective function explicit before optimization is real.

## Scope boundaries

- I2C only — four nets (SDA, SCL, 3V3, GND).
- Three modules: ESP32-C3 assembly + SCD41 + BH1750.
- Greedy router, not optimal. Manhattan paths, two routing "layers" (top face / bottom face).
- Output: `.scad` per layout via the existing `cad/bin/render` pipeline.
- No STL, no print, no KiCad export this spike.
- Optimizer is a **grid search** over angular placements of unpinned parts. Simulated annealing deferred.

## Phasing

Each phase ends with a runnable artifact reviewable before the next phase starts. Stopping after any phase still leaves the project with something the paper can cite.

### Phase 1 — Placement spec + pin map

Foundation. Every later phase consumes these types.

- `cad/src/layout.py` — `Module`, `Net`, `Layout` dataclasses. Module carries `name`, `vitamin`, `position: Vec3`, `orientation: Rot3`, `pinned: bool`.
- `cad/src/pinmap.py` — pad positions per vitamin in the vitamin's local frame (SDA pad of SCD41, etc.). Sourced from existing `cad/src/vitamins/sensors.py` and `cad/src/vitamins/esp32.py` measurements.
- `cad/tests/test_pinmap.py` — smoke test: every module exposes all four I2C pads; pad positions land on the PCB footprint.

### Phase 2 — Orientation gallery, no routing

The §2.1 demo on its own. If routing turns out to be hard, this phase already proves the orientation claim.

- `cad/src/substrate.py` — bounding-box body generator. Polymer block + module inlays. No channels yet.
- `cad/bin/gallery` — renders 3–4 hand-authored layouts:
  1. All three modules coplanar, MCU centered (baseline).
  2. BH1750 rotated +Z (light sensor faces up through the lid).
  3. SCD41 on a side wall (environmental sensor faces outward).
  4. MCU rotated so USB-C points at −Y wall.
- Output: `cad/build/gallery/{layout_name}.scad`.

### Phase 3 — Greedy router

- `cad/src/router.py` — for each net, greedy Manhattan path between pads through the substrate volume. Two layers (top / bottom face), chosen by simple crossing avoidance. Bend radius and channel-to-channel clearance run as DRC checks that **log warnings, not hard-fail**.
- `cad/src/substrate.py` extended to subtract channel geometry from the body.
- Gallery re-rendered with routed channels visible.

Accepted failure mode: the greedy router will sometimes produce ugly routes. The paper claims a maze router exists; it does not claim this is it.

### Phase 4 — Score function

- `cad/src/score.py` — for a routed layout, compute:
  - total wire length (mm),
  - controller-to-each-sensor through-body distance (thermal proxy),
  - net crossings,
  - longest single-net length (I2C budget).
- `cad/bin/gallery` prints a score table beside each rendered layout.

Why this earns its keep: §2.2 (thermal partitioning) goes from rhetorical to numerical, and the same data feeds Phase 5's optimizer.

### Phase 5 — Pin / optimize loop

- `cad/src/optimizer.py` — given a `Layout` with some modules `pinned=True`, grid-search angular orientation and a coarse position grid for unpinned modules; pick the placement minimizing a weighted score from Phase 4.
- `cad/bin/optimize` — CLI: takes a partial layout file, emits merged layout + `.scad`.
- Worked example: pin the MCU at `(0,0,0)` with USB toward −Y; let the optimizer place SCD41 and BH1750.

Stop condition: the optimizer needs to demonstrably move parts. Proving it finds the true optimum is not in scope.

## Out of scope for this plan

Called out so we don't drift:

- KiCad netlist export (§3 stepping-stone mode) — separate plan.
- Tolerance calibration coupon — separate plan, but must precede any physical print.
- SPI / 1-Wire generalization example — separate plan.
- Pressure-fit lid generation — deferred until a layout is print-worthy.

## Risks and open questions

- **Pin-map accuracy.** Vitamins were copied from `ncrmro/plant-caravan#28` with measured dimensions; pad `(x, y)` positions may not be annotated. Phase 1's smoke test surfaces this — if pads are missing, add them in the same change.
- **AnchorSCAD subtraction performance.** Many long channels through a body may render slowly. Acceptable for the spike; a real compiler would use a different geometry kernel.
- **I2C bus topology.** Each I2C net is a tree across multiple modules, not point-to-point. The Phase 3 router must handle multi-stop nets.

## Commit sequence

One conventional-commit per phase, in order:

1. `feat(cad): add Module/Net/Layout placement spec and I2C pin map`
2. `feat(cad): orientation gallery with bounding-box substrate`
3. `feat(cad): greedy two-layer Manhattan router`
4. `feat(cad): wire-length, thermal-proxy, and crossing scoring`
5. `feat(cad): grid-search optimizer for unpinned modules`
