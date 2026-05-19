# Routing check — `spike_v2`

Validation against `printable_pcb/spike_v2/substrate_plan.md`.
Source of truth: the inline YAML routing blocks (parsed below).
Coordinates in mm. L1 = bottom face, L2 = top face.

ESP32 pocket bounds (for via-clearance checks):
`x ∈ [-32.45, -9.65], y ∈ [-18.0, +4.3]`. SCD41 and BH1750 pockets
are entirely south of y ≈ -3. **All vias are at y ∈ {+6, +9, +12, +15}**
which is north of every pocket footprint.

---

### Net: `+3V3`  layer assignment: L1+L2, vias at (-29, +6), (5, +6), (20, +6)

Trunk segments (from YAML):
- (L1, -30.0, -11.92, -29.0, -11.92)  east stub
- (L1, -29.0, -11.92, -29.0,   6.0)   north
- (L2, -29.0,   6.0,    5.0,   6.0)   L2 east to SCD41 col
- (L1,   5.0,   6.0,    5.0, -17.0)   L1 south to J2.1
- (L2,   5.0,   6.0,   20.0,   6.0)   L2 east branch
- (L1,  20.0,   6.0,   20.0, -17.0)   L1 south to J3.1

Foreign-pin collisions:
- east-stub L1 y=-11.92, x∈[-30, -29]: no foreign-pin collisions on L1.
- north L1 x=-29: no foreign-pin collisions on L1.
- L2 east y=+6, x∈[-29, 5]: no foreign-pin collisions on L2.
- south L1 x=5: no foreign-pin collisions on L1 (J2.1 at (5, -17) is endpoint).
- L2 east-branch y=+6, x∈[5, 20]: no foreign-pin collisions on L2.
- south L1 x=20: no foreign-pin collisions on L1 (J3.1 endpoint).

Same-layer crossings: VCC's L1 verticals at x ∈ {-29, 5, 20}; VCC's L1 east-stub at y=-11.92. Cross-checked against GND, SCL, SDA L1 segments — all disjoint (different x for north legs, different y for east stubs, no x overlap on south legs). VCC's L2 east legs at y=+6; GND L2 at y=+9, SCL L2 at y=+12, SDA L2 at y=+15 — all distinct y, disjoint.

Pocket overlaps: vias at (-29, 6), (5, 6), (20, 6) — all y=+6 ≥ +4.3+clearance, OUTSIDE ESP32 pocket. SCD41 & BH1750 pockets south of y≈-3. All vias clear.

**Verdict: PASS**

---

### Net: `GND`  layer assignment: L1+L2, vias at (-27, +9), (7.54, +9), (22.54, +9)

Trunk segments:
- (L1, -30.0, -14.46, -27.0, -14.46)
- (L1, -27.0, -14.46, -27.0,   9.0)
- (L2, -27.0,   9.0,    7.54,  9.0)
- (L1,   7.54,  9.0,    7.54,-17.0)
- (L2,   7.54,  9.0,   22.54,  9.0)
- (L1,  22.54,  9.0,   22.54,-17.0)

Foreign-pin collisions:
- east-stub L1 y=-14.46, x∈[-30, -27]: J1A.2 at (-30,-14.46) is endpoint; J1B.2 at (-12.22,-14.46) NOT in x range. No foreign on L1.
- north L1 x=-27: no foreign.
- L2 east y=+9, x∈[-27, 7.54]: no foreign.
- south L1 x=7.54: J2.2 endpoint. No foreign.
- L2 east-branch y=+9, x∈[7.54, 22.54]: no foreign.
- south L1 x=22.54: J3.2 endpoint. No foreign.

