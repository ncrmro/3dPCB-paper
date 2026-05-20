# Vernacular

Canonical names, abbreviations, and shorthand used across the
repo. The terms here are referenced by code comments, doc strings,
commit messages, AGENTS.md hooks, and the paper. When in doubt,
prefer these spellings over ad-hoc ones.

## Coordinate-frame axis directions

The substrate uses a right-handed, Z-up Cartesian frame
(documented in `paper.md` §4.1). The six oriented half-axes have
short forms used in code identifiers, file paths, anchor names,
and short comments where the full `+X` / `-X` notation would be
clumsy:

| Long form | Short form | Direction in substrate frame |
| --- | --- | --- |
| `+X` | `xp` | substrate long axis, positive (right when viewed from above) |
| `-X` | `xn` | substrate long axis, negative (left when viewed from above) |
| `+Y` | `yp` | substrate short axis, positive (back / far edge) |
| `-Y` | `yn` | substrate short axis, negative (front / near edge — ESP32 USB-C side) |
| `+Z` | `zp` | perpendicular to substrate, positive (top routing face / lid side) |
| `-Z` | `zn` | perpendicular to substrate, positive (bottom routing face / channel side) |

Rules of use:

- `yp` / `yn` (and the other four) are the spelling in identifiers
  and short prose. Examples that are good: `xn_edge_clearance`,
  `# wire exits through the yp wall`, `J4_yn_edge`.
- `+Y` / `-Y` (and the other four) are the spelling in math,
  coordinate triples, and anywhere the sign matters as a
  multiplicative thing. Examples that are good:
  `pos = origin + 5 * Y`, `the +Z hemisphere of the inlay`.
- `Y+` and `Y-` (sign trailing) are **not** used in this repo —
  pick one of the two forms above.
- `up`, `north`, `front`, `left`, etc. are **avoided in code**
  because they're frame-relative and ambiguous (`up` depends on
  whether the substrate is viewed lid-up or bed-down; `front` is
  printer-relative). They're fine in user-facing prose where the
  context is clear, but library code and tests refer to the
  half-axis directly.

## Other repo-wide vernacular

- **Vitamin** — a 3D model of a COTS component that the
  substrate's geometry must clear (ESP32 SuperMini, SCD41 breakout,
  BH1750 breakout, OLED SSD1306). Lives under
  `code/cad/src/vitamins/`.
- **PINOUT** — a per-vitamin Python dict mapping 1-indexed pin
  number to `Pin(ref, number, signal, function)`. The single
  source of truth for which physical pin carries which bus signal.
  Always upper-case in identifiers (`J1A_PINOUT`, `OLED_PINOUT`).
- **Net** — one bus signal resolved across all participants
  (master + devices). Encoded as `netlist.Net`.
- **Trunk** — the main wire run of a bus signal from the master
  through the corridor; subdivided into per-device **branches**.
- **Corridor** — the east-west wire-channel lane assigned to a
  net's trunk on the substrate top or bottom face.
- **Receptacle** — a printed pressure-fit female pocket (vs. a
  normal clearance through-hole) sized so the printed plastic
  grips a male pin by interference fit. Tier 2 OLED only.
- **Pedestal** — a raised solid feature above the substrate top
  face that lifts the OLED's header (and therefore the OLED PCB)
  high enough to clear the SCD41 sensor IC.
- **Tier 1 / Tier 2 / Tier 3** — the three substrate variants from
  `goals.md`: bare-wire (Tier 1), pressure-fit receptacles
  + OLED (Tier 2), multi-level Z-stack (Tier 3).
- **Printability floor** — the minimum CAD hole diameter below
  which a given printer-and-slicer combo closes the hole
  entirely. Empirically ~0.8 mm light-through, ~1.25 mm pin-fit on
  the validation hardware. See `docs/fdm_tolerance_notes.md`.

## See also

- `docs/paper.md` §4.1 for the coordinate-frame definition.
- `code/cad/src/netlist.py` for the `Pin` / `Net` / `Bus`
  dataclasses these terms correspond to.
- `code/cad/src/netlist_audit.md` for the silkscreen-to-PINOUT
  audit using these conventions.
