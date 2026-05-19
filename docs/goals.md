# Goals

Date: 2026-05-14
Status: draft

## Purpose

Enable an agent — LLM-driven, scripted, or human-with-a-checklist — to
take this repo's KiCad netlist plus 3D placement intent and emit a
printable, build-instructable artifact: a 3D-printed substrate, an
enclosed case housing that substrate, or a substrate that accepts COTS
modules via pre-soldered male headers.

The paper exists because [ncrmro/plant-caravan](https://github.com/ncrmro/plant-caravan)
needs sensor mounts ([PR #28](https://github.com/ncrmro/plant-caravan/pull/28)
`feat(hardware): sensor mounts`). Tier 1 below is the artifact
plant-caravan actually consumes today; Tiers 2 and 3 are
generalizations the paper claims the same pipeline can produce.

## What "an agent can produce" means

Given the canonical KiCad project at `code/kicad/spike.kicad_pcb` plus
a placement sidecar, the agent calls existing scripts in this repo and
gets back:

- a `.scad` / `.stl` substrate (or case) ready for any FDM slicer,
- a routed wire-channel layout (Tiers 1–2) or socket layout (Tier 3),
- review artifacts the agent can inspect before declaring success: GLB
  in `<model-viewer>`, iso PNG, score table (wire length, thermal
  proxy, crossings),
- a build sheet: BOM, wire-cut lengths, solder points, orientation
  marks.

The agent's loop is: ingest KiCad → place modules → route → render →
score → iterate. Every step is a CLI invocation, every output is a
file on disk.

## Three design tiers

The three tiers escalate along two independent axes: **conductor
mechanism** (how the wire is held in place) and **dimensionality**
(flat plate vs. multi-level Z-stack). Each tier exposes the same
netlist; only the physical embodiment changes.

### Tier 1 — flat substrate, bare-copper through-hole conductor

The minimal viable artifact and the one plant-caravan consumes.

- 3D-printed flat plate.
- ESP32-C3 SuperMini + SCD41 + BH1750 laid out coplanar, inlay pockets
  per module.
- I2C routed: `SDA`, `SCL`, `+3V3`, `GND` — four nets, multi-stop.
- Routing channels emerge as through-holes at each pad position. The
  user threads bare copper wire through the hole, solders to the COTS
  module pad on top, snips the excess underneath. **The wire is the
  conductor.** No male headers, no female sockets, no PCB.
- Build instructions enumerate: wire gauge, cut lengths per net,
  solder-pad order.

Why it's first: plant-caravan's PR #28 already has the enclosure +
sensor mount geometry; what it lacks is a routed substrate that
solves the wiring story. Tier 1 unblocks that PR.

### Tier 2 — Tier 1 substrate + OLED device on pressure-fit receptacles

Same flat plate, same three modules as Tier 1 mounted exactly the
same way (bare copper wire soldered through through-holes —
**unchanged**). The *only* new element is a fourth I2C device,
mounted by a brand-new mechanism:

- **+1 device on the primary I2C bus**: a Hosyond SSD1306
  128 × 64 OLED display. Lets the running stack show its own
  sensor readings in real time, closing the loop from "soldered
  bus" to "live demo."
- **OLED-only pressure-fit receptacles**: the OLED's 4 male pins
  (`GND, VCC, SCL, SDA` looking down at the display) plug into 4
  printed female pockets sized to grip a 0.64 mm pin by
  interference fit. The printed plastic IS the socket — no
  off-the-shelf header strip, no solder joint at the receptacle.
  Copper wire continues from the back of each receptacle into the
  same channel layout as Tier 1.
- Everything else stays Tier 1's mechanism: the ESP32, SCD41, and
  BH1750 still mount via inlay pockets and bare copper soldered
  through through-holes. The pressure-fit receptacle scope is
  bounded to four pin positions so the FDM tolerance dial-in is
  small and isolated.
- The netlist abstraction from Tier 1 (per-sensor PINOUT modules
  in `code/cad/src/vitamins/<sensor>_pinout.py`) absorbs the new
  device with no code change to the substrate or the routing —
  just an `oled_ssd1306_pinout.py` declaring the OLED's silkscreen
  pin order. This is the design's first real validation that
  "add a sensor = add a PINOUT dict."

Why second: minimal new mechanism (4 receptacles, not 27),
minimal new device (1 OLED, on the existing bus), maximum
demonstrative value (live readings from the substrate). Validates
that the netlist + collision-test infrastructure scales to
additional bus devices, and produces the first iteration of the
printed-receptacle geometry that Tier 3's multi-level harness
will reuse.

The parallel KiCad-PCB embodiment uses standard
`Connector_PinSocket_2.54mm` footprints from `kicad-packages3d`
for the OLED slot (`code/kicad/gen_spike_pcb.py` already supports
this style); the 3D-printed receptacle is the FDM-side analogue.

### Tier 3 — multi-level Z-stacked enclosure with bus harness

The first tier where the **Z axis carries meaning**. The substrate is
no longer a flat plate but a multi-floor structure: separate levels
for the MCU, the environmental sensors, and (optionally) the user
interface. The bus harness routes vertically between floors through
printed vias / wire-channels in the supporting walls.

- ESP32-C3 sits in its own compartment, walled off from the
  environmental sensors so MCU self-heating doesn't bias the SCD41
  temp/humidity readings.
- BH1750 (light) faces up through the lid; SCD41 (CO2 / temperature
  / humidity) faces down through the floor or a side vent so it
  samples outside-case air; OLED faces a viewing surface.
- The I2C bus runs as a vertical harness through wall-internal
  channels — same conductor mechanism as Tier 2 (pressure-fit
  receptacles + DuPont jumpers), now extended into the Z axis.
  Vias become real holes through floor/wall plates; receptacles can
  appear on any face of any level.
- Multi-level routing forces the netlist's `Bus` model to grow a
  notion of `level` so the test gate can sweep collisions per
  floor-plane and per inter-floor harness.

Why third: requires Tier 2's pressure-fit receptacle work to be
solid, plus genuine enclosure-geometry generation (multi-floor
shells, wall-internal channels, alignment between levels). Deployment
data from plant-caravan should also have surfaced concrete thermal
or sensor-orientation requirements by then.

## Order of urgency

1. **Tier 1 — done.** Substrate STL printable; netlist + collision
   gate in `code/cad/`; KiCad sibling regenerates identically.
   `docs/progress.md` records the artefacts.
2. **Tier 2 — next.** Pressure-fit female receptacles + OLED as a
   fourth bus device. The netlist abstraction was designed to make
   the extra device a no-code-change addition.
3. **Tier 3 — later.** Multi-level enclosure + Z-axis bus harness.
   Comes after Tier 2 ships, when deployment data has firmed up the
   thermal-isolation and sensor-orientation requirements.

## Relationship to docs/plan.md

`docs/plan.md` describes the compiler phases (KiCad ingest →
placement → routing → scoring → optimization). Each tier above is a
different output target of the same compiler, not a different
compiler:

- Tier 1 needs Phase 0–3 (ingest, vitamin registry, placement,
  greedy router) targeting a flat substrate with through-holes.
- Tier 2 reuses Phase 0–3, plus a per-pin receptacle-geometry
  generator and one extra bus device (OLED) plugged into the
  existing netlist abstraction.
- Tier 3 reuses Phase 0–3, plus multi-floor enclosure generation
  and a Z-aware extension of the routing/collision model so the
  bus harness can route between levels.

The KiCad-PCB output path (`code/kicad/gen_spike_pcb.py`) is a
parallel embodiment of *any* tier's netlist — at every tier the
3D-printed substrate and the etched-copper PCB share the same
single source of truth in `code/cad/src/netlist.py`.

If you're picking up this repo and want to ship something
plant-caravan can use, **Tier 1** is already done; the next
incremental step is Tier 2.
