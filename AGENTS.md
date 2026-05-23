# AGENTS.md

## Project

3dPCB-paper: a research paper and spike CAD for a parametric 3D-printed
substrate that unifies PCB layout, harness routing, and enclosure into one
declarative artifact. Demonstration target: ESP32-C3 Supermini + SCD41
(CO2/temp/humidity) + BH1750 (light) over I2C (SDA=GPIO5, SCL=GPIO6).

## Layout

- `docs/paper.md` — the paper itself; the canonical statement of the
  methodology, claims, and validation protocol.
- `docs/plan.md` — phased plan for the spike CAD compiler.
- `docs/plants/` — weekly plan snapshots (e.g. `W20-demoable-paper.md`).
- `docs/kicad/` — KiCad workflow notes (e.g. `images.md`: rendering boards).
- `code/` — all source code. Houses the uv + bun workspace roots.
  - `code/kicad/` — canonical electrical design (`spike.kicad_sch` +
    `spike.kicad_pcb`) plus a `placements/` directory of 3D placement
    sidecars (YAML keyed by reference designator). Own `flake.nix`.
  - `code/cad/` — substrate compiler (own `flake.nix`,
    `pyproject.toml`, `.venv`).
    - `src/vitamins/` — COTS module 3D models (`esp32.py`, `sensors.py`),
      copied verbatim from `ncrmro/plant-caravan/hardware/cad/src/vitamins/`
      so changes can be diffed back upstream.
    - `src/registry.py` — part registration for AnchorSCAD shapes / raw SCAD.
    - `bin/render` — renders registered parts to `.scad` under `code/cad/build/`.
  - `code/web/` — bun + astro gallery (planned; see
    `docs/plants/W20-demoable-paper.md`).
- `.deepwork/` — DeepWork workflow metadata.

## Workflow: KiCad-first

Electrical designs live in KiCad. The substrate is a **physical embodiment**
of a KiCad design — a fabricated PCB is a sibling embodiment of the same
netlist, not a successor. Designers work in KiCad, then author a YAML
placement sidecar (per reference designator: position, orientation,
pinned-ness) that the substrate compiler consumes alongside the KiCad
netlist and footprint pad coordinates.

Inspiration from `circuit-synth/circuit-synth` (pin-by-name component
access, KiCad symbols as the canonical pad source) is taken without
adopting it as a runtime dependency. The compiler owns its data model.

## Dev shell

Default developer loop is a single `process-compose` invocation from
the repo root. It starts the Astro gallery, stages GLBs once, and
watches `code/cad/` and `code/kicad/` for source changes so the
rendered `.glb`/`.stl` artefacts in `code/web/public/models/` stay
in lockstep with the source. **Always boot this before editing CAD or
KiCad files** — without it, the gallery artefacts drift out of date
relative to the source and any "I changed the part, why does it still
look like the old one" confusion follows.

```bash
nix develop -c process-compose up
```

Processes wired up by `process-compose.yaml`:

- **prebuild** — one-shot: stages GLBs into `code/web/public/models/`.
- **web** — `astro dev` on a random high port (logged at start).
- **watch-cad** — re-runs the AnchorSCAD render pipeline on `*.py`
  changes under `code/cad/src/`.
- **watch-kicad** — re-runs the KiCad render pipeline on
  `*.kicad_pcb` / `*.kicad_sch` changes under `code/kicad/`.

Each subproject also has its own `flake.nix` for direct use when the
orchestrator is overkill (one-shot render, CI, debugging a single
pipeline):

```bash
cd code/cad   && nix develop -c ./bin/render               # AnchorSCAD parts
cd code/kicad && nix develop -c ./bin/render-board spike.kicad_pcb
cd code/web   && nix develop -c bun install && nix develop -c bun run dev
```

Python is 3.13, managed by `uv`. Dependencies: `anchorscad-core`,
`pythonopenscad`, `numpy`. `cadeng` (gallery server) and a wrapped
headless OpenSCAD come from the `cadeng` flake input. Never run
installers the devshell already provides (no `playwright install`,
no `pip install` outside `uv`).

## Conventions

- Conventional Commits: `type(scope): subject`. One logical change per commit.
- Prose: succinct, sentence-case headings, ISO 8601 dates.
- Comments explain **why**, not what. Use `SECURITY:`, `CRITICAL:`, `TODO:`
  prefixes when they apply.
- Search with `rg --type` and inspect JSON/YAML with `jq`/`yq` rather than
  reading whole files.

## Vitamin parity

`code/cad/src/vitamins/*.py` are mirrored from plant-caravan. When
updating a vitamin, preserve the file structure so a future `diff`
against the upstream copy stays meaningful. The I2C pinout (SDA=GPIO5,
SCL=GPIO6, 3V3, GND) mirrors plant-caravan so firmware ports are
drop-in.

## Prior art

The substrate idea is a generalization of plant-caravan PR
[ncrmro/plant-caravan#28](https://github.com/ncrmro/plant-caravan/pull/28)
`feat(hardware): sensor mounts` (open). That PR is the earliest
working example of the methodology and the source of:

- The `Scd41Breakout` and `Bh1750Breakout` vitamins copied into
  `code/cad/src/vitamins/sensors.py`, including the measured PCB / header /
  sub-PCB / sensor-dome dimensions.
- The `Esp32C3Assembly` carrier + supermini stack in `code/cad/src/vitamins/esp32.py`.
- The earliest cut of channel routing: a `wire_channel_width: 6.0,
  wire_channel_depth: 2.0` vertical slot in the interior wall (DuPont
  connector clearance) — the direct ancestor of the paper's
  printed-channel router.
- The lid-recess + frame sandwich pattern that holds modules by
  pressure-fit shelves and lets headers pass through frame holes —
  the predecessor to the paper's pressure-fit inlay model.

When citing prior art in `docs/paper.md`, reference this PR directly.
When the upstream PR moves (lands, splits, or evolves), update this
file and re-diff `code/cad/src/vitamins/` against the new upstream
paths.

## Paper edits

`docs/paper.md` is the authoritative artifact. When CAD work changes a
load-bearing claim (tolerance numbers, yield targets, routing limits),
update the paper in the same change.
