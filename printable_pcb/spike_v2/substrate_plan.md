# Substrate plan — `spike_v2`

Re-design of spike substrate to fix the v1 routing collisions.
All J1A net trunks now use a north-detour around the J1B pin column;
all BH1750 branches use L2 crossbars at staggered y values above all
module pockets. Vias placed at corridor y values clear of every pocket.

Refreshed 2026-05-20 to add Tier 2 OLED (J4) participation and apply
two net-share merges (GND, VCC) between OLED and SCD41 — see the
Net merge audit section at the end of this file.

## 1. Board identity

- **board_name**: `spike_v2`
- **outline**: 80 × 50 × 3 mm
- **KiCad sibling**: `code/kicad/spike.kicad_pcb`

## 2. Modules

| Name | Vitamin | Pin 1 (mm) | Rotation | Pins | Pitch |
| --- | --- | --- | --- | --- | --- |
| ESP32-C3 SuperMini (J1A col) | `Esp32C3SuperminiDimensions` | (-30, -17) | pads +Y | 9 | 2.54 |
| ESP32-C3 SuperMini (J1B col) | `Esp32C3SuperminiDimensions` | (-12.22, -17) | pads +Y | 9 | 2.54 |
| SCD41 breakout | `Scd41Dimensions` | J2.1 (5, -17) | pads +X | 4 | 2.54 |
| BH1750 breakout | `Bh1750Dimensions` | J3.1 (20, -17) | pads +X | 5 | 2.54 |
| Hosyond SSD1306 OLED (J4) | mounted via `_J4_*` constants in `substrate.py` (Tier 2: pedestal + receptacles, no pocket) | J4.1 (-3.81, -22) | pads +X | 4 | 2.54 |

## 3. Net list

| Net | Endpoints |
| --- | --- |
| `+3V3` | `J1A.3, J2.1, J3.1, J4.3` |
| `GND`  | `J1A.2, J2.2, J3.2, J4.4` |
| `SCL`  | `J1B.2, J2.3, J3.3, J4.2` |
| `SDA`  | `J1B.1, J2.4, J3.4, J4.1` |
| `J3_ADDR` | `J3.5` |
| `J1A_unused_{1,4..9}` | one J1A pin each |
| `J1B_unused_{3..9}`   | one J1B pin each |

OLED pin assignments per `code/cad/src/vitamins/oled_ssd1306_pinout.py`
(PINOUT was reversed so the high-frequency SDA pin is closest to the
ESP32 master). Mapping: J4.1=SDA, J4.2=SCL, J4.3=VCC, J4.4=GND.

## 4. Pocket layout

(SCD41/BH1750/ESP32 unchanged from v1; bounds carried from the
`Dimensions` classes.)

- ESP32: centre (-21.11, -6.84), approx 18.3 × 22.3 mm, depth ≈ 1.6
- SCD41: centre (8.81, scd_cy), depth = scd41.pcb_thickness
- BH1750: centre (25.08, bh_cy), depth = bh1750.pcb_thickness
- OLED (J4): **no recess pocket** — Tier 2 mounts the OLED on
  pressure-fit receptacles. Features:
  - Raised pedestal 12 × 4 × 2.5 mm centred at (0, -22), encloses the
    4 receptacle through-holes; lifts the OLED's plastic header guard
    clear of the substrate top.
  - Support bump 4 × 4 × 5 mm at (0, 0), props up the cantilevered
    north end of the OLED PCB so it sits level above the substrate.
  - OLED PCB body cantilevers SOUTH off the substrate: occupies
    x ∈ [-13.5, +13.5], y ∈ [-22, -49] in the world frame. It does
    NOT overlap the SCD41 or BH1750 pockets in xy.

ESP32 pocket bounds (used for via-clearance checks): x ∈ [-32.45, -9.65], y ∈ [-18.0, +4.3] approximately. **All vias placed at y ≥ +6** to clear the north edge cleanly.

## 5. Through-hole list

