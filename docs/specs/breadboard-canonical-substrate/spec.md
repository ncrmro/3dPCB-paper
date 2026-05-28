# Breadboard-canonical substrate Specification

## Overview

### Problem Statement

The substrate compiler is slow and error-prone to iterate for 3D printing,
for four compounding reasons:

1. **Scattered clearances.** The minimum gaps the design must respect (between
   a sensor pocket and a wire, between a via and a sensor edge, between two
   wires, between a channel and the board edge) are expressed as a family of
   independent numbers. There is no single dial to widen every gap at once, so
   tuning a print for fit means hunting and editing several values that must
   stay mutually consistent.

2. **Holes that don't print.** Receptacle bores, pin drill holes, and vias use
   different diameters, and the receptacle bore prints closed/too tight on the
   validation FDM hardware. A standard DuPont pin only seats reliably at a
   1.25 mm designed bore, and the printed receptacles have no lead-in, so pins
   won't self-guide into them.

3. **Vias too close to sensors.** Along the board midline, vias surface near
   the sensor pockets with too little solid material between the via barrel and
   the pocket edge, leaving thin walls or gaps in the print.

4. **Pixelated geometry.** Diagonal and corner geometry is reconstructed from a
   fine grid, so 45° runs and corners look staircased rather than as clean
   straight edges — which also complicates the synchronized chamfers between
   paired bus signals.

### Business Value

This is the spike CAD behind a research paper whose claim is that a single
declarative artifact can be iterated quickly into a printable substrate. Making
the dimensions tweakable from one knob, the holes reliably printable, and the
geometry clean directly serves that claim and shortens the print-test loop that
currently dominates iteration time.

### Target Users

- **Board designer / hardware iterator**: authors a declarative board
  description, generates the substrate, prints it, and fits real components and
  DuPont pins. Wants to adjust fit for their printer with the fewest possible
  knobs and re-print fast.
- **Substrate-compiler maintainer**: reasons about and debugs clearances and
  routing. Wants one place that defines each dimension so changes don't have to
  be mirrored across the system.
- **Reviewer**: confirms a change didn't regress fit, clearance, or
  printability before it merges.

## User Stories

### US-1: Tune all clearances with one knob

**As a** board designer
**I want to** set a single "buffer" value that governs the minimum material gap
between every pair of features
**So that** I can loosen or tighten an entire print's fit in one edit instead of
reconciling several independent clearance numbers

**Acceptance Criteria:**
- [ ] A single buffer parameter exists with a documented default of 1.0 mm.
- [ ] The minimum gap between every feature pair (sensor-pocket edge ↔ wire,
      board edge ↔ channel, wire ↔ wire, via barrel ↔ any neighbor) is governed
      by that one buffer value.
- [ ] The buffer can be overridden per board in the declarative spec without
      editing compiler source.
- [ ] Increasing the buffer visibly widens every governed gap; decreasing it
      narrows them — uniformly.

**Edge Cases:**
- Buffer set so large the board can no longer be routed: the system fails with a
  clear conflict report naming the feature pair(s) that could not satisfy the
  buffer, rather than auto-relaxing or producing an invalid/overlapping result.
- Buffer omitted in a board spec: the documented default applies.

### US-2: Print receptacles that accept a DuPont pin

**As a** board designer
**I want to** print receptacles whose bore reliably accepts a standard DuPont
pin and guides it in
**So that** I can seat jumper wires by hand without the hole printing closed or
the pin missing the opening

**Acceptance Criteria:**
- [ ] Receptacle bores use the validated 1.25 mm designed diameter.
- [ ] Each receptacle has a lead-in at its opening so a pin self-centers as it
      enters.
- [ ] Each receptacle has a CAD grip/interference target (e.g. a tapered or
      slightly undersized lower bore) so seating grip does not depend on slicer
      settings.
- [ ] On the validation hardware, a printed receptacle passes a standard DuPont
      pin and holds it (consistent with the receptacle coupon v2 result).

**Edge Cases:**
- Different printer/hardware: the bore value is documented as printer-dependent
  and overridable, with a pointer to re-run the coupon.

### US-3: One hole size across the design

**As a** substrate-compiler maintainer
**I want to** define receptacle bores, pin drill holes, and vias from a single
hole-size source
**So that** the three never drift apart and changing the validated bore is a
one-line edit

**Acceptance Criteria:**
- [ ] Receptacle bore, pin drill hole, and via diameter all derive from one
      unified hole size, defaulting to 1.25 mm.
- [ ] Changing that one value changes all three together.
- [ ] The unified size matches the sensor pin pitch convention so holes land on
      real pins.