Same-layer crossings: disjoint with all other nets (north x=-27 unique; south x's 7.54/22.54 unique; L2 east y=+9 unique).

Pocket overlaps: vias all at y=+9, well above all pocket north edges. Clear.

**Verdict: PASS**

---

### Net: `SCL`  layer assignment: L1+L2, vias at (-11, +12), (10.08, +12), (25.08, +12)

Trunk segments:
- (L1, -12.22, -14.46, -11.0, -14.46)
- (L1, -11.0, -14.46,  -11.0,  12.0)
- (L2, -11.0,  12.0,   10.08, 12.0)
- (L1,  10.08, 12.0,   10.08,-17.0)
- (L2,  10.08, 12.0,   25.08, 12.0)
- (L1,  25.08, 12.0,   25.08,-17.0)

Foreign-pin collisions:
- east-stub L1 y=-14.46, x∈[-12.22, -11]: J1B.2 at (-12.22,-14.46) endpoint. No foreign.
- north L1 x=-11: no foreign (J1B column at x=-12.22 ≠ -11; J1A at -30 ≠ -11; sensors at y=-17 not at x=-11).
- L2 east y=+12, x∈[-11, 10.08]: no foreign.
- south L1 x=10.08: J2.3 endpoint. No foreign.
- L2 east-branch y=+12, x∈[10.08, 25.08]: no foreign.
- south L1 x=25.08: J3.3 endpoint. No foreign.

Same-layer crossings:
- SCL.north L1 (x=-11, y∈[-14.46, 12]) vs SDA.east-stub L1 (y=-17, x∈[-12.22, -9]): x=-11 ∈ [-12.22,-9], y=-17 ∈ [-14.46, 12]? No (y=-17 < -14.46). Disjoint.
- All others: distinct x's / y's per net. Disjoint.

Pocket overlaps: vias at y=+12, clear.

**Verdict: PASS**

---

### Net: `SDA`  layer assignment: L1+L2, vias at (12.62, +15), (27.62, +15)

Trunk segments:
- (L1, -12.22, -17.0, -9.0, -17.0)
- (L1, -9.0, -17.0,   -9.0,  15.0)
- (L1, -9.0,  15.0,   12.62, 15.0)
- (L1,  12.62, 15.0,  12.62,-17.0)
- (L2,  12.62, 15.0,  27.62, 15.0)
- (L1,  27.62, 15.0,  27.62,-17.0)

Foreign-pin collisions:
- east-stub L1 y=-17, x∈[-12.22, -9]: J1B.1 at (-12.22,-17) endpoint. Sensor pins start at J2.1 (5,-17) — x=5 ∉ [-12.22,-9]. No foreign.
- north L1 x=-9: no foreign (no pin column at x=-9).
- east-corridor L1 y=+15, x∈[-9, 12.62]: no foreign (no pin at y=+15).
- south L1 x=12.62: J2.4 endpoint. No foreign.
- L2 east-branch y=+15, x∈[12.62, 27.62]: no foreign.
- south L1 x=27.62: J3.4 endpoint. No foreign.

Same-layer crossings:
- SDA.east-corridor L1 (y=+15, x∈[-9, 12.62]) vs all L1 verticals: VCC.south x=5 (y∈[-17,+6]): y=+15 ∉. Disjoint. GND.south x=7.54 (y∈[-17,+9]): y=+15 ∉. Disjoint. SCL.south x=10.08 (y∈[-17,+12]): y=+15 ∉. Disjoint. SCL.north x=-11 (y∈[-14.46,+12]): x=-11 ∉ [-9, 12.62]. Disjoint.
- SDA.north L1 (x=-9) vs all L1 horizontals: VCC.east-stub y=-11.92 (x∈[-30,-29]): x=-9 ∉. Disjoint. GND.east-stub y=-14.46 (x∈[-30,-27]): x=-9 ∉. Disjoint. SCL.east-stub y=-14.46 (x∈[-12.22,-11]): x=-9 ∉. Disjoint.
- All other pairs: distinct.

Pocket overlaps: vias at y=+15, clear.

**Verdict: PASS**

---

### Singleton nets

`J3_ADDR`, `J1A_unused_*`, `J1B_unused_*` — single endpoint each, no trunk segments. Vacuously **PASS**.

---

## Overall verdict: PASS

All four routed nets pass every check. 11 vias placed, all at y ≥ +6 (clear of every module pocket footprint). 0 foreign-pin collisions. 0 same-layer crossings. 0 pocket overlaps. Plan is mechanically translatable into `code/cad/src/vitamins/substrate.py`'s `Point2D / WireSegment / Via / SignalPath` data model.
