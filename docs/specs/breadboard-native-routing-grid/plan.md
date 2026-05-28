# Breadboard-native routing grid — plan

Date: 2026-05-28

## Problem

The design intends the 2.54 mm breadboard pitch to be the canonical coordinate
system (constitution Principle 2). Placement honours that — `_snap_devices_to_pitch`
(`board.py:139`) shifts every device so its pin lattice lands on exact 2.54 mm
multiples. But the **router** does not: A\* runs on a fixed 0.5 mm voxel grid
(`GRID_RES_MM = 0.5`, `grid.py:23`) whose origin is the board outline's
min-corner (`grid.py:62`, `from_board`).

These two grids are incommensurate:

- 2.54 / 0.5 = **5.08** — not an integer, so no 0.5 mm cell sits under a pin.
- The origin (`perim.x_min`) is the author-specified plate corner (`build.py:182`),
  which is not snapped to the pitch (Phase-4 Task 18 was never implemented).

So every 2.54-aligned pin is re-quantized through `to_grid()` (`grid.py:82`) to
the nearest 0.5 mm cell, up to 0.25 mm off its true centre. Wires and vias live
only on the voxel grid (a via's xy is `to_world()` of its layer-flip cell,
`autoroute.py:300`), so they cannot land on a pin column or a corner. The
pitch-aware align passes compound it: they treat one pitch as a hardcoded
`pitch_cells=5` (`autoroute.py:474,479`) = 2.5 mm, and `round(2.54/0.5)=5`
(`autoroute.py:556`) rounds the 0.04 mm away — so alignment is to a 2.5 mm
approximation, drifting 0.04 mm per pitch. The comments at `grid.py:28` and
`grid.py:214` already assert "2.54 mm = 5 grid cells at 0.5 mm", which is false
(5 × 0.5 = 2.5).

This is the root cause of the off-centre OLED vias, and it is the missing bridge
between the existing initiative's **Phase 4** (placement snapping — Task 17 done
in `be151d8`, Task 18 not done) and **Phase 5** (vectorized 45° edges — not
started). Phase 5 assumes diagonals between snapped endpoints are exact 45°
vectors through lattice points; that only holds once the routing lattice
actually contains those endpoints.

## Goal

Make the routing lattice contain every breadboard grid point, so a via or corner
on a pin column lands exactly on the pin, and a diagonal between two snapped pins
is an exact 45° vector through lattice points.

## Non-goals

- Vectorized 45° emission and synced bus chamfers — that is Phase 5; this plan is
  its precondition, not its delivery.
- Changing the buffer/hole model or any clearance value.
- Retiring the via-jog cleanup passes — tracked as an optional follow-on once the
  lattice change is proven to make them redundant.

## Design decision: derive resolution from the pitch

Replace the standalone `GRID_RES_MM = 0.5` constant with a resolution **derived
from the pitch**, so the cell size always divides 2.54 (constitution Principle 1:
one knob, derived everywhere). Introduce `pitch_subdivisions` (int, default 5):

```
res = pitch / pitch_subdivisions
```

| `pitch_subdivisions` | res (mm) | cells/pitch | vs today | Notes |
|---|---|---|---|---|
| 2 | 1.270 | 2 | much coarser | too coarse for sub-mm halos/clearances |
| **5** | **0.508** | **5** | ~same (+1.6 %) | **recommended** — matches the existing `pitch_cells=5` assumption, perf-neutral (slightly fewer cells → marginally faster), pins land exactly when the origin is aligned |
| 10 | 0.254 | 10 | finer | 4× grid area (slower/more memory); only if sub-pitch routing precision is later needed |

`pitch_subdivisions = 5` (res = 0.508 mm) is the minimal change: it is within
1.6 % of today's resolution, it makes `pitch_cells = 5` exact (so the align
passes stop approximating), and the grid gets marginally coarser, not finer, so
A\* search cost does not grow.

Commensurate resolution is necessary but not sufficient — the origin must also be
on the pitch lattice. Two coupled requirements:

1. **`res` divides the pitch** (resolution change above).
2. **Origin on the pitch lattice** — `x_min`/`y_min` snapped so that any pin at
   world `k · 2.54` maps to an integer cell. Equivalent to finishing Phase-4
   Task 18 (snap perimeter to pitch); with a pitch-multiple origin and
   `res = pitch/5`, a pin at `k · 2.54` maps to cell `5k` exactly.

## Phased tasks

Each task is a behavior-changing commit (geometry shifts), so per constitution
§Governance each ships separately and ends test-green with no new
clearance-invariant violations. This is **not** a behavior-preserving refactor.

