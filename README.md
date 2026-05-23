# 3dPCB-paper

A research paper and spike CAD for **parametric 3D-printed substrates
that unify PCB layout, harness routing, and enclosure into one
declarative artifact**. A fabricated PCB and a 3D-printed substrate
are sibling physical embodiments of the same KiCad netlist — not
successors.

Demonstration target: ESP32-C3 Supermini + Sensirion SCD41 + Rohm
BH1750 on a shared I2C bus (SDA=GPIO5, SCL=GPIO6).

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
