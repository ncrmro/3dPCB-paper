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

### Tier 1 — flat single-layer substrate (plant-caravan target)

The minimal viable artifact and the urgent one.

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

### Tier 2 — compartmentalized enclosure

Builds on Tier 1's wire technique inside a thermally partitioned case.

- ESP32-C3 sits in its own compartment, walled off from the
  environmental sensors so MCU self-heating doesn't bias readings.
- BH1750 (light) faces up through the lid.
- SCD41 (CO2 / temperature / humidity) faces down through the floor or
  a side vent, sampling outside-case air.
- Wire channels routed through compartment walls; same bare-copper
  through-hole conductor technique as Tier 1.

Why second: requires Tier 1's routing to work, plus enclosure
geometry generation (see `code/cad/src/vitamins/` for the existing
shape primitives; plant-caravan PR #28 has the parallel design in
`hardware/cad/src/parts/enclosure.py`).

### Tier 3 — socketed substrate with KiCad parity

Reworkable build: the substrate (or the parallel fabricated PCB)
accepts each COTS module's existing pre-soldered male header strip.

- Female 0.1″ sockets integrated into the substrate (3D-printed
  pockets sized for socket-housing inlay) or routed in the KiCad PCB
  (`Connector_PinSocket_2.54mm` from kicad-packages3d, already wired
  in `code/kicad/gen_spike_pcb.py`).
- Same netlist as Tiers 1–2; different physical embodiment.
- Modules pull out. Useful when a sensor dies or a clone arrives with
  a different pinout.

Why third: most infrastructure (female sockets, packages3d, GLB
rendering, KiCad → GLB pipeline) is already landed. What remains is
the parallel 3D-printed-socket variant and the agent-facing "build
this tier" CLI.

## Order of urgency

1. **Tier 1 — now.** plant-caravan PR #28 is in flight; the substrate
   needs to be printable end-of-week.
2. **Tier 3 — already underway.** Female PinSocket footprints landed;
   `spike.glb` shows raised sockets. Remaining work is the printed
   socket variant + agent CLI.
3. **Tier 2 — after Tier 1 is in plant-caravan's hands.** Needs
   thermal-isolation requirements firmed up from real deployment data.

## Relationship to docs/plan.md

`docs/plan.md` describes the compiler phases (KiCad ingest →
placement → routing → scoring → optimization). Each tier above is a
different output target of the same compiler, not a different
compiler:

- Tier 1 needs Phase 0–3 (ingest, vitamin registry, placement,
  greedy router) targeting a flat substrate.
- Tier 2 reuses Phase 0–3 plus enclosure-geometry generation.
- Tier 3 reuses Phase 0 plus the KiCad-PCB output path already
  working in `code/kicad/gen_spike_pcb.py`.

If you're picking up this repo and want to ship something
plant-caravan can use, work toward **Tier 1** through `plan.md`'s
Phase 0–3. The other tiers are downstream once that lands.
