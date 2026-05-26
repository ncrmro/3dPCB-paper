# 3dPCB-paper

**3dPCB-paper turns a few lines of YAML — "an ESP32, an SCD41, a
BH1750, all on I²C" — into a 3D-printable substrate with the bus
auto-routed and a 3D-printable enclosure designed around it.** The
goal is a succinct declarative format for iterating on PCBs that are
*cast as plastic* rather than etched on copper: edit the spec,
re-render, ship a new board in an hour, drop it into the printed
housing the same day.

Devices are first-class primitives — microcontrollers and sensors
that expose standard pin groups (I²C, UART, GPIO, power). Buses
connect them. The router places wires to minimise length, vias, and
same-layer crossings while respecting printable wall floors.
Everything geometric (board outline, pockets, channels, holes) is
*derived* from the device + bus declaration. Nothing about the
geometry — including the OLED display, sensor breakouts, or ESP32
carrier — is hardcoded in Python beyond the physical dimensions of
the parts themselves.

A fabricated PCB and a 3D-printed substrate are sibling physical
embodiments of the same netlist — not successors.

Demonstration target: ESP32-C3 Supermini + Sensirion SCD41 + Rohm
BH1750 on a shared I²C bus (SDA=GPIO5, SCL=GPIO6).

## Authoring a new board

```yaml
# code/cad/specs/i2c_starter.yaml
name: i2c_starter
levels:
  - name: base
    perimeter: { cx: 0, cy: 0, w: 68, h: 50 }
    z_start: -1.5
    z_end: 1.5
devices:
  - { name: u1,     device: esp32_c3_supermini, position: { x: -21, y: -7 } }
  - { name: scd41,  device: scd41,              position: { x:   9, y: -6 } }
  - { name: bh1750, device: bh1750,             position: { x:  25, y: -8 } }
  - name: oled
    device: oled_ssd1306
    position: { x: 0, y: 10 }
    header: { connector: female_1x4_2.54 }
buses:
  - { kind: i2c, name: primary, master: u1, slaves: [scd41, bh1750, oled] }
```

Drop a YAML in `code/cad/specs/`, run `nix develop ./code/cad -c bash
code/web/bin/prebuild-cad`, open the gallery — the new board renders
with the bus auto-routed.

## Layout

```
3dPCB-paper/
├── docs/
│   ├── paper.md                          # the paper itself
│   ├── plan.md                           # phased spike plan
│   ├── plants/W20-demoable-paper.md      # this week's restructure
│   └── kicad/images.md                   # rendering boards to PNG
└── code/                                 # uv + bun workspace roots
    ├── kicad/                            # canonical electrical design
    ├── cad/                              # AnchorSCAD substrate compiler
    └── web/                              # bun + astro gallery
```

See [`AGENTS.md`](AGENTS.md) for the contributor-facing detail
(workflow, vitamin parity, prior art).

## Quick start

```bash
nix develop -c process-compose up
```

Boots the Astro gallery, stages GLBs once, and watches `code/cad/`
and `code/kicad/` for source changes. See
[`AGENTS.md` § Dev shell](AGENTS.md#dev-shell) for the per-process
breakdown and per-subproject `nix develop` fallbacks.

Top-level workspaces:

- `cd code && uv sync` — resolves the uv (Python) workspace.
- `cd code && bun install` — resolves the bun (JS) workspace.

## Paper

The paper draft is in [`docs/paper.md`](docs/paper.md). When CAD
work changes a load-bearing claim (tolerance numbers, yield targets,
routing limits), update the paper in the same change.

## Prior art

The substrate idea generalizes
[ncrmro/plant-caravan#28](https://github.com/ncrmro/plant-caravan/pull/28)
`feat(hardware): sensor mounts`. The vitamins in
`code/cad/src/vitamins/` are mirrored from that PR so updates can be
diffed back upstream.

## License

TBD (target: CERN-OHL-S for hardware, MIT for the Python compiler).
See `code/kicad/RESEARCH.md` for the license plan that lets us ship
permissively.