**Edge Cases:**
- A board needs a larger via than pin hole: the override mechanism allows it,
  but the default keeps them unified.

### US-4: Vias clear sensor edges

**As a** board designer
**I want to** vias to keep at least the buffer distance from sensor-pocket edges
**So that** the print has enough solid wall around each via and doesn't leave a
gap or thin wall next to a sensor

**Acceptance Criteria:**
- [ ] No via barrel sits closer than the buffer to any sensor-pocket edge.
- [ ] The midline vias that previously crowded the sensors now clear them by at
      least the buffer.
- [ ] The clearance report shows no via-to-pocket violations.

**Edge Cases:**
- A net genuinely needs a via where no buffer-respecting spot exists: the
  system reports the conflict rather than silently violating the buffer.

### US-5: Breadboard-snapped placements

**As a** board designer
**I want to** device placements and the board perimeter to resolve onto the
2.54 mm breadboard grid
**So that** components, pin rows, and the outline "click together" on a
predictable pitch and the layout is easy to reason about and reproduce

**Acceptance Criteria:**
- [ ] Device placements snap to 2.54 mm pitch multiples.
- [ ] The board perimeter snaps to pitch multiples.
- [ ] Bus spacing falls on pitch-derived positions.
- [ ] Snapping is expressed declaratively in the board spec, not hand-computed.

**Edge Cases:**
- A placement that can't satisfy snapping plus the buffer simultaneously: the
  system fails with a clear conflict report identifying the placement, rather
  than silently relaxing snapping or the buffer.

### US-6: Clean 45° edges and corners

**As a** board designer
**I want to** diagonal runs and corners to render as clean straight 45° edges
**So that** the printed substrate looks finished rather than staircased and the
channels are smooth

**Acceptance Criteria:**
- [ ] 45° runs render as single straight edges, not visible step sequences.
- [ ] Corners are clean rather than pixelated.
- [ ] The visual gallery for the reference board shows smooth diagonals.

### US-7: Synchronized bus chamfers

**As a** board designer
**I want to** paired bus signals (e.g. VCC/GND, SCL/SDA) to receive matching,
aligned chamfers
**So that** companion traces bend together as a tidy bundle rather than
diverging at corners

**Acceptance Criteria:**
- [ ] Any two bus traces running parallel at pitch receive chamfers that are
      synchronized (aligned and consistent) with each other — synchronization is
      automatic for every adjacent bus pair, not limited to explicitly declared
      pairs.
- [ ] Synchronized chamfers are applied after the parallel signals are
      pitch-aligned.
- [ ] No chamfer cuts into a via barrel or a pin approach.

### US-8: Refactor without changing the print

**As a** reviewer
**I want to** the consolidation of scattered clearances into the buffer model to
be behavior-preserving in its first phase
**So that** I can adopt the new dimension model without re-validating a changed
physical print in the same step

**Acceptance Criteria:**
- [ ] The consolidation phase produces numerically identical routing/geometry
      output to before (the dial-to-default switch is a later, separate phase).
- [ ] The full test suite is green.
- [ ] Substrate clearance reports show no new violations.

**Edge Cases:**
- A behavior change is unavoidable during consolidation: it is split into its
  own clearly-labeled behavior-changing phase rather than hidden in the refactor.

## Requirements

### Functional Requirements

| ID | Requirement | Priority | Notes |
|----|-------------|----------|-------|
| FR-1 | A single `buffer` parameter governs the minimum gap of every feature pair | Must Have | Default 1.0 mm |
| FR-2 | `buffer` is overridable per board in the declarative spec | Must Have | |
| FR-3 | Receptacle bore, pin drill, and via derive from one unified hole size; via diameter is separately overridable per board | Must Have | Default 1.25 mm, unified |
| FR-4 | Receptacles have a lead-in at the opening | Must Have | DuPont self-guide |
| FR-5 | Vias clear sensor-pocket edges by at least `buffer` | Must Have | |
| FR-6 | Device placements snap to 2.54 mm pitch multiples | Must Have | |
| FR-7 | Board perimeter snaps to pitch multiples | Must Have | |
| FR-8 | 45° runs and corners render as clean straight edges | Should Have | Replaces staircase |
| FR-9 | Every adjacent bus pair (any two traces parallel at pitch) receives synchronized chamfers after pitch alignment | Should Have | Largest change; automatic, not declared-only |
| FR-10 | The clearance consolidation phase is behavior-preserving | Must Have | Numeric output identical |
| FR-11 | An over-constrained board (buffer unroutable, or snapping vs. buffer conflict) fails with a clear conflict report | Must Have | No silent invalid output, no auto-relax |
| FR-12 | Receptacles have a CAD grip/interference target so seating grip does not depend on slicer settings | Must Have | Second hole-shape feature beyond the lead-in |

