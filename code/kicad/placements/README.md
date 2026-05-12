# Substrate placements

Each YAML file here is one **substrate variant** — a declarative
pairing of a KiCad netlist with a 3D-printed substrate layout. The
gallery's `/embodiment/[id]/` route reads these and renders the
matched pair side-by-side.

## Schema

```yaml
id: stacked_vertical        # url-safe slug; matches /embodiment/[id]/
label: "Stacked vertical"
pcb: spike.kicad_pcb        # KiCad project file under code/kicad/
substrate:
  glb: scd41_breakout.glb   # GLB under code/cad/build/ (served from /models/cad/)
  camera: iso               # optional; defaults to cad manifest's iso camera
parts:
  U1: { x: 0,  y: 0,  z: 0, rotation: [0, 0, 0], pinned: true }
  U2: { x: 0,  y: 20, z: 0, rotation: [0, 0, 0], pinned: false }
  U3: { x: 20, y: 0,  z: 0, rotation: [0, 0, 0], pinned: false }
```

- `id` — url-safe slug. Filename does not have to match but should
  for grep-ability.
- `pcb` — the KiCad project file. Must live under `code/kicad/`. The
  PCB GLB at `/models/kicad/{basename without .kicad_pcb}.glb` is
  rendered into the right pane.
- `substrate.glb` — a GLB filename produced by the AnchorSCAD render
  pipeline (`bin/prebuild-cad`); served from `/models/cad/`.
- `substrate.camera` — optional camera key from
  `code/web/src/manifest.cad.yaml`'s `cameras` table.
- `parts` — reference-designator-keyed map of (position,
  orientation, pinned). Consumed by the Phase-3 router; today the
  embodiment route only displays the table.

## Loading

The dynamic route `code/web/src/pages/embodiment/[id].astro` reads
every `*.yaml` in this directory at build time. Add a file → ship a
new page. `README.md` is the only file ignored.
