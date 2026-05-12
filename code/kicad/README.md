# code/kicad — canonical electrical design

This is the **Phase 0** KiCad project from `docs/plan.md`. It is the
authoritative netlist source for the substrate compiler. A fabricated
PCB and a 3D-printed substrate are sibling physical embodiments of the
same design.

## Status

Scaffolded. Schematic and PCB files not yet authored.

Asset sources (symbols, footprints, 3D models) are catalogued in
`RESEARCH.md`. Mounting decision: **female 0.1″ headers** for all three
breakouts (reworkable; tolerates clone pinout variation).

## Target circuit

Three COTS modules on a shared I2C bus:

| Ref | Module | I2C addr | Header |
|---|---|---|---|
| U1 | ESP32-C3 Supermini | (host) | 2 × 1×9 castellated (or female header rows) |
| U2 | Sensirion SCD41 breakout | 0x62 | 1×4 (VCC, GND, SCL, SDA — verify per vendor) |
| U3 | Rohm BH1750 / GY-302 | 0x23 | 1×5 (VCC, GND, SCL, SDA, ADDR) |

Net list: `SDA`, `SCL`, `+3V3`, `GND`. Four nets.

Supermini I2C pin assignment: **GPIO5 = SDA, GPIO6 = SCL**, mirroring
the firmware target inherited from `ncrmro/plant-caravan` so any
firmware port is drop-in. Note this differs from the `Loufe`
reference project, which uses GPIO3/4.

## How to start

1. Enter the KiCad dev shell from the `code/kicad/` directory:
   ```bash
   cd code/kicad
   nix develop      # provides `kicad` + `kicad-cli`
   ```
2. Launch KiCad and create a new project here: `code/kicad/spike.kicad_pro`.
3. Import the symbols and footprints listed in `RESEARCH.md`. Per the
   license flags, **do not commit** SnapEDA or UltraLibrarian `.kicad_sym` /
   `.kicad_mod` files into this repo — reference part IDs in the BOM
   instead.
4. Wire the four nets, run ERC, lay out the PCB with female headers,
   run DRC, export Gerbers.
5. Commit `spike.kicad_pro`, `spike.kicad_sch`, `spike.kicad_pcb`, and
   any custom library files whose licenses permit it.

## Directory layout

```
code/kicad/
├── README.md           # this file
├── RESEARCH.md         # symbol/footprint source catalogue + license flags
├── BOM.md              # populated once part numbers are pinned
├── flake.nix
├── spike.kicad_pro     # (not yet authored)
├── spike.kicad_sch     # (not yet authored)
├── spike.kicad_pcb     # (not yet authored)
└── placements/         # 3D placement sidecars for the substrate compiler
                        # (consumed by Phase 2; empty for now)
```

## Phase 2 placement sidecars

The `placements/` directory will hold YAML files keyed by reference
designator describing 3D position + orientation for each module. See
`docs/plan.md` Phase 2. Each sidecar is one variant of the orientation
gallery — they all consume the same `spike.kicad_*` netlist.

## License plan

Target: **CERN-OHL-S** (or MIT for the Python compiler code, CERN-OHL-S
for the hardware). Achievable per `RESEARCH.md` if we:

- use KiCad-official `Sensor_Gas:SCD40-D-R2` (or a 1×4 connector) for the SCD41 breakout,
- use `usini/usini_kicad_sensors` for the BH1750 GY-302,
- reference the Supermini via SnapEDA part number in `BOM.md` rather than committing its files,
- or obtain explicit permissive licensing from `mrtnvgr/KiCad_ESP32-C3-SuperMini`.