### Non-Functional Requirements

#### Printability
- Designed hole/bore values reflect measured FDM behavior on the validation
  hardware; defaults are documented as printer-dependent and overridable.
- The default buffer (1.0 mm) is justified against the measured ~0.4 mm
  worst-case over-extrusion.

#### Reliability / regression
- The test suite must be green at every phase.
- Regenerating all substrate models must complete with no exceptions.
- Clearance-invariant reports must show no new violations after a change.

#### Maintainability
- Each dimension is defined once and derived elsewhere; there is no parallel
  hardcoded copy of a clearance, bore, or halo that can drift.

## Scope

### In Scope
- A single universal `buffer` clearance model with a per-board override.
- Unified hole size for receptacles, pin drills, and vias, plus a receptacle
  lead-in.
- Via-to-sensor-edge clearance respecting the buffer.
- Breadboard 2.54 mm canonical sizing: placement and perimeter snapping.
- Vectorized 45° edges/corners and synchronized bus-pair chamfers.
- A behavior-preserving consolidation phase, then the value switches, sequenced
  separately.

### Out of Scope
- A full rewrite of the router beyond the geometry needed for clean 45° edges
  and synchronized chamfers.
- Per-board chamfer tuning knobs.
- Re-validating FDM tolerance numbers on hardware other than the current
  validation printer (documented as a per-printer follow-up).
- Changes to the upstream KiCad electrical design or netlist.

### Assumptions
- The 1.25 mm bore and ~0.4 mm over-extrusion figures from the validation
  hardware are representative for the default printer.
- Boards are authored declaratively (spec-driven), so snapping and overrides can
  be expressed in the spec rather than hand-computed.
- The reference board (`i2c_midline_no_oled`) is the primary visual/clearance
  acceptance target.

### Dependencies
- Measured FDM tolerances (`docs/fdm_tolerance_notes.md`).
- The discovery document that records the breadboard model and the consolidated
  dimension schema (to be authored before behavior changes, per the
  constitution).
- The clearance-invariant report as the objective acceptance gate.

## Clarifications

### 2026-05-28 Clarification Session

**Q1: Does the unified 1.25 mm bore apply to vias, or do vias get a larger
barrel by default?**
A: Unified, overridable. Vias default to the same unified hole size as
receptacles and pin drills; a board may override the via diameter separately
when a net genuinely needs a bigger barrel.
Impact: FR-3 keeps a single default hole size and adds a per-board via-diameter
override; the US-3 edge case is the override path.

**Q2: When constraints can't all be satisfied (buffer too large to route, or
snapping vs. buffer conflict), what should the compiler do?**
A: Fail with a clear conflict report. Never emit silently-invalid geometry and
never auto-relax; surface exactly which feature pair or placement could not
satisfy the buffer/snapping and stop so the designer chooses the fix.
Impact: FR-11 promoted to Must Have; the US-1 and US-5 edge cases now specify
fail-with-report rather than auto-relax. Merges the former open questions about
unroutable buffer and snapping-vs-buffer conflict into one rule.

**Q3: Which bus pairs get synchronized chamfers?**
A: Every adjacent bus pair. Any two bus traces running parallel at pitch are
synchronized automatically, not limited to explicitly declared pairs (e.g.
VCC/GND, SCL/SDA).
Impact: FR-9 and US-7 specify automatic synchronization for all adjacent bus
pairs.

**Q4: Is a lead-in chamfer enough for DuPont seating, or is a separate
grip/interference target required?**
A: Lead-in plus a CAD grip target. In addition to the self-guiding lead-in, a
receptacle has an explicit interference/grip dimension (e.g. tapered or slightly
undersized lower bore) so grip does not depend on slicer settings.
Impact: New FR-12; US-2 gains a grip-target acceptance criterion.

## Acceptance Checklist

### User Stories
- [x] All stories have 3+ acceptance criteria (where applicable)
- [x] All criteria are testable/measurable
- [x] Edge cases are documented

### Requirements
- [x] Printability thresholds defined (1.0 mm buffer, 1.25 mm bore, 2.54 mm pitch)
- [x] Failure behavior is specific (fail-with-report, no silent invalid output)
- [x] Maintainability requirement is specific (single source per dimension)

### Scope
- [x] In-scope items are detailed
- [x] Out-of-scope items are explicit
- [x] Assumptions are documented

### Completeness
- [x] No open questions remain
- [x] All ambiguities resolved
- [x] Ready for technical planning
