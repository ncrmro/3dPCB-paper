# data/models — third-party 3D models

External 3D models for the spike circuit's three modules. Both the
KiCad `(model ...)` block and the AnchorSCAD vitamin pipeline can
consume the STEP / STP files in here.

## Layout

| Folder | Component | Source | License | Tracked? |
|---|---|---|---|---|
| `scd40_breakout/` | Adafruit STEMMA QT 5187 (SCD-40 — same PCB as 5190 / SCD-41) | [adafruit/Adafruit_CAD_Parts](https://github.com/adafruit/Adafruit_CAD_Parts) | MIT | yes |
| `bh1750_breakout/` | usini GY-302 footprint (`.kicad_mod`) | [usini/usini_kicad_sensors](https://github.com/usini/usini_kicad_sensors) | CC-0 | yes |
| `bh1750_breakout/` | GrabCAD GY-302 STEP (Jonathan Griggs, via usini) | GrabCAD upload | GrabCAD ToS — royalty-free use, **not redistributable** | no — fetched |
| `esp32_c3_supermini/` | mrtnvgr Supermini STEP | [mrtnvgr/KiCad_ESP32-C3-SuperMini](https://github.com/mrtnvgr/KiCad_ESP32-C3-SuperMini) | unstated (treat as all-rights-reserved) | no — fetched |

## Fetching the unredistributable assets

```bash
nix develop -c bin/fetch-models
```

Running this implicitly accepts the upstream terms documented in the
table above. Files land in the same `data/models/<component>/` paths
but are git-ignored so they don't leak into the published repo.

## Why split commit vs fetch

The publication target is CERN-OHL-S for hardware. Files we commit
must be relicensable (or compatibly licensed) under that. MIT and
CC-0 are; GrabCAD ToS and an unstated license aren't, so we keep
those out of the tree and let each contributor pull them under their
own copy of the upstream terms.
