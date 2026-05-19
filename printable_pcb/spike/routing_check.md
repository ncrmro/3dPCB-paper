# Routing check — `spike`

Validation gate against `printable_pcb/spike/substrate_plan.md`.
Coordinates are in mm. L1 = bottom face.

---

### Net: `+3V3`  layer assignment: L1 (no vias)

Trunk segments:
- (L1, -30.00, -11.92,   5.00, -11.92)   `s1` horizontal
- (L1,   5.00, -11.92,   5.00, -17.00)   `s2` vertical
- (L1,   5.00, -17.00,  20.00, -17.00)   `s3` horizontal

Foreign-pin collisions:
- `s1` (L1, y=-11.92, x ∈ [-30, 5]): **J1B.3 at (-12.22, -11.92)** (net `J1B_unused_3`) — collision.
- `s2` (L1, x=5, y ∈ [-17, -11.92]): no foreign-pin collisions on L1.
- `s3` (L1, y=-17, x ∈ [5, 20]): **J2.2 (7.54, -17) net `GND`**, **J2.3 (10.08, -17) net `SCL`**, **J2.4 (12.62, -17) net `SDA`** — 3 collisions.

Same-layer crossings (other nets' L1 segments):
- vs `GND.s1` (y=-14.46): `s1` parallel different y → disjoint; `s2` (vertical x=5) crosses `GND.s1` at **(5, -14.46)** → CROSSING.
- vs `GND.s3` (y=-17, x ∈ [7.54, 22.54]): `s3` overlaps for x ∈ **[7.54, 20]** → CROSSING.
- vs `SCL.s1` (y=-14.46, x ∈ [-12.22, 10.08]): `s2` (x=5) crosses at **(5, -14.46)** → CROSSING.
- vs `SCL.s3` (y=-17, x ∈ [10.08, 25.08]): `s3` overlaps for x ∈ **[10.08, 20]** → CROSSING.
- vs `SDA.s1` (y=-17, x ∈ [-12.22, 12.62]): `s3` overlaps for x ∈ **[5, 12.62]** → CROSSING.
- vs `SDA.s2` (y=-17, x ∈ [12.62, 27.62]): `s3` overlaps for x ∈ **[12.62, 20]** → CROSSING.

Pocket overlaps: no vias; no L2 segments — clear.

**Verdict: FAIL** — 4 foreign-pin collisions, 6 same-layer crossings with three other nets.

---

### Net: `GND`  layer assignment: L1 (no vias)

Trunk segments:
- (L1, -30.00, -14.46,   7.54, -14.46)   `s1` horizontal
- (L1,   7.54, -14.46,   7.54, -17.00)   `s2` vertical
- (L1,   7.54, -17.00,  22.54, -17.00)   `s3` horizontal

Foreign-pin collisions:
- `s1` (L1, y=-14.46, x ∈ [-30, 7.54]): **J1B.2 at (-12.22, -14.46)** (net `SCL`) — collision.
- `s2` (L1, x=7.54, y ∈ [-17, -14.46]): no foreign-pin collisions on L1.
- `s3` (L1, y=-17, x ∈ [7.54, 22.54]): **J2.3 (10.08, -17) net `SCL`**, **J2.4 (12.62, -17) net `SDA`**, **J3.1 (20.00, -17) net `+3V3`** — 3 collisions.

Same-layer crossings:
- vs `+3V3.s2` (vertical x=5, y ∈ [-17, -11.92]): intersects at **(5, -14.46)** if x=5 ∈ [-30, 7.54] — yes → CROSSING (mirror of the `+3V3` row).
- vs `+3V3.s3` (y=-17, x ∈ [5, 20]): `s3` overlaps for x ∈ **[7.54, 20]** → CROSSING.
- vs `SCL.s1` (y=-14.46, x ∈ [-12.22, 10.08]): `s1` overlaps for x ∈ **[-12.22, 7.54]** → CROSSING.
- vs `SCL.s2` (vertical x=10.08, y ∈ [-17, -14.46]): does x=10.08 ∈ `s1`'s x-range [-30, 7.54]? No → disjoint with `s1`. With `s3` (y=-17): intersects at (10.08, -17) = J2.3 (already counted as foreign-pin collision on `s3`).
- vs `SCL.s3` (y=-17, x ∈ [10.08, 25.08]): `s3` overlaps for x ∈ **[10.08, 22.54]** → CROSSING.
- vs `SDA.s1` (y=-17, x ∈ [-12.22, 12.62]): `s3` overlaps for x ∈ **[7.54, 12.62]** → CROSSING.
- vs `SDA.s2` (y=-17, x ∈ [12.62, 27.62]): `s3` overlaps for x ∈ **[12.62, 22.54]** → CROSSING.

Pocket overlaps: no vias; no L2 — clear.

**Verdict: FAIL** — 4 foreign-pin collisions, 6 same-layer crossings.

---

### Net: `SCL`  layer assignment: L1 (no vias)

Trunk segments:
- (L1, -12.22, -14.46,  10.08, -14.46)   `s1` horizontal
- (L1,  10.08, -14.46,  10.08, -17.00)   `s2` vertical
- (L1,  10.08, -17.00,  25.08, -17.00)   `s3` horizontal

Foreign-pin collisions:
- `s1` (L1, y=-14.46, x ∈ [-12.22, 10.08]): no foreign-pin collisions on L1 (J1B.2 is endpoint; no other holes at y=-14.46 in this x range — J1A.2 is at x=-30 outside the range).
- `s2` (L1, x=10.08, y ∈ [-17, -14.46]): no foreign-pin collisions on L1.
- `s3` (L1, y=-17, x ∈ [10.08, 25.08]): **J2.4 (12.62, -17) net `SDA`**, **J3.1 (20.00, -17) net `+3V3`**, **J3.2 (22.54, -17) net `GND`** — 3 collisions.

Same-layer crossings:
- vs `+3V3.s2` (vertical x=5): x=5 ∉ `s1`'s [-12.22, 10.08] — wait, 5 IS in [-12.22, 10.08]. y=-14.46 ∈ `+3V3.s2`'s [-17, -11.92] → CROSSING at **(5, -14.46)** (mirror of earlier).
- vs `+3V3.s3` (y=-17, x ∈ [5, 20]): `s3` overlaps for x ∈ **[10.08, 20]** → CROSSING.
- vs `GND.s1` (y=-14.46, x ∈ [-30, 7.54]): `s1` overlaps for x ∈ **[-12.22, 7.54]** → CROSSING.
- vs `GND.s3` (y=-17, x ∈ [7.54, 22.54]): `s3` overlaps for x ∈ **[10.08, 22.54]** → CROSSING.
- vs `SDA.s1` (y=-17, x ∈ [-12.22, 12.62]): `s3` overlaps for x ∈ **[10.08, 12.62]** → CROSSING.
- vs `SDA.s2` (y=-17, x ∈ [12.62, 27.62]): `s3` overlaps for x ∈ **[12.62, 25.08]** → CROSSING.

Pocket overlaps: no vias; no L2 — clear.

**Verdict: FAIL** — 3 foreign-pin collisions, 6 same-layer crossings.

---

### Net: `SDA`  layer assignment: L1 (no vias)

Trunk segments:
- (L1, -12.22, -17.00,  12.62, -17.00)   `s1` horizontal
- (L1,  12.62, -17.00,  27.62, -17.00)   `s2` horizontal

Foreign-pin collisions:
- `s1` (L1, y=-17, x ∈ [-12.22, 12.62]): **J2.1 (5.00, -17) net `+3V3`**, **J2.2 (7.54, -17) net `GND`**, **J2.3 (10.08, -17) net `SCL`** — 3 collisions.
- `s2` (L1, y=-17, x ∈ [12.62, 27.62]): **J3.1 (20.00, -17) net `+3V3`**, **J3.2 (22.54, -17) net `GND`**, **J3.3 (25.08, -17) net `SCL`** — 3 collisions.

Same-layer crossings:
- vs `+3V3.s2` (vertical x=5, y ∈ [-17, -11.92]): `s1` (y=-17) touches at endpoint **(5, -17)** — same point also flagged above as J2.1 foreign collision.
- vs `+3V3.s3` (y=-17, x ∈ [5, 20]): `s1` overlaps x ∈ **[5, 12.62]**, `s2` overlaps x ∈ **[12.62, 20]** → CROSSING.
- vs `GND.s3` (y=-17, x ∈ [7.54, 22.54]): `s1` overlaps x ∈ **[7.54, 12.62]**, `s2` overlaps x ∈ **[12.62, 22.54]** → CROSSING.
- vs `SCL.s3` (y=-17, x ∈ [10.08, 25.08]): `s1` overlaps x ∈ **[10.08, 12.62]**, `s2` overlaps x ∈ **[12.62, 25.08]** → CROSSING.

Pocket overlaps: no vias; no L2 — clear.

**Verdict: FAIL** — 6 foreign-pin collisions, 6 same-layer crossings.

---

### Singleton nets (one endpoint, no copper run)

The following nets have a single endpoint and therefore zero trunk segments. No foreign-pin, same-layer, or pocket checks apply — the through-hole is mechanical only.

`J3_ADDR`, `J1A_unused_1`, `J1A_unused_4`, `J1A_unused_5`, `J1A_unused_6`, `J1A_unused_7`, `J1A_unused_8`, `J1A_unused_9`, `J1B_unused_3`, `J1B_unused_4`, `J1B_unused_5`, `J1B_unused_6`, `J1B_unused_7`, `J1B_unused_8`, `J1B_unused_9`.

**Verdict: PASS (vacuously)** — no segments to check.

---

## Overall verdict: FAIL

4 routed nets, 4 FAIL: `+3V3`, `GND`, `SCL`, `SDA`. 15 singleton nets vacuously pass.

Summary of failures:
- **Foreign-pin collisions**: 14 distinct cases across the four bus nets. Two of these directly reproduce the original `Tier1Substrate` bug — `+3V3.s1` piercing J1B.3 at (-12.22, -11.92) and `GND.s1` piercing J1B.2 at (-12.22, -14.46). The remaining 12 are J1A/J1B trunks running along the southern row y=-17 and colliding with J2/J3 pins of every other net.
- **Same-layer crossings**: every pair of the four routed nets crosses or overlaps on L1, most along the y=-17 bottom row.

## Suggested remediations

- **Option A (recommended, matches plant-caravan PR #38)**: keep SCD41 trunks on L1, branch BH1750 via L2 crossover above the module pockets (Zone 3, y > +4.5). For nets sourced from J1A (the inner ESP32 column relative to J1B), break the L1 east-bound trunk with a via-pair that hops over the J1B column on L2 at a staggered y to avoid same-layer collisions.
- **Option B**: re-place the ESP32 module to the west edge of the board so J1A is the outer column with a free escape lane east, and J1B sits next to the sensors with no obstructions. This removes the J1A→J1B crossing problem entirely.
- **Option C**: dedicate each bus net to its own y on L1 (no shared southern row). Reach each sensor pad via a short north-going stub from the unique bus y. This requires the sensors to expose their pads on the *north* edge (rotation 90°) rather than the south edge, which means re-rotating both sensor footprints relative to the existing KiCad spike — changes the sibling parity claim.

Decision required: pick A, B, or C (or a combination) and call `mcp__deepwork__go_to_step` with `step_id="draft_plan"` to re-draft.