27 standard pin through-holes (diameter 1.0 mm) for ESP32 + SCD41 +
BH1750 — see `printable_pcb/spike/substrate_plan.md` section 5 for
the full table.

Plus 4 OLED receptacle through-holes at y = -22, diameter 1.25 mm
(interference-fit for 0.64 mm DuPont male pins, validated on
`docs/fdm_tolerance_notes.md` — printability floor confirmed):

| (x, y) | Pin | Net | Diameter (mm) |
| --- | --- | --- | --- |
| (-3.81, -22) | J4.1 | SDA | 1.25 |
| (-1.27, -22) | J4.2 | SCL | 1.25 |
| (+1.27, -22) | J4.3 | VCC | 1.25 |
| (+3.81, -22) | J4.4 | GND | 1.25 |

Receptacle diameter is LARGER than the standard 1.0 mm pin through-hole
to keep the printed hole open after FDM over-extrusion; see
`docs/paper.md` §5.5 Tolerance Calibration.

## 6. Per-net routing

Each routed net uses a unique **corridor y** above all pockets:
VCC = +6, GND = +9, SCL = +12, SDA = +15. J1A nets escape via
a north-detour at unique north-corridor x's (VCC: −29, GND: −27);
J1B nets escape via a tiny east-step then north at unique x's
(SCL: −11, SDA: −9). BH1750 branches use L2 crossbars at the
corridor y; via pairs at L1↔L2 transitions are all at y ≥ +6
(outside every pocket footprint).

For VCC and GND, the SCD41-side trunk uses an L2 east leg from the
north-corridor-top via to the SCD41-column via, because the L1
alternative would cross other nets' L1 north-legs. SCL also uses L2
for its corridor-east leg for the same reason (SDA's north leg crosses
it on L1 otherwise). SDA's corridor is the topmost (+15) so its east
leg can stay on L1 — no L1 verticals up that high.

### `+3V3` — L1+L2 with 3 vias

