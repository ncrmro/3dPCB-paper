# Substrate plan — `spike_v2`

Re-design of spike substrate to fix the v1 routing collisions.
All J1A net trunks now use a north-detour around the J1B pin column;
all BH1750 branches use L2 crossbars at staggered y values above all
module pockets. Vias placed at corridor y values clear of every pocket.

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

## 3. Net list

Unchanged from v1.

| Net | Endpoints |
| --- | --- |
| `+3V3` | `J1A.3, J2.1, J3.1` |
| `GND`  | `J1A.2, J2.2, J3.2` |
| `SCL`  | `J1B.2, J2.3, J3.3` |
| `SDA`  | `J1B.1, J2.4, J3.4` |
| `J3_ADDR` | `J3.5` |
| `J1A_unused_{1,4..9}` | one J1A pin each |
| `J1B_unused_{3..9}`   | one J1B pin each |

## 4. Pocket layout

(Unchanged from v1; bounds carried from the `Dimensions` classes.)

- ESP32: centre (-21.11, -6.84), approx 18.3 × 22.3 mm, depth ≈ 1.6
- SCD41: centre (8.81, scd_cy), depth = scd41.pcb_thickness
- BH1750: centre (25.08, bh_cy), depth = bh1750.pcb_thickness

ESP32 pocket bounds (used for via-clearance checks): x ∈ [-32.45, -9.65], y ∈ [-18.0, +4.3] approximately. **All vias placed at y ≥ +6** to clear the north edge cleanly.

## 5. Through-hole list

Unchanged from v1 (27 holes total). See `printable_pcb/spike/substrate_plan.md` section 5 for the full table.

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

```yaml
net: vcc
segments:
  - { layer: 1, start: [-30.0, -11.92], end: [-29.0, -11.92] }   # east stub
  - { layer: 1, start: [-29.0, -11.92], end: [-29.0,   6.0] }    # north
  - { layer: 2, start: [-29.0,   6.0],  end: [  5.0,   6.0] }    # L2 east to SCD41 col
  - { layer: 1, start: [  5.0,   6.0],  end: [  5.0, -17.0] }    # south to J2.1
  - { layer: 2, start: [  5.0,   6.0],  end: [ 20.0,   6.0] }    # L2 east branch
  - { layer: 1, start: [ 20.0,   6.0],  end: [ 20.0, -17.0] }    # south to J3.1
vias:
  - { position: [-29.0, 6.0], diameter: 1.5 }
  - { position: [  5.0, 6.0], diameter: 1.5 }
  - { position: [ 20.0, 6.0], diameter: 1.5 }
```

### `GND` — L1+L2 with 3 vias

```yaml
net: gnd
segments:
  - { layer: 1, start: [-30.0, -14.46], end: [-27.0, -14.46] }
  - { layer: 1, start: [-27.0, -14.46], end: [-27.0,   9.0] }
  - { layer: 2, start: [-27.0,   9.0],  end: [  7.54,  9.0] }
  - { layer: 1, start: [  7.54,  9.0],  end: [  7.54, -17.0] }
  - { layer: 2, start: [  7.54,  9.0],  end: [ 22.54,  9.0] }
  - { layer: 1, start: [ 22.54,  9.0],  end: [ 22.54, -17.0] }
vias:
  - { position: [-27.0, 9.0], diameter: 1.5 }
  - { position: [  7.54, 9.0], diameter: 1.5 }
  - { position: [ 22.54, 9.0], diameter: 1.5 }
```

### `SCL` — L1+L2 with 3 vias

```yaml
net: scl
segments:
  - { layer: 1, start: [-12.22, -14.46], end: [-11.0, -14.46] }
  - { layer: 1, start: [-11.0, -14.46],  end: [-11.0,  12.0] }
  - { layer: 2, start: [-11.0,  12.0],   end: [ 10.08, 12.0] }
  - { layer: 1, start: [ 10.08, 12.0],   end: [ 10.08, -17.0] }
  - { layer: 2, start: [ 10.08, 12.0],   end: [ 25.08, 12.0] }
  - { layer: 1, start: [ 25.08, 12.0],   end: [ 25.08, -17.0] }
vias:
  - { position: [-11.0, 12.0], diameter: 1.5 }
  - { position: [ 10.08, 12.0], diameter: 1.5 }
  - { position: [ 25.08, 12.0], diameter: 1.5 }
```

### `SDA` — L1-only with 2 vias (top corridor)

```yaml
net: sda
segments:
  - { layer: 1, start: [-12.22, -17.0], end: [-9.0, -17.0] }
  - { layer: 1, start: [-9.0, -17.0],   end: [-9.0,  15.0] }
  - { layer: 1, start: [-9.0,  15.0],   end: [ 12.62, 15.0] }
  - { layer: 1, start: [ 12.62, 15.0],  end: [ 12.62, -17.0] }
  - { layer: 2, start: [ 12.62, 15.0],  end: [ 27.62, 15.0] }
  - { layer: 1, start: [ 27.62, 15.0],  end: [ 27.62, -17.0] }
vias:
  - { position: [ 12.62, 15.0], diameter: 1.5 }
  - { position: [ 27.62, 15.0], diameter: 1.5 }
```

## 7. Layer rationale

- **VCC / GND on L2 east legs**: the L1 alternative would cross GND/SCL/SDA north legs on L1 at the same point.
- **SCL on L2 east leg**: would otherwise cross SDA.north at (-9, +12) on L1.
- **SDA on L1 east leg**: SDA's corridor y = +15 is above every other net's L1 vertical extent, so the L1 east leg is collision-free.
- **All vias at y ≥ +6**: ESP32 pocket north edge ≈ +4.3, SCD41/BH1750 pockets fully south of +0, so y ≥ +6 puts every via OUTSIDE every pocket footprint.

## 8. Risks-to-validate

- Trunk-through-foreign-pin: verify each segment's bbox is clear of every non-endpoint pin hole on its layer. Specifically confirm the J1A east stubs and J1B east stubs don't cross any foreign pin on the way east.
- Same-layer parallel: VCC.L2 / GND.L2 / SCL.L2 / SDA.L2 east legs are at distinct y's (+6, +9, +12, +15) — confirm no overlap. L1 north legs at distinct x's (VCC -29, GND -27, SCL -11, SDA -9) — confirm. South legs at unique sensor-pin x — confirm.
- Via-in-pocket: each via's (x, y) must satisfy y ≥ +6 (clear of ESP32 pocket north edge at +4.3). Confirm all 11 vias.
- Edge-of-board escape: J1A nets escape via north detour; J1B nets escape via short east stub. Both verified at coords above.

## 9. Open questions

- Channel cross-section, via diameter, hole diameter, pocket clearance: defaults applied per brief.
- SDA east stub at y=-17 from (-12.22, -17) to (-9, -17) stays on the southern row but is short (3.22 mm); confirms no foreign pins fall in this x range at y=-17 (they don't — closest sensor pin J2.1 is at x=5).