### Task 1 — Derive `res` from the pitch
- `grid.py`: replace `GRID_RES_MM = 0.5` with `res = pitch / pitch_subdivisions`;
  thread `pitch` + `pitch_subdivisions` from `ResolvedDims` into `Grid.from_board`
  / `_build_grid` (currently `res` defaults to the module constant, `grid.py:53`).
- `board.py` / `build.py`: add `pitch_subdivisions` to `DimOverrides` + `_DEFAULTS`
  (default 5); expose `res` as a `ResolvedDims` accessor (`res = pitch / subdiv`).
- Acceptance: `Grid.res == 0.508`; `res` overridable per board via the pitch knobs.

### Task 2 — Align the grid origin to the pitch lattice
- `grid.py` (`from_board`) and/or `board.py`/`build.py`: snap the perimeter
  min-corner so `x_min`, `y_min` are pitch multiples relative to the pin lattice
  (finish Phase-4 Task 18 — perimeter + bus spacing on pitch).
- Acceptance: for every device pin, `to_world(*to_grid(pin)) == pin` exactly
  (within 1e-6). Add a test asserting pins round-trip through the grid with zero
  error on both production boards.

### Task 3 — Remove hardcoded cell-count assumptions
Audit and convert constants that silently assumed `res == 0.5`:
- `autoroute.py:474,479` `pitch_cells=5` → derive `round(pitch / g.res)` (now
  exactly 5, but no longer a magic literal); `autoroute.py:556` already derives it.
- `grid.py:32` `APPROACH_DEPTH = 3` (cells = 1.5 mm today) and `astar.py:33,38`
  `_PARALLEL_MIN=2` / `_PARALLEL_MAX=5` (cells) — re-express in mm and convert via
  `res`, or document that they are deliberately cell-counts.
- `grid.py:28,214` comments — fix to "2.54 mm = 5 cells at 0.508 mm" (now true).
- mm-based clearances (halos in `blocking.py`, `align.py:616`; no-turn radius
  `grid.py:357`; collapse residuals `collapse.py:453-454`) already divide by
  `g.res` and auto-scale — verify, no change expected.
- Acceptance: grep finds no surviving `0.5`/`5`-cell assumption tied to the pitch.

### Task 4 — Feed align passes the true pitch
- `autoroute.py`: pass the derived `pitch_cells` (exact 5) into `align_pair_pitch`
  / `align_parallel_pitch` / `align_cluster_pitch`; remove the 2.5 mm
  approximation drift.
- Acceptance: paired runs align to a true-2.54 offset, not 2.5; no per-pitch drift.

### Task 5 — Re-route and verify (checkpoint)
- `bin/test` green; `bin/lint` clean.
- `process-compose process restart prebuild-cad` regenerates all GLBs, no
  exceptions.
- Reports (`substrate_*.json`) show **no new** clearance-invariant violations
  (the objective gate). Length/aggregate deltas are expected and acceptable.
- Gallery diff at the dev URL reviewed: OLED-channel vias and 90° corners now sit
  centred on pin columns; no new visual regressions.

### Task 6 — (Optional follow-on) Retire redundant via-jog cleanup
Once Task 5 confirms vias land on-lattice, evaluate whether `pull_stub_vias`,
`slide_via_pair_clusters`, and `merge_via_clusters` (`align.py`) are now no-ops
and can be removed. Separate commit, only if the report + gallery prove them
redundant.

## Risks

- **Origin coupling.** A pitch-dividing `res` buys nothing if the origin is not
  pitch-aligned; Tasks 1 and 2 must land together (or Task 2 first) or the
  round-trip test in Task 2 will fail by design.
- **Behavior change blast radius.** All routed geometry shifts; the gate is "no
  *new* invariant violations", not "identical output". Expect report deltas.
- **Missed cell-count constant.** A single un-converted literal (Task 3) yields
  subtle misalignment; the audit list above is the checklist, and the Task 2
  round-trip test catches origin/resolution errors.
- **Performance (only if `subdiv=10`).** 0.254 mm quadruples grid area; check A\*
  route time before adopting. `subdiv=5` is perf-neutral.

## Relationship to the existing initiative

This plan completes **Phase 4 Task 18** (perimeter → pitch) and supplies the
precondition for **Phase 5** (vectorized 45° + synced chamfers) in
`docs/specs/breadboard-canonical-substrate/tasks.md`. It is the routing-substrate
half of "the breadboard is the ruler": placement already snaps to pitch; this
makes the router measure in the same units.
