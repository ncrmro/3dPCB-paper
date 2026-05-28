# The breadboard-canonical substrate model

A discovery doc: anchoring the substrate compiler on the 2.54 mm breadboard
grid, governing every clearance with one universal **buffer**, unifying the hole
sizes, and moving from staircased voxel reconstruction to vectorized 45° edges.
This is the written model the code is reorganised around; it precedes the code
churn (see `docs/constitution.md` — docs/specs first).

The feature's specification, plan, data model, research, and task breakdown live
in `docs/specs/breadboard-canonical-substrate/`.

## 1. The breadboard is the ruler

The validation assembly (ESP32-C3 SuperMini, SCD41, BH1750, optional OLED) is
built from parts on a **2.54 mm** pin pitch — the breadboard module. Treating
that pitch as the canonical sizing and coordinate unit makes the geometry "click
together":

- Device placements snap to pitch multiples, so pin rows land on a common grid.
- The board perimeter snaps to pitch multiples.
- Bus spacing falls on pitch-derived positions.

The strategic payoff is geometric: when runs start and end on a regular grid,
diagonal segments land on exact **45°** vectors. That is what lets the router
represent runs and corners as true vectors instead of reconstructing them from a
fine voxel grid (§4), and it is what makes synchronised bus chamfers fall out
naturally (§5).

## 2. One universal buffer

Today the design carries a scattered family of clearances —
`pocket_clearance`, `edge_clearance`, `min_wall_thickness`, a wire halo, a via
halo, a pocket margin — defined independently across the builder, the grid, the
blocking pass, the scorer, the alignment pass, and the report. There is no single
dial, so tuning a print for fit means reconciling several numbers.

The discovery: these are **one quantity**. Every keep-out is

```
(half the feature's own extent) + buffer
```

where `buffer` is the minimum solid material you want between a feature's edge
and any neighbour. Concretely (current values, 0.5 mm grid):

| Keep-out | Derivation | Value |
|---|---|---|
| wire ↔ wire (wall floor) | `channel_width + buffer` | 1.4 |
| wire halo (grid keep-out) | `channel_width + buffer − res/2` | 1.15 |
| via halo | `via_diameter/2 + buffer` | 1.35 |
| channel ↔ board edge (score) | `channel_width/2 + buffer` | 1.0 |
| pocket margin (routing) | `pocket_clearance + buffer + channel_width/2` | 1.3\* |

\* The pocket margin carries a full `buffer` wall between a top channel and the
device recess, like every other gap; `pocket_clearance` (0.3) is only the
device drop-in fit. Boards are spread out so this is routable at the generous
default — see the data-model finding on buffer vs breadboard pitch.

**Therefore:** `min_wall_thickness` *is* the buffer. Promote it to a single
`buffer` knob (default 1.0 mm, justified by the ~0.4 mm worst-case FDM
over-extrusion in `docs/fdm_tolerance_notes.md`), make every clearance a derived
accessor on one resolved-dimensions object, and let a board override it from
YAML. Adding a clearance should touch one definition, not several.

The vias-near-sensors print failure falls out of this model for free: once the
via↔sensor-pocket gap is governed by `buffer`, the midline vias that crowded the
sensors are pushed clear.

## 3. One hole size

Receptacle bores, pin drill holes, and vias are three independent diameters
today, and the receptacle bore prints closed on the validation hardware. The
coupon results (`docs/fdm_tolerance_notes.md`) give one validated number: a
**1.25 mm** CAD bore both passes light and accepts/holds a standard DuPont pin;
bores below ~0.8 mm vanish under default slicer settings.

So unify: receptacle = pin drill = via = one `hole_diameter`, default 1.25 mm,
with the via diameter still independently overridable when a net genuinely needs
a bigger barrel. Each receptacle additionally gets:

- a **lead-in** chamfer at the opening so a pin self-centres, and
- a **grip** target (tapered/undersized lower bore) so seating grip does not
  depend on slicer hole-compensation settings.

## 4. Voxel → vectorized 45°

The router is a 0.5 mm voxel A*; diagonal runs and corners are reconstructed
from cells, which looks staircased and complicates the synced bus chamfers.
Anchoring on the breadboard grid (§1) means a diagonal between two snapped
endpoints is an exact 45° vector — it can be represented and cut as a straight
edge rather than a sequence of steps. This is the largest change and is
sequenced last; the model here is locked first so the geometry stage can be
rewritten against a fixed target.

## 5. Synchronised bus chamfers

Once paired bus signals (VCC/GND, SCL/SDA, or any two traces parallel at pitch)
are pitch-aligned, a 45° chamfer applied to one should be mirrored on its
neighbour so the bundle bends together. With vectorized 45° geometry (§4) this
is a vector operation rather than cell-list surgery: apply synchronised chamfers
to every adjacent bus pair *after* pitch alignment and *before* per-path
collapse, never cutting into a via barrel or a pin approach.

## Sequencing

Per the constitution, docs and the dimension schema come first (this doc + the
spec folder), then a **behavior-preserving** consolidation that introduces the
`buffer`/`pitch` knobs and derived accessors without changing any value, then the
intended value changes one phase (and one commit) at a time: buffer → 1.0,
unified 1.25 mm holes + lead-in + grip, breadboard snapping, vectorized 45° +
synced chamfers. Each phase ends test-green with no new clearance-report
violations. See `docs/specs/breadboard-canonical-substrate/tasks.md`.
