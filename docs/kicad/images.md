# Rendering KiCad boards to images

For PR descriptions, paper figures, and review threads we want PNGs
of the PCB, not raw `.kicad_pcb` files. KiCad ships a headless
renderer that needs no GUI session.

## Direct PCB render (recommended)

`kicad-cli pcb render` raytraces a `.kicad_pcb` directly to PNG/JPEG.
No STL intermediate, no OpenSCAD, no display server.

```bash
cd code/kicad
nix develop -c kicad-cli pcb render \
  spike.kicad_pcb \
  -o spike-top.png \
  --rotate '-30,0,30' \
  --quality high \
  --floor
```

A ~1600×900 render of a small board takes ~4 s on a laptop CPU.
Output is ~1 MB PNG with transparency.

### Useful flags

| Flag | Effect |
|---|---|
| `--side top` / `bottom` / `left` / `right` / `front` / `back` | Camera face. Default `top`. |
| `--rotate 'X,Y,Z'` | Euler rotation in degrees. `'-30,0,30'` is the standard isometric. |
| `--quality basic` / `high` / `user` / `job_settings` | `high` enables raytracing. `basic` is OpenGL preview-quality. |
| `--floor` | Adds a shadow-receiving floor plane. Forces post-processing on. |
| `--background transparent` / `opaque` | Default: transparent for PNG, opaque for JPEG. |
| `--perspective` | Perspective instead of orthographic projection. |
| `--width W --height H` | Resolution. Default 1600×900. |
| `--zoom Z` | Camera zoom multiplier. |

### Three-view convention

For PRs and the paper, emit three views per board:

```bash
kicad-cli pcb render spike.kicad_pcb -o spike-iso.png    --rotate '-30,0,30' --quality high --floor
kicad-cli pcb render spike.kicad_pcb -o spike-top.png    --side top  --quality high
kicad-cli pcb render spike.kicad_pcb -o spike-bottom.png --side bottom --quality high
```

### Component 3D models

KiCad resolves component meshes via `${KICAD9_3DMODEL_DIR}`. The
`code/kicad/` dev shell does not yet export this — board geometry
renders fine, but missing-model warnings will print for components
that reference packaged `.wrl` / `.step` files. To silence them, add
to `code/kicad/flake.nix` shellHook:

```nix
export KICAD9_3DMODEL_DIR="${pkgs.kicad}/share/kicad/3dmodels"
```

## STL render (for the substrate compiler)

The substrate compiler emits STL, not `.kicad_pcb`. To render those,
use the headless OpenSCAD already in the `code/cad/` dev shell:

```bash
cd code/cad
cat > /tmp/render.scad <<'EOF'
import("path/to/substrate.stl");
EOF
nix develop -c openscad -o substrate.png \
  --camera=0,0,0,55,0,25,200 \
  --imgsize=1600,900 \
  /tmp/render.scad
```

`--camera` is `tx,ty,tz,rx,ry,rz,dist`. The wrapped OpenSCAD uses
EGL for headless GPU rendering — no X server needed.

## When to use which

- **Spike PCB / paper figures**: `kicad-cli pcb render` — the board
  *is* the canonical artifact.
- **Substrate variants in the orientation gallery (Phase 2+)**:
  OpenSCAD over STL — the substrate compiler is what produces them
  and they have no `.kicad_pcb` equivalent.
- **Side-by-side PCB ↔ substrate comparisons**: render each with its
  native tool, compose externally (e.g. `montage` from ImageMagick),
  or feed both as GLB into `<model-viewer>` in the planned `code/web/`
  gallery (see `docs/plants/W20-demoable-paper.md`).
