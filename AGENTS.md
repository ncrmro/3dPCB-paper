# AGENTS.md

## Project

3dPCB-paper: a research paper and spike CAD for a parametric 3D-printed
substrate that unifies PCB layout, harness routing, and enclosure into one
declarative artifact. Demonstration target: ESP32-C3 Supermini + SCD41
(CO2/temp/humidity) + BH1750 (light) over I2C (SDA=GPIO5, SCL=GPIO6).

## Layout

- `docs/paper.md` — the paper itself; the canonical statement of the
  methodology, claims, and validation protocol.
- `cad/` — spike CAD package (own `flake.nix`, `pyproject.toml`, `.venv`).
  - `src/vitamins/` — COTS module models (`esp32.py`, `sensors.py`),
    copied verbatim from `ncrmro/plant-caravan/hardware/cad/src/vitamins/`
    so changes can be diffed back upstream.
  - `src/registry.py` — part registration for AnchorSCAD shapes / raw SCAD.
  - `bin/render` — renders registered parts to `.scad` under `cad/build/`.
- `.deepwork/` — DeepWork workflow metadata.

## Dev shell

Each subproject with code has its own `flake.nix`. Enter via `nix develop`
or rely on direnv. Never run installers the devshell already provides
(e.g. no `playwright install`, no `pip install` outside `uv`).

```bash
cd cad
nix develop -c ./bin/render   # writes .scad files into cad/build/
```

Python is 3.13, managed by `uv`. Dependencies: `anchorscad-core`,
`pythonopenscad`, `numpy`. `cadeng` (gallery server) and a wrapped
headless OpenSCAD come from the `cadeng` flake input.

## Conventions

- Conventional Commits: `type(scope): subject`. One logical change per commit.
- Prose: succinct, sentence-case headings, ISO 8601 dates.
- Comments explain **why**, not what. Use `SECURITY:`, `CRITICAL:`, `TODO:`
  prefixes when they apply.
- Search with `rg --type` and inspect JSON/YAML with `jq`/`yq` rather than
  reading whole files.

## Vitamin parity

`cad/src/vitamins/*.py` are mirrored from plant-caravan. When updating a
vitamin, preserve the file structure so a future `diff` against the
upstream copy stays meaningful. The I2C pinout (SDA=GPIO5, SCL=GPIO6,
3V3, GND) mirrors plant-caravan so firmware ports are drop-in.

## Prior art

The substrate idea is a generalization of plant-caravan PR
[ncrmro/plant-caravan#28](https://github.com/ncrmro/plant-caravan/pull/28)
`feat(hardware): sensor mounts` (open). That PR is the earliest
working example of the methodology and the source of:

- The `Scd41Breakout` and `Bh1750Breakout` vitamins copied into
  `cad/src/vitamins/sensors.py`, including the measured PCB / header /
  sub-PCB / sensor-dome dimensions.
- The `Esp32C3Assembly` carrier + supermini stack in `cad/src/vitamins/esp32.py`.
- The earliest cut of channel routing: a `wire_channel_width: 6.0,
  wire_channel_depth: 2.0` vertical slot in the interior wall (DuPont
  connector clearance) — the direct ancestor of the paper's
  printed-channel router.
- The lid-recess + frame sandwich pattern that holds modules by
  pressure-fit shelves and lets headers pass through frame holes —
  the predecessor to the paper's pressure-fit inlay model.

When citing prior art in `docs/paper.md`, reference this PR directly.
When the upstream PR moves (lands, splits, or evolves), update this
file and re-diff `cad/src/vitamins/` against the new upstream paths.

## Paper edits

`docs/paper.md` is the authoritative artifact. When CAD work changes a
load-bearing claim (tolerance numbers, yield targets, routing limits),
update the paper in the same change.