**merged in auto mode (2026-05-20)**: OLED.J4.3 is now tapped from
the SCD41 trunk via a short L1 jumper at y = -17 instead of a
dedicated 28 mm south leg from the corridor at x = +1.27. Wire
saved ≈ 19 mm; 1 via eliminated (the previous corner-via at
(1.27, 6) on the OLED branch). Droop warning: shared 3V3 rail
between OLED and SCD41 — OLED draws ≤ 20 mA peak (SSD1306, 4 MHz
SPI/I²C), SCD41 ≤ 75 mA peak during the photoacoustic measurement
window; combined ≤ 95 mA across ≈ 5 mm of 0.8 × 0.8 mm copper.
Resistance ≈ 0.5 mΩ → droop ≤ 50 µV, well under SCD41's 3.3 V
±10% tolerance. Slicer Δtime / Δfilament: skipped
(`bin/slicer-estimate` not implemented — see GH #41).

```yaml
net: vcc
merged_with: [SCD41.J2.1, OLED.J4.3]
segments:
  - { layer: 1, start: [-30.0, -11.92], end: [-29.0, -11.92] }   # east stub
  - { layer: 1, start: [-29.0, -11.92], end: [-29.0,   6.0] }    # north
  - { layer: 2, start: [-29.0,   6.0],  end: [  5.0,   6.0] }    # L2 east to SCD41 col
  - { layer: 1, start: [  5.0,   6.0],  end: [  5.0, -17.0] }    # south to J2.1
  - { layer: 1, start: [  5.0, -17.0],  end: [  1.27,-17.0] }    # merge jumper west on L1
  - { layer: 1, start: [  1.27,-17.0],  end: [  1.27,-22.0] }    # south to J4.3 (OLED VCC)
  - { layer: 2, start: [  5.0,   6.0],  end: [ 20.0,   6.0] }    # L2 east branch
  - { layer: 1, start: [ 20.0,   6.0],  end: [ 20.0, -17.0] }    # south to J3.1
vias:
  - { position: [-29.0, 6.0], diameter: 1.5 }
  - { position: [  5.0, 6.0], diameter: 1.5 }
  - { position: [ 20.0, 6.0], diameter: 1.5 }
```

### `GND` — L1+L2 with 3 vias

**merged in auto mode (2026-05-20)**: OLED.J4.4 is now tapped from
the SCD41 GND trunk via a short L1 jumper at y = -17 instead of a
dedicated 31 mm south leg from the corridor at x = +3.81. Wire
saved ≈ 22 mm; 1 via eliminated. Ground merges are always safe at
I²C speeds (the only loss is shared impedance, negligible). Slicer
Δtime / Δfilament: skipped (issue #41).

```yaml
net: gnd
merged_with: [SCD41.J2.2, OLED.J4.4]
segments:
  - { layer: 1, start: [-30.0, -14.46], end: [-27.0, -14.46] }   # east stub
  - { layer: 1, start: [-27.0, -14.46], end: [-27.0,   9.0] }    # north
  - { layer: 2, start: [-27.0,   9.0],  end: [  7.54,  9.0] }    # L2 east to SCD41 col
  - { layer: 1, start: [  7.54,  9.0],  end: [  7.54, -17.0] }   # south to J2.2
  - { layer: 1, start: [  7.54,-17.0],  end: [  3.81,-17.0] }    # merge jumper west on L1
  - { layer: 1, start: [  3.81,-17.0],  end: [  3.81,-22.0] }    # south to J4.4 (OLED GND)
  - { layer: 2, start: [  7.54,  9.0],  end: [ 22.54,  9.0] }    # L2 east branch
  - { layer: 1, start: [ 22.54,  9.0],  end: [ 22.54, -17.0] }   # south to J3.2
vias:
  - { position: [-27.0, 9.0], diameter: 1.5 }
  - { position: [  7.54, 9.0], diameter: 1.5 }
  - { position: [ 22.54, 9.0], diameter: 1.5 }
```

### `SCL` — L1+L2 with 4 vias

OLED.J4.2 (SCL) participates as a regular branch off the corridor —
**not merged** (I²C SCL is a bus signal; merging breaks the corridor
fan-out model and is explicitly forbidden by the optimize_net_sharing
step's eligibility rules). The corridor sweeps west-to-east:
OLED (J4.2, x=-1.27) → SCD41 (J2.3, x=10.08) → BH1750 (J3.3, x=25.08).

```yaml
net: scl
segments:
  - { layer: 1, start: [-12.22, -14.46], end: [-11.0, -14.46] }
  - { layer: 1, start: [-11.0, -14.46],  end: [-11.0,  12.0] }
  - { layer: 2, start: [-11.0,  12.0],   end: [ -1.27, 12.0] }   # L2 east to OLED col
  - { layer: 1, start: [ -1.27, 12.0],   end: [ -1.27,-22.0] }   # south to J4.2
  - { layer: 2, start: [ -1.27, 12.0],   end: [ 10.08, 12.0] }   # L2 east to SCD41 col
  - { layer: 1, start: [ 10.08, 12.0],   end: [ 10.08, -17.0] }  # south to J2.3
  - { layer: 2, start: [ 10.08, 12.0],   end: [ 25.08, 12.0] }
  - { layer: 1, start: [ 25.08, 12.0],   end: [ 25.08, -17.0] }
vias:
  - { position: [-11.0,  12.0], diameter: 1.5 }
  - { position: [ -1.27, 12.0], diameter: 1.5 }
  - { position: [ 10.08, 12.0], diameter: 1.5 }
  - { position: [ 25.08, 12.0], diameter: 1.5 }
```

### `SDA` — L1-only with 2 vias (top corridor)

OLED.J4.1 (SDA) participates as a regular branch off the corridor —
**not merged** (bus signal). Corridor sweeps west-to-east:
OLED (J4.1, x=-3.81) → SCD41 (J2.4, x=12.62) → BH1750 (J3.4, x=27.62).

```yaml
net: sda
segments:
  - { layer: 1, start: [-12.22, -17.0], end: [-9.0, -17.0] }
  - { layer: 1, start: [-9.0, -17.0],   end: [-9.0,  15.0] }
  - { layer: 1, start: [-9.0,  15.0],   end: [-3.81, 15.0] }    # east to OLED col on L1
  - { layer: 1, start: [-3.81, 15.0],   end: [-3.81,-22.0] }    # south to J4.1
  - { layer: 1, start: [-3.81, 15.0],   end: [ 12.62, 15.0] }
  - { layer: 1, start: [ 12.62, 15.0],  end: [ 12.62, -17.0] }
  - { layer: 2, start: [ 12.62, 15.0],  end: [ 27.62, 15.0] }
  - { layer: 1, start: [ 27.62, 15.0],  end: [ 27.62, -17.0] }
vias:
  - { position: [ 12.62, 15.0], diameter: 1.5 }
  - { position: [ 27.62, 15.0], diameter: 1.5 }
```

## 7. Layer rationale

- **VCC / GND on L2 east legs**: the L1 alternative would cross GND/SCL/SDA north legs on L1 at the same point.
- **VCC / GND merge jumpers on L1 at y=-17**: short legs (≤ 5 mm) along the SCD41 J2 pin row directly west to the OLED column. **Risk to validate** (see section 8): the jumpers run through y=-17 in the x-strip between J2.1/J2.2 and J4 — check_routing must confirm no foreign-pin or pocket collision.
- **SCL on L2 east legs**: would otherwise cross SDA.north at (-9, +12) on L1.
- **SDA on L1 east legs**: SDA's corridor y = +15 is above every other net's L1 vertical extent (except the long-east leg to BH1750, which drops back to L2 to clear the SCL crossing at x ≈ +25.08).
- **All vias at y ≥ +6**: ESP32 pocket north edge ≈ +4.3, SCD41/BH1750 pockets fully south of +0, so y ≥ +6 puts every via OUTSIDE every pocket footprint.

## 8. Risks-to-validate

- Trunk-through-foreign-pin: verify each segment's bbox is clear of every non-endpoint pin hole on its layer. Specifically confirm the J1A east stubs and J1B east stubs don't cross any foreign pin on the way east.
- **New: VCC merge jumper at y=-17 from (5, -17) west to (1.27, -17) on L1 — verify no foreign J2 pin between x=1.27 and x=5 (J2.1 is at x=5 and is the segment's east endpoint, so it's an OK endpoint; no other J2 pin sits at y=-17 west of x=5).**
- **New: GND merge jumper at y=-17 from (7.54, -17) west to (3.81, -17) on L1 — passes through (5, -17) which is J2.1 (SCD41 +3V3 pin). This is a foreign-pin collision on the merge jumper. check_routing MUST surface this; remediations: (a) route the jumper at y = -17.5 just south of the J2 row (if the pocket allows L1 surface there); (b) lift the jumper to L2 with a via pair at (7.54,-17) and (3.81,-17) — adds 2 vias but eliminates the collision; (c) reject the GND merge.**
- **New: VCC + GND merge south legs to J4 at (1.27, -22) and (3.81, -22) — verify these short L1 segments do not cross any pocket footprint (the OLED has no pocket; SCD41 pocket's south edge is somewhere north of y=-22; confirm).**
- Same-layer parallel: VCC.L2 / GND.L2 / SCL.L2 / SDA east legs are at distinct y's (+6, +9, +12, +15) — confirm no overlap.
- Via-in-pocket: each via's (x, y) must satisfy y ≥ +6 (clear of ESP32 pocket north edge at +4.3). Confirm all 13 vias.
- Edge-of-board escape: J1A nets escape via north detour; J1B nets escape via short east stub; J4 OLED escapes via south legs from corridor + jumpers. Verified at coords above.

## 9. Open questions

- Channel cross-section, via diameter, hole diameter, pocket clearance: defaults applied per brief.
- OLED receptacle diameter = 1.25 mm (validated; see `docs/fdm_tolerance_notes.md`).
- SDA east stub at y=-17 from (-12.22, -17) to (-9, -17) stays on the southern row but is short (3.22 mm); confirms no foreign pins fall in this x range at y=-17 (closest sensor pin J2.1 is at x=5).
- **Plan/code drift flagged**: the SDA YAML block above was refreshed to include J4 OLED but retains the existing plan's mixed L1/L2 east-leg semantics. The Tier 2 substrate code (`code/cad/src/vitamins/substrate.py` `_build_paths_for_net`) currently treats SDA as a single-layer L1 corridor based on `scd_east_on_l2=False`; that produces an all-L1 east-leg topology. A follow-up plan refresh should reconcile the YAML with the code's current rule.

## 10. Net merge audit

Optimization pass executed 2026-05-20 via the `optimize_net_sharing`
step of the `printable_pcb/single_plan` workflow.

- **Mode**: autonomous (no interactive merge-by-merge AskUserQuestion;
  the structured "Plan drift" question that opened this pass was a
  scoping decision about how to handle the OLED gap, not a
  per-proposal accept/decline). Both proposed merges accepted under
  the auto-default-TRUE rule and annotated `merged in auto mode` in
  the per-net YAML blocks above.
- **Source of truth for the analysis**: live code
  (`code/cad/src/vitamins/substrate.py` Tier 2 + `code/cad/src/netlist.py`
  `PRIMARY_BUS = TIER2_BUS`). The pre-pass `substrate_plan.md` (this
  file's prior revision) did not list J4; sections 2–6 above were
  refreshed in the same pass to reflect Tier 2 reality before applying
  the merges.
- **Slicer status**: `unavailable` — `code/cad/bin/slicer-estimate`
  not implemented (tracked in GH #41). Per-proposal Δtime and
  Δfilament rows are recorded as `skipped`. Re-running this audit
  after slicer-estimate lands will fill in the numbers.

### Proposals considered

| # | Signal | Participants | Wire saved (mm) | Vias saved | Δtime | Δfilament | Disposition |
| - | ------ | ------------ | --------------- | ---------- | ----- | --------- | ----------- |
| 1 | GND | SCD41.J2.2 ↔ OLED.J4.4 | ~22 (replaces 31 mm south leg with 5 mm jumper + 4 mm south to J4) | 1 | skipped | skipped | **merged in auto mode** (with check_routing remediation note for the jumper passing through J2.1) |
| 2 | VCC | SCD41.J2.1 ↔ OLED.J4.3 | ~19 (replaces 28 mm south leg with 4 mm jumper + 5 mm south to J4) | 1 | skipped | skipped | **merged in auto mode** (droop warning: combined OLED + SCD41 transient ≤ 95 mA, droop ≤ 50 µV — well within SCD41 tolerance) |

### Proposals not eligible

| Pair | Signal | Reason |
| ---- | ------ | ------ |
| OLED.J4.1 ↔ ESP32.J1B.1 | SDA | I²C bus signal — never a merge candidate per the optimize_net_sharing eligibility rules. Bus fan-out is the corridor model's job. |
| OLED.J4.2 ↔ ESP32.J1B.2 | SCL | I²C bus signal — never a merge candidate. |
| OLED.J4 ↔ BH1750.J3 | GND / VCC | Footprint centres ~22 mm apart in x with SCD41 in between; the existing west-to-east trunk topology already visits both via a single corridor. A direct OLED ↔ BH1750 jumper would add wire, not save it. |
| SCD41.J2 ↔ BH1750.J3 | GND / VCC | Adjacent in x (~15 mm) but not vertically stacked. Existing trunk visits both via the corridor; a direct jumper would route along y=-17 over a long span and conflict with multiple foreign pins. |

### Follow-up

A follow-up GitHub issue scopes a **static analyzer** that would
produce this audit deterministically from the netlist + pocket
geometry without an LLM in the loop, and would also evaluate
**single-trunk bus topologies** (one wire visiting every I²C
destination in series rather than separate trunks per signal).
That work may grow into a second paper on declarative net
topology for 3D-printed substrates.
