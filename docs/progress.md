# Progress

Date: 2026-05-19
Status: Tier 1 complete; Tier 2 scoped.

Companion to `docs/goals.md`: that doc describes the long-term
three-tier vision; this one tracks what has shipped and what is
next.

## Tier 1 — flat substrate with bare-copper wire routing — DONE

The minimal viable artifact from `docs/goals.md` is on disk and
verified.

### What shipped

- **`Tier1Substrate` AnchorSCAD vitamin**
  (`code/cad/src/vitamins/substrate.py`): single 80 × 50 × 3 mm flat
  plate carrying ESP32-C3 SuperMini + SCD41 + BH1750 in inlay
  pockets. 27 through-holes (one per module pin), three pockets,
  four I2C nets routed as channels.
- **Two-layer routing topology** ported from
  [`ncrmro/plant-caravan` PR #38](https://github.com/ncrmro/plant-caravan/pull/38)
  (branch-merge "approach G"), adapted so the trunks terminate at
  ESP32 pin holes on the substrate itself rather than a back-edge
  entry notch. J1A nets (VCC, GND) escape via a north detour around
  the J1B pin column; J1B nets (SCL, SDA) use a short east stub.
  All four nets use unique corridor y values (+6, +9, +12, +15 mm)
  and L2 east legs for branch crossbars; 11 vias total, all at
  y ≥ +6 (outside every pocket footprint).
- **`netlist.py` single source of truth**
  (`code/cad/src/netlist.py` + `vitamins/esp32_pinout.py` +
  `vitamins/sensors_pinout.py`): `I2cSignal` enum, `Pin` / `Bus` /
  `Net` / `RoutingHint` dataclasses, `PRIMARY_BUS` declaration,
  `NETS` table derived by signal lookup across each sensor's
  PINOUT. Both `code/cad/` (AnchorSCAD substrate) and `code/kicad/`
  (KiCad sibling PCB) consume the same data — the two embodiments
  cannot drift.
- **Connectivity + collision test suite**
  (`code/cad/tests/test_netlist.py`, 22 cases): per-net BFS
  asserting every declared endpoint is reachable from the master
  pin, per-pair AABB sweep over every segment / via / through-hole
  / pocket. Re-implements the deepwork `check_routing` gate
  programmatically against the actual generated geometry.
- **`bin/show-netlist`** prints the assembled bus → sensor harness
  in one screen so the wiring can be eyeballed without opening
  SCAD.
- **`netlist_audit.md`**: silkscreen-to-footprint audit for each
  breakout, recording the vendor source that justifies each
  PINOUT entry.
- **`deepwork_jobs/printable_pcb`** workflow:
  `single_plan` produces a substrate plan from a free-form brief,
  then a `check_routing` step validates routing collisions and
  loops back on FAIL. Used to design the v2 topology and re-render
  the production STL.

### Verification

- `cd code/cad && nix develop -c bin/test` — 22 / 22 passing.
- `cd code/cad && nix develop -c bin/show-netlist` — every routed
  net's master + both device endpoints marked `reachable`.
- STL + SCAD output is byte-identical pre/post the netlist
  refactor (MD5 hash-matched) — the source-of-truth move
  introduced no geometric drift.
- KiCad sibling `code/kicad/spike.kicad_pcb` regenerates
  identically from the refactored `gen_spike_pcb.py`.

### Artefacts on disk

- `code/cad/build/tier1_substrate.{scad,stl,glb,3mf}`
- `code/web/public/models/cad/tier1_substrate.glb` (gallery)
- `code/kicad/spike.kicad_pcb` (sibling PCB for the same nets)
- `printable_pcb/spike_v2/{substrate_plan.md,routing_check.md}`
  (deepwork workflow output)

## Tier 2 — Tier 1 substrate + OLED on pressure-fit receptacles — NEXT

Scope is intentionally narrow: **keep Tier 1 exactly as-is for the
ESP32 / SCD41 / BH1750, add one OLED display whose 4 male pins are
the *only* things in pressure-fit female receptacles.** Validates
two things at once with minimal new surface area:

1. Adding a fourth bus device via the netlist abstraction lands as
   a one-file change (new PINOUT module, no routing-code edits).
2. The 3D-printed receptacle mechanism for standard 2.54 mm pins
   prints and grips reliably — but only across 4 pin positions, so
   the FDM tolerance dial-in is small and isolated.

### What changes

- **Add an OLED display module** as the fourth I2C device on the
  primary bus so the substrate can SHOW current sensor readings
  (live demo of the integrated stack).
  - **Module**: Hosyond 0.96″ OLED I2C SSD1306 128 × 64 (white).
  - **Pin order** (looking DOWN at the display, header visible):
    `GND, VCC, SCL, SDA` (4 pins).
  - **⚠ Pin-order is *different* from BH1750 / SCD41** (which are
    `VCC, GND, ...`). The `netlist.py` abstraction handles this
    naturally — the OLED's `OLED_PINOUT` declares the actual
    silkscreen order, `NETS` assembly finds VCC/GND/SCL/SDA by
    signal lookup. First real-world validation of why the enum +
    PINOUT design was worth doing.
- **OLED-only pressure-fit receptacles** (4 of them): the OLED's
  male header presses into 4 printed female pockets sized for
  interference fit on a 0.64 mm pin. The printed plastic IS the
  socket — no metal contact at the receptacle, no off-the-shelf
  header strip. Copper wire continues from the back of each
  receptacle into the same channel layout the bare-wire-through-
  hole nets use.

### What does NOT change

- ESP32, SCD41, BH1750 mounting: still inlay pockets + bare copper
  wire soldered through through-holes. Same geometry as Tier 1.
- Routing topology: still the v2 north-detour + L2-branch design.
  The new OLED is just an additional device on each net's
  `device_pins` tuple; the substrate's routing code already loops
  over `device_pins` of arbitrary length.
- Plate outline + module placements for the three existing
  modules: unchanged. Only the OLED's footprint + 4 receptacle
  positions are new geometry.

### File-level shape (not yet implemented)

- `code/cad/src/vitamins/oled_ssd1306.py` — new
  `OledSsd1306Dimensions` class (PCB width × depth × thickness,
  display window cutout, header position relative to body).
- `code/cad/src/vitamins/oled_ssd1306_pinout.py` —
  ```python
  OLED_PINOUT = {
      1: Pin("J4", 1, signal=I2cSignal.GND),
      2: Pin("J4", 2, signal=I2cSignal.VCC),
      3: Pin("J4", 3, signal=I2cSignal.SCL),
      4: Pin("J4", 4, signal=I2cSignal.SDA),
  }
  ```
- `PRIMARY_BUS.devices` extends to `("SCD41", "BH1750", "OLED")`;
  every `Net.device_pins` becomes length-3. The substrate's
  routing iterator is already length-agnostic, so this just
  produces one more south-leg per net.
- `ReceptacleDimensions` data class (`pin_diameter`,
  `socket_id_diameter`, `wall_thickness`, `lip_depth`,
  `socket_depth`). The Tier 2 substrate uses receptacles ONLY at
  the OLED's 4 pin positions; the other 27 pin positions are
  unchanged through-holes.
- Tests extend cleanly: `test_endpoint_coverage` parametrised over
  the four bus signals asserts BFS reaches three devices, not
  two. The collision sweep needs no changes — same segment /
  via / pocket model plus an OLED-pocket bbox in the via /
  segment exclusion zones.

### Open questions for Tier 2

- Receptacle interference-fit tolerance vs FDM print resolution:
  test prints needed to dial in `socket_id_diameter` (probably
  ~0.55–0.6 mm for a 0.64 mm pin on a 0.2 mm-layer print). With
  only 4 receptacles per substrate, iterating tolerance is cheap.
- Receptacle depth vs substrate thickness: if the receptacle is
  blind (closed-bottomed), the wire on the underside still
  contacts the jumper pin tip; if through-bottomed, the user can
  trim from below. Open-bottomed is probably right so the
  back-side copper wire and the OLED pin make contact through the
  full substrate thickness.
- OLED display placement on the existing plate: pocket on the top
  face with a cutout for the visible-window area, ideally where
  the existing routing channels don't have to detour far to reach
  it. May warrant the OLED sitting north of the sensor row.

## Tier 3 — multi-level Z-stacked enclosure with bus harness — LATER

Per `docs/goals.md` §"Tier 3 — multi-level Z-stacked enclosure
with bus harness". First tier where the Z axis carries meaning:
multi-floor structure (MCU floor walled off from environmental
sensors floor, OLED on a viewing surface), bus harness routes
vertically through printed wall-internal channels.

Requires Tier 2's pressure-fit receptacle work to be solid, plus:
- Multi-floor shell generation (enclosure walls, floor plates,
  alignment between levels).
- Z-aware extension to the routing model: `Bus` grows a notion of
  `level`; the collision-test sweep extends to per-floor planes
  and inter-floor harness segments.
- Genuine enclosure CAD (top lid with BH1750 window, floor / side
  vent for SCD41 outside-air sampling, viewing surface for OLED).

Comes after Tier 2 ships, when deployment data has firmed up the
thermal-isolation and sensor-orientation requirements.

## Parallel embodiment — KiCad PCB sibling

At every tier the netlist supports a KiCad-PCB embodiment in
parallel. `code/kicad/gen_spike_pcb.py` already generates
`spike.kicad_pcb` from the same `vitamins/<sensor>_pinout.py`
modules the 3D-printed substrate consumes. The two embodiments
cannot drift — both pull pin labels from the same source. The PCB
path is incidentally how an integrator could reach a fab-house
build of the same design without 3D printing.

## Order of work

1. **Tier 2 next.** Pressure-fit receptacle geometry + OLED bus
   device addition. The netlist abstraction was designed to make
   the extra device a no-code-change addition (just a new PINOUT).
2. **Tier 3 later.** Multi-level enclosure with Z-axis bus harness.
   Comes after Tier 2 ships and after plant-caravan deployment data
   surfaces concrete thermal / orientation requirements.
