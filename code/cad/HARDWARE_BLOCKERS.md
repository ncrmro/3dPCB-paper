# Hardware blockers

Known issues preventing printing and on-hardware validation of the CAD
substrates. Each entry names the symptom, the consequence, and the
fix-or-defer status.

| ID | Blocker | Consequence | Status |
|----|---------|-------------|--------|
| HB-1 | `voxel_grid.BOARD_W = 80.0` is stale (substrate uses `_BOARD_W = 68.0`) | Edge-proximity tooling that relies on `voxel_grid` (e.g. `voxel_suggester`) computes wrong distances to the east/west board edges, masking edge-exposure failures. | Open. Fix: collapse to a single source of truth in `code/cad/src/vitamins/substrate.py` and have `voxel_grid` import it. |
| HB-2 | +Y board excess (~9.6 mm past the SDA highway at y=+15 on Tier2Substrate) | The printed plate carries ~10 mm of substrate north of any feature, wasting filament and visually misrepresenting the populated bbox. | Open. Documented in `substrate.py:85–99` as deferred — needs the `.solid() + .hole()` rewrite of `build()`. |
| HB-3 | OLED not on `PRIMARY_BUS` for routing-builder visibility | `test_netlist.py:58-61` notes that the OLED pinout is tested in isolation but not yet on the bus net for routing purposes. Routing builders only see OLED via per-builder lookups, not via a shared net. | Open. Low priority; current builders work around it explicitly. |
| HB-4 | SDA edge exposure on `Tier2SubstrateBundled` | SDA's L2 east-leg centreline at x=+34 inflates (channel half-width 0.4 + wall floor 0.6) to x=+34.5 — outside the board outline. The wire prints physically exposed at the east face. | **Mitigated.** `Tier2SubstrateOption2` routes the entire SDA trunk on L1 with east-leg at x=+33.0 (clear of the inflated boundary). Bundled is kept as the "before" half of `bin/score-routes`. Remove this entry once `Tier2SubstrateBundled` is retired. |
| HB-5 | `kicad-cli` not in the orchestration nix shell | `prebuild-kicad` fails under process-compose. CAD changes can't be cross-validated against the KiCad spike PCB until the orch shell is updated. | Open. Out of scope for the SDA rework. |
| HB-6 | `code/cad/src/router/` was empty on `main` before this work | The `feat/route-optimiser` branch carries an optimiser (`router/optimiser.py`, `router/collisions.py`) that's not merged. The waypoint + score helpers added here are pure-Python and intentionally orthogonal — the optimiser can be merged on top without touching `router/paths.py` or `router/score.py`. | Open. Optimiser merge is a separate decision. |
| HB-7 | `circuit/` spec v1 supports axis-aligned rectangles only | `Level.perimeter` and `Device.pocket` are typed `Rect`; arbitrary polygons (rounded edges, L-shapes, irregular pedestals) would need an OpenSCAD `polygon()` bridge through `pythonopenscad`. `build.py` raises `NotImplementedError` if a future spec type carries a non-Rect perimeter, so the limitation is loud rather than silent. | Open. Lift when the first non-rectangular variant lands. |

## What changed in this work

- `test_no_channel_on_board_edge` (in `tests/test_substrate_routing.py`) flags HB-4 going forward — any future class that lays a channel on the board outline fails CI. The bundled tier is `xfail`-marked there until it's retired.
- `Tier2SubstrateOption2` in `vitamins/substrate.py` is HB-4's fix. Use `bin/score-routes tier2_substrate_bundled tier2_substrate_option2` to compare them.
- `router/paths.py` (`Waypoint` + `waypoints_to_path`) lets future route experiments be authored as checkpoint lists.
- `router/score.py` (`RouteScore` + `score_paths`) makes "is variant A better than variant B?" a one-line question.
