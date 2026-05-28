# Breadboard-canonical substrate Implementation Tasks

## Overview

**Total Tasks**: 24
**Phases**: 6 (Phase 0–5, mirroring the plan's locked sequencing)
**Parallelizable Tasks**: 6 (marked `[P]`)

Each phase ends test-green with no new clearance-report violations. Phases 0–1
are behavior-preserving; Phases 2–5 each introduce one intended behavior change.
Per the constitution, a refactor and a behavior change never share a commit.

## Task Dependency Graph

```
Phase 0 (docs)         T1 ─ T2 ─ T3
                         │
Phase 1 (consolidate)  T4(buffer/pitch+accessors) ─┬─ T5 ─┐
                                                    ├─ T6 ─┤
                                                    ├─ T7 ─┼─ T9(golden) ─ T10(delete dead) 
                                                    └─ T8 ─┘
Phase 2 (buffer=1.0)   T11 ─ T12 ─ T13
Phase 3 (holes)        T14 ─ T15 ─ T16
Phase 4 (snapping)     T17 ─ T18 ─ T19
Phase 5 (vector 45°)   T20 ─ T21 ─ T22 ─ T23 ─ T24
```

---

## Phase 0: Discovery doc + schema (no behavior change)

### Task 1: Author the breadboard-model discovery doc
**User Story**: US-5, US-6 (foundation) · **Type**: Docs · **Dependencies**: None

**Description:** Write `docs/breadboard-model.md` — the discovery doc: 2.54 mm as
canonical coordinate system; the universal `buffer` model; unified 1.25 mm hole +
lead-in + grip; the voxel→vectorized-45° trajectory and how synced bus chamfers
fall out.

**Files to Create/Modify:**
- `docs/breadboard-model.md` — new discovery doc (no code).

**Acceptance Criteria:**
- [ ] Covers breadboard grid, buffer, unified hole/lead-in/grip, vector-45° path.
- [ ] References the spec/plan/data-model under `docs/specs/breadboard-canonical-substrate/`.

**Validation:** Doc renders; cross-links resolve.

### Task 2: Extend vernacular [P]
**User Story**: Infrastructure · **Type**: Docs · **Dependencies**: None

**Files to Create/Modify:**
- `docs/vernacular.md` — add: buffer, breadboard unit/pitch, receptacle,
  lead-in, grip, via, chamfer.

**Acceptance Criteria:**
- [ ] Each term has a one-line definition consistent with the spec.

**Validation:** Terms present; no contradictions with `spec.md`.

### Task 3: Point README at the dimension model [P]
**User Story**: Infrastructure · **Type**: Docs · **Dependencies**: None

**Files to Create/Modify:**
- `code/cad/README.md` — link to `docs/breadboard-model.md` + the dimension
  schema (`data-model.md`).

**Acceptance Criteria:**
- [ ] README points a new reader at the model and the breadboard convention.

**Validation:** Links resolve.

## Checkpoint: Model documented
- [ ] Discovery doc + vernacular + README in place — the model is the written
      reference before any code changes.

---

## Phase 1: Consolidation commit (behavior-preserving)

### Task 4: Introduce `buffer` + `pitch` knobs and `ResolvedDims` accessors
**User Story**: US-1, US-8 · **Type**: Model · **Dependencies**: T1

**Description:** Add `buffer` (default = current `min_wall_thickness` = 0.6) and
`pitch` (2.54) to `_DEFAULTS`, `DimOverrides`, `ResolvedDims`. Add derived
accessors that are the single definition of each formula: `wall_floor_mm`,
`wall_halo_mm`, `via_halo_mm`, `edge_inflate_mm`, `pocket_margin_mm`,
`hole_bore_mm`. Keep `pocket_clearance`/`edge_clearance` as terms so values are
unchanged this phase.

**Files to Create/Modify:**
- `code/cad/src/board/board.py` — add `buffer`, `pitch` to `DimOverrides`.
- `code/cad/src/board/build.py` — `_DEFAULTS`, `ResolvedDims`, accessors.

**Acceptance Criteria:**
- [ ] Accessors return the exact current values (1.4 / 1.15 / 1.35 / 1.0 / 0.7 / 1.0).
- [ ] `buffer` and `pitch` overridable from YAML.

**Validation:** `bin/test` green; unit test asserts accessor values.

### Task 5: Repoint blocking + align halos at the accessor [P]
**User Story**: US-8 · **Type**: Refactor · **Dependencies**: T4

**Files to Create/Modify:**
- `code/cad/src/router/blocking.py` — use `dims.wall_halo_mm` / `via_halo_mm`.
- `code/cad/src/router/align.py` — use `dims.wall_halo_mm` (remove the
  re-derived formula at ~line 617).

**Acceptance Criteria:**
- [ ] No `channel_width + min_wall_thickness …` formula remains outside `ResolvedDims`.

**Validation:** `bin/test` green; grep finds zero duplicate halo formulas.

### Task 6: Repoint grid edge/pocket inflation at accessors [P]
**User Story**: US-8 · **Type**: Refactor · **Dependencies**: T4

**Files to Create/Modify:**
- `code/cad/src/router/grid.py` — edge strip + `pocket_margin` from accessors;
  remove duplicated pocket inflation (vs `build.py:287`).

**Acceptance Criteria:**
- [ ] Pocket margin + edge strip derive from `ResolvedDims`.

**Validation:** `bin/test` green; report unchanged.

### Task 7: Repoint scorer + report at accessors [P]
**User Story**: US-8 · **Type**: Refactor · **Dependencies**: T4

**Files to Create/Modify:**
- `code/cad/src/router/score.py` — drop shadow default literals; require dims.
- `code/cad/src/board/cli_report.py`, `cli_score.py` — read `wall_floor_mm` etc.
- `code/cad/src/router/paths.py` — drop hardcoded `via_diameter=1.5` default.

**Acceptance Criteria:**
- [ ] No clearance literal remains in `score.py`/`paths.py` signatures.

**Validation:** `bin/test` green; `score-routes` unchanged on reference boards.

### Task 8: Golden-output regression harness [P]
**User Story**: US-8 · **Type**: Test · **Dependencies**: T4

**Description:** Capture pre-change routed geometry + report for the reference
boards; assert identical after the repoints (T5–T7).

**Files to Create/Modify:**
- `code/cad/tests/` — golden test for `i2c_midline_no_oled` (+ siblings).

**Acceptance Criteria:**
- [ ] Test fails if any segment/via/report value changes.

**Validation:** `bin/test` green with T5–T7 applied.

### Task 9: Verify behavior-preserving consolidation
**User Story**: US-8 · **Type**: Checkpoint · **Dependencies**: T5,T6,T7,T8

**Validation:**
- [ ] `bin/test` green.
- [ ] `process-compose process restart prebuild-cad` regenerates all GLBs, no exceptions.
- [ ] Reports show zero diff vs pre-change.

### Task 10: Delete dead `hole_pair_clearance`
**User Story**: US-8 · **Type**: Refactor · **Dependencies**: T9

**Files to Create/Modify:**
- `code/cad/src/board/build.py` (`_DEFAULTS`, `ResolvedDims`),
  `code/cad/src/board/board.py` (`DimOverrides`) — remove the knob.

**Acceptance Criteria:**
- [ ] Grep for `hole_pair_clearance` returns nothing.

**Validation:** `bin/test` green.

## Checkpoint: Consolidation complete (behavior-preserving)
- [ ] One `buffer`/one bore source; each formula defined once; dead knob gone;
      numeric output identical.

---

## Phase 2: Universal buffer enforcement (default 1.0 mm)

### Task 11: Switch `buffer` default to 1.0 and fold in pocket/edge clearance
**User Story**: US-1, US-4 · **Type**: Model · **Dependencies**: T10

**Files to Create/Modify:**
- `code/cad/src/board/build.py` — `buffer`=1.0; `pocket_margin_mm` /
  `edge_inflate_mm` derive from `buffer` (drop independent `pocket_clearance`/
  `edge_clearance` defaults).

**Acceptance Criteria:**
- [ ] Every governed gap widens uniformly with `buffer`.
- [ ] Via↔sensor-pocket edge ≥ `buffer` (US-4).

**Validation:** Report shows no via-to-pocket violations; `bin/test` green.

### Task 12: Fail-loud on unroutable buffer / over-constraint
**User Story**: US-1, US-5 (FR-11) · **Type**: Backend · **Dependencies**: T11

**Files to Create/Modify:**
- `code/cad/src/router/autoroute.py` (+ grid as needed) — raise a clear
  conflict error naming the feature pair/placement; no auto-relax.

**Acceptance Criteria:**
- [ ] An over-large buffer raises with an actionable message, not invalid geometry.

**Validation:** Targeted test: unroutable buffer raises; `bin/test` green.

### Task 13: Re-route + visual/report verify (Phase 2)
**User Story**: US-4 · **Type**: Checkpoint · **Dependencies**: T11,T12

**Validation:**
- [ ] GLB regen no exceptions; midline vias clear sensors by ≥ buffer in the gallery.
- [ ] Reports clean.

---

## Phase 3: Unified 1.25 mm holes + receptacle lead-in + grip

### Task 14: Unify hole bore to 1.25 mm (receptacle = pin drill = via)
**User Story**: US-3 · **Type**: Model · **Dependencies**: T10

**Files to Create/Modify:**
- `code/cad/src/board/build.py` — `hole_diameter`=`via_diameter`=1.25; all
  drilling reads `hole_bore_mm`; via diameter independently overridable.

**Acceptance Criteria:**
- [ ] One edit changes all three bores; override still possible per board.

**Validation:** `bin/test` green; report hole diameter = 1.25.

### Task 15: Add receptacle lead-in + grip target
**User Story**: US-2 (FR-4, FR-12) · **Type**: Model+Geometry · **Dependencies**: T14

**Files to Create/Modify:**
- `code/cad/src/board/connectors.py` — `drill_diameter` from `hole_bore_mm`;
  add `lead_in_depth`/`lead_in_angle`/`grip_diameter` fields.
- `code/cad/src/board/build.py` — pedestal drilling cuts the lead-in chamfer +
  grip step.

**Acceptance Criteria:**
- [ ] Each receptacle shows a lead-in at the opening + a grip step below.

**Validation:** GLB regen; visual lead-in present; `bin/test` green.

### Task 16: Receptacle print/fit checkpoint
**User Story**: US-2 · **Type**: Checkpoint · **Dependencies**: T15

**Validation:**
- [ ] (Human) coupon/reference re-print: DuPont pin self-guides and holds.
- [ ] Documented as printer-dependent in `docs/fdm_tolerance_notes.md`.

---

## Phase 4: Breadboard snapping

### Task 17: Snap device placements to pitch
**User Story**: US-5 (FR-6) · **Type**: Model · **Dependencies**: T10

**Files to Create/Modify:**
- `code/cad/src/board/board.py` — resolve placements onto `pitch` multiples,
  declaratively.

**Acceptance Criteria:**
- [ ] Placements land on 2.54 mm multiples; conflict → fail-with-report (T12 path).

**Validation:** `bin/test` green; placements on pitch in report.

### Task 18: Snap perimeter + bus spacing to pitch
**User Story**: US-5 (FR-7) · **Type**: Model · **Dependencies**: T17

**Files to Create/Modify:**
- `code/cad/src/board/board.py` / `build.py` — perimeter + bus spacing on pitch.

**Acceptance Criteria:**
- [ ] Perimeter + bus positions are pitch-derived.

**Validation:** `bin/test` green.

### Task 19: Re-route affected boards (Phase 4)
**User Story**: US-5 · **Type**: Checkpoint · **Dependencies**: T17,T18

**Validation:**
- [ ] GLB regen no exceptions; gallery + reports verified for the reference board.

---

## Phase 5: Vectorized 45° edges + synchronized chamfers

### Task 20: Vectorized 45° run/corner representation
**User Story**: US-6 (FR-8) · **Type**: Backend · **Dependencies**: T10

**Files to Create/Modify:**
- `code/cad/src/router/collapse.py` (+ `paths.py`) — emit exact 45° vectors
  anchored on the breadboard grid instead of staircase reconstruction.

**Acceptance Criteria:**
- [ ] Diagonals render as single straight edges; corners clean.

**Validation:** GLB regen; gallery shows smooth diagonals; `bin/test` green.

### Task 21: Synchronized chamfer slot after pitch alignment
**User Story**: US-7 (FR-9) · **Type**: Backend · **Dependencies**: T20

**Files to Create/Modify:**
- `code/cad/src/router/autoroute.py` (`_finalise_collapse`) — add the synced-
  chamfer slot after `align_cluster_pitch`, before per-path collapse.

**Acceptance Criteria:**
- [ ] Slot runs on adjacent bus pairs at the correct pipeline position.

**Validation:** `bin/test` green; ordering asserted.

### Task 22: Apply synchronized chamfers to every adjacent bus pair
**User Story**: US-7 (FR-9) · **Type**: Backend · **Dependencies**: T21

**Files to Create/Modify:**
- `code/cad/src/router/align.py` / `collapse.py` — pair detection + aligned
  chamfers; must not cut a via barrel or pin approach.

**Acceptance Criteria:**
- [ ] Adjacent bus pairs chamfer together, aligned; no chamfer into via/pin.

**Validation:** Report no via/pin intrusion; gallery shows tidy bundles.

### Task 23: Regression: clearance invariants under vector geometry
**User Story**: US-6, US-7 · **Type**: Test · **Dependencies**: T22

**Files to Create/Modify:**
- `code/cad/tests/` — assert wall-floor / via / edge invariants hold for the
  new diagonal + chamfer geometry.

**Validation:** `bin/test` green; report clean.

### Task 24: Final verification
**User Story**: All · **Type**: Checkpoint · **Dependencies**: T23

**Validation:**
- [ ] `bin/test` green; `bin/lint` clean.
- [ ] GLB regen no exceptions; gallery diff at the reference URL reviewed.
- [ ] Reports show no new violations across all boards.

## Checkpoint: Feature complete
- [ ] All four pillars shipped; each phase landed as its own commit; reports clean.

---

## Summary

| Phase | Tasks | Parallel | Behavior |
|-------|-------|----------|----------|
| 0. Docs | T1–T3 | T2,T3 | none |
| 1. Consolidate | T4–T10 | T5,T6,T7,T8 | preserving |
| 2. Buffer=1.0 | T11–T13 | — | change |
| 3. Holes+lead-in+grip | T14–T16 | — | change |
| 4. Snapping | T17–T19 | — | change |
| 5. Vector 45°+chamfers | T20–T24 | — | change |

**Critical path:** T1 → T4 → {T5,T6,T7,T8} → T9 → T10 → (T11/T14/T17/T20 fan out)
→ T20 → T21 → T22 → T23 → T24.

**Total parallelizable:** 6 tasks (`[P]`): T2,T3 (Phase 0) and T5,T6,T7,T8 (Phase 1).

**Note:** Phases 2–5 depend only on T10 (consolidation complete), so after Phase
1 they can be sequenced in any order; the plan's order (buffer → holes →
snapping → vector) front-loads the printability wins (US-2/US-4).
