# Module back conductivity — z-axis clearance between wire and PCB back

This note records what's known about the conductive vs. non-conductive
regions of each module PCB's BACK face (the face that sits against
the substrate pocket floor). The substrate routes bare copper wire
in surface channels — when the channel sits at the L2 z-band
(z ∈ [+0.7, +1.5]), the wire and the back of any PCB occupying the
same xy at the L2 band are at overlapping z, so an exposed conductor
on the PCB back would short to the wire.

## z-geometry context

- Substrate body: z ∈ [-1.5, +1.5] (3 mm thick).
- L1 channel z-band: [-1.5, -0.7] (bottom face, cut into substrate
  from below).
- L2 channel z-band: [+0.7, +1.5] (top face, cut into substrate
  from above).
- Pocket cavity z-band: [+0.7, +1.5] (cut into substrate from above
  for module PCBs to seat into).
- Module PCB back face: z = +0.7 (rests on pocket floor).

Conclusion: an L2 channel at the same xy as a pocket cavity puts
the wire in the same z range as the PCB back. The two physically
overlap.

## Current voxel-test behavior (conservative)

`code/cad/tests/test_substrate_routing.py` rasterizes every module's
PCB xy footprint at the L2 z-band as a "board" owner (None-signal).
Any L2 wire voxel whose xy lands inside a PCB footprint is flagged
as "board contact" — failure mode #5 in
`.deepwork/jobs/printable_pcb/job.yml`.

This is conservative: it treats every square millimeter of every
PCB back as if it were exposed conductor. In practice most PCB
backs are largely silkscreened or covered by soldermask, with only
specific regions (pin pads, vias, exposed traces) actually
conductive. The conservative model rules out routing options that
would actually be safe.

## Per-module conductivity audit

> Status of these notes: based on **user observation** of the
> validation hardware (2026-05). Pending photo capture and explicit
> region labelling. Re-audit per board if the hardware changes.

### SCD41 (Adafruit STEMMA QT 5190) — pocket J2

- **Back face**: mostly covered by silkscreen / soldermask. The
  J2 header pads (pins 1–4 at the front edge) ARE conductive on
  the back (through-hole barrels). Most of the rest of the back is
  not exposed copper.
- **Implication**: L2 channels in J2 pocket xy at the pin row
  (y ≈ -17, near the front edge) collide with the pin barrels — a
  real conductive collision. L2 channels in the rest of the
  pocket xy (further north of the pin row) would be safer than the
  current conservative check suggests, but should still be avoided
  until the silkscreen coverage is photo-confirmed.

### BH1750 (GY-302) — pocket J3

- **Back face**: similar to SCD41 — most of the back is
  silkscreened, with the J3 header pad barrels (pins 1–5) at the
  front edge being the conductive exception.
- **Implication**: same as SCD41 — pin barrels at y ≈ -17 are
  exposed; rest is conservative.

### ESP32-C3 SuperMini — pocket J1A/J1B

- **Back face**: mostly silkscreened. The 18 castellated/through-
  hole pads along the two side rows (J1A at the west edge, J1B
  ~17.78 mm east) are conductive. The reset and boot switches and
  the USB-C connector occupy areas on the top face only — back is
  free of those.
- **Implication**: an L2 channel that runs INSIDE the ESP32 pocket
  but BETWEEN the J1A and J1B columns (x ∈ [-30+ε, -12.22-ε]) is
  on a silkscreen-covered region of the back. Currently the
  conservative check rules this out.

### OLED (Hosyond SSD1306 128×64) — pocket J4

- **Back face**: NOT silkscreened — the SSD1306 PCB has exposed
  copper traces and component leads on its back.
- **Raised mounting**: the OLED PCB sits on a 5 mm pedestal above
  the substrate top (see `code/cad/src/vitamins/substrate.py`
  `oled_pedestal_height`). The OLED PCB back sits at z ≈ +9 mm —
  ~7.5 mm above the L2 z-band ceiling at z = +1.5. L2 channels
  passing UNDER the OLED PCB don't make contact regardless of
  the back's conductivity.
- **Implication**: `_module_pcb_footprints()` in substrate.py
  already excludes the OLED from the forbidden-xy list because
  the OLED sits clear of the L2 z-band. The voxel test correctly
  permits L2 channels under the OLED footprint.

## Future refinement: per-region conductivity map

The voxel test could be refined to carve out non-conductive
regions of each PCB back as allowed L2 xy. Implementation sketch:

1. Each `Tier1Substrate._module_pcb_footprints()` entry returns
   not just `(name, cx, cy, hw, hl)` but `(name, cx, cy, hw, hl,
   conductive_regions)` where `conductive_regions` is a list of
   sub-rectangles or sub-circles known to be exposed copper.
2. The voxel rasterizer marks only `conductive_regions` as
   forbidden, leaving the rest of the pocket xy free for L2
   routing.
3. Per-module conductivity comes from a photo audit and is
   recorded next to the dimensions in each module's vitamin
   file.

This is deferred until at least one routing decision is actually
blocked by the conservative check on a non-conductive region.
The current bus topology routes well within the existing
constraints, so the refinement isn't on the critical path.

## Confidence and re-audit triggers

- **High confidence**: OLED raised-pedestal clearance — verified
  by geometry, not by photo.
- **Medium confidence** (user statement, not photographed):
  ESP32, SCD41, BH1750 back surface silkscreen coverage.
- **Re-audit triggers**:
  - New module added to a substrate.
  - Vendor changes a board layout (e.g. Adafruit revs the SCD41
    breakout).
  - Voxel test ever needs to be relaxed for a specific routing
    option — re-confirm the relevant module's conductivity first.
