# code/AGENTS.md

Source tree for the substrate compiler, gallery, and KiCad sidecars.
See the repo-root [`AGENTS.md`](../AGENTS.md) for the paper, dev-shell,
and conventions context.

## uv workspace layout

`code/` is the uv workspace root. `code/pyproject.toml` declares the
workspace + a single shared dev group (pytest, pytest-cov, ruff, ty);
the venv lives at `code/.venv/` and is anchored by `UV_PROJECT` from
`cad/flake.nix`'s shellHook. Without that anchor, a member-level
`uv sync` from `code/cad/` would miss the workspace dev tools and they'd
get evicted on every shell entry. The shellHook also passes
`--all-packages` so cross-member runtime deps (anchorscad, trimesh, …)
land in the shared venv.

Adding a new Python package: drop it under `code/` with its own
`pyproject.toml` and add the directory to `[tool.uv.workspace].members`
in `code/pyproject.toml`. It then shares the same venv + dev tools.

| Subdir | uv member? | Purpose |
|---|---|---|
| `cad/` | yes | Substrate compiler (Python 3.13, AnchorSCAD). |
| `kicad/` | no | Canonical KiCad design + render scripts. Own `flake.nix`. |
| `web/` | no | Bun + Astro gallery. Own `flake.nix`. |

## cad/ structure

Source under `code/cad/src/`:

- `board/` — declarative board model + builder.
  - `board.py` — `Board` dataclass: levels, perimeter, device list, buses.
  - `build.py` — `Board → CAD geometry` (calls into `router/` to get
    `SignalPath`s, then carves substrate).
  - `buses.py` — `Bus → Net` resolution; `bus_endpoint_xys()` is the
    single source of truth for which pin xys are bus endpoints (used
    by grid blocking and hole filtering).
  - `device_library.py` — device catalog (pin names, footprints).
  - `devices.py` — `DeviceInstance`, `Footprint`, `Pin`, geometry.
  - `loader.py` — YAML spec → `Board`.
  - `spec_discovery.py` — find specs on disk.
  - `cli_*.py` — entry points for `bin/render`, `bin/substrate-report`,
    `bin/score-routes`.
- `router/` — A* auto-router, split by concern (see **Router modules**).
- `vitamins/` — COTS module 3D models (`esp32.py`, `sensors.py`,
  `substrate.py`). Mirrored verbatim from
  `ncrmro/plant-caravan/hardware/cad/src/vitamins/` so diffs against
  upstream stay meaningful.
- `voxel_*.py` — legacy voxel pipeline kept only for `apply_chamfers`
  + collision math. New router code shouldn't reach in here; cleanup
  is deferred until the helpers are either rewired or removed.
- `registry.py` — part registration for `bin/render`.

## Router modules

`router/` was a single 1086-line `autoroute.py` until 2026-05; it's
now split into focused modules. Imports flow one way: `autoroute.py`
(orchestration) calls primitives, never the reverse.

| Module | Responsibility |
|---|---|
| `grid.py` | `Grid` dataclass + `_build_grid`: 0.5 mm 2-layer discretisation of the board, populated with static blockers (edge clearance, device pockets, per-pin "approach corridors"). Also stashes dynamic `_pin_approach_*` attrs on the Grid instance — lifting these into proper fields is a known follow-up. |
| `astar.py` | `_astar` search + cost weights (`_W_STEP`, `_W_VIA`, `_W_CROSSING`, `_W_EDGE`, `_W_BEND`, `_W_PARALLEL_*`). Cardinal-only moves; optional parallel-mate bonus for bundled pair routing. |
| `blocking.py` | `_block_path`: post-route halo inflation of a `SignalPath` onto the grid for subsequent nets. Exempts pin approach cells so pins stay reachable. |
| `collapse.py` | `_path_to_waypoints` (cells → corner Waypoints) and `_collapse_quadrant_runs` (monotonic cardinal staircase → 45° diagonal). Called as a post-route global pass from `route_board` so each collapse sees every other path's halo. |
| `schedule.py` | `_net_priority` + `_ordered_bus_actions`: route signals in priority order with bundled pair-mate hints (VCC/GND, SCL/SDA). |
| `paths.py` | `Waypoint` dataclass + `waypoints_to_path` (Waypoints → `SignalPath`). |
| `score.py` | Route quality scoring used by `bin/score-routes`. |
| `autoroute.py` | Orchestration: `RouteFailure`, `_route_one_net`, `route_board`, `autoroute`. |

External callers should only import:

- `router.autoroute` — `RouteFailure`, `route_board`, `autoroute`
- `router.paths` — `Waypoint`, `waypoints_to_path`

Everything `_`-prefixed in the other modules is internal and may move.

## Lint + type-check

`bin/lint` runs ruff + ty in one shot:

```bash
nix develop -c ./bin/lint              # check both src and tests
nix develop -c ./bin/lint --fix        # apply ruff auto-fixes
nix develop -c ./bin/lint format       # ruff format (writes changes)
```

Both tools always run so a single invocation surfaces the full picture.
Config in `cad/pyproject.toml`:

- **ruff**: `select = ["ALL"]` with documented per-rule and per-file
  ignores. Notable per-file exemptions:
  - `tests/**` — D (docstrings), S101 (assert), PLR2004, ANN.
  - `src/router/**` — C901/PLR09xx (inherent A* complexity), N806
    (`A`/`B` endpoint markers), SLF001 (Grid dynamic attrs follow-up),
    PLR2004 (rotation/grid magic numbers).
  - `src/board/cli_*.py` — T201 (prints are the CLI), C901/PLR09xx.
  - `src/voxel_*.py` — `ALL` (legacy; defer until rewire/remove).
- **ty**: preview mode with explicit strict promotions (deprecated,
  possibly-missing-*, redundant-cast, unused-ignore-comment, …)
  mirroring `~/repos/scifireality/placeholder/`'s pattern.

## Tests

```bash
nix develop -c ./bin/test              # all 37 tests
```

Tests live in `code/cad/tests/`; pytest config in `cad/pyproject.toml`
sets `pythonpath = ["src"]` so `from router.foo import …` resolves
without an `src.` prefix.
