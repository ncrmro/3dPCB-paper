# W20: Demoable paper restructure

Date: 2026-05-12
Status: plan; depends on PRs #1 and #2 merging first.

## Why this exists

The repo is one spike: a research paper demoing a novel AI / PCB /
CAD generation methodology. The current layout — `cad/` and
`kicad/` at root, plus `kicad/spike/` — uses "spike" naming that's
redundant when the entire repo is the spike. Week W20 collapses
that, introduces a `code/` workspace (uv + bun), and adds an Astro
gallery that makes the paper's headline claim ("the substrate and
the PCB are sibling embodiments of one netlist") visible in a
browser.

## Target layout

```
3dPCB-paper/
├── AGENTS.md
├── docs/
│   ├── paper.md
│   ├── plan.md
│   ├── kicad/images.md
│   └── plants/W20-demoable-paper.md          # this file
└── code/
    ├── pyproject.toml                        # uv workspace root
    ├── package.json                          # bun workspace root
    ├── cad/                                  # AnchorSCAD project
    │   ├── pyproject.toml                    #   uv workspace member
    │   ├── flake.nix
    │   ├── bin/render
    │   └── src/{registry.py, vitamins/, ...}
    ├── kicad/                                # was kicad/spike/
    │   ├── flake.nix
    │   ├── README.md
    │   ├── RESEARCH.md
    │   ├── bin/{render-board, render-glb}
    │   ├── spike.kicad_{pro,sch,pcb}
    │   └── placements/
    └── web/                                  # bun + astro gallery
        ├── package.json                      #   bun workspace member
        ├── flake.nix
        ├── astro.config.mjs
        └── src/{pages/, components/, ...}
```

Per-subproject `flake.nix` files stay (the AGENTS.md convention).
`code/` is *both* a uv workspace root (`pyproject.toml`,
`members = ["cad"]`) and a bun workspace root (`package.json`,
`workspaces = ["web"]`). Any future Python or JS module under
`code/` joins by adding itself to the respective members list —
one symmetrical pattern across both ecosystems.

## Gallery design

`<model-viewer>` web component (Google) for in-browser 3D. Inputs
must be GLB/GLTF:

- **KiCad** → native: `kicad-cli pcb export glb foo.kicad_pcb`.
- **AnchorSCAD** → SCAD → STL (OpenSCAD) → GLB (`assimp export`).

Astro builds statically. The build step runs both render pipelines,
emits GLBs under `code/web/public/models/`, and Astro reads a
manifest (the `cadeng.yaml`-shaped declaration) to lay out the
gallery cards.

Page routes:

- `/` — index, grouped by project.
- `/embodiment/[id]` — side-by-side substrate ↔ PCB pair for one
  variant. Reads the `placements/*.yaml` sidecar to match
  substrate variants to the netlist.

The vanilla-JS lightbox and CSS grid from
`~/repos/ncrmro/cadeng/client/` port over directly; only the card
body changes (`<img>` → `<model-viewer>`).

## Prerequisites

1. PR #1 (`docs/plan-spike-orientation-router`) merged.
2. PR #2 (`feat/kicad-spike`) merged.
3. `main` pulled into `~/repos/ncrmro/3dPCB-paper/`.

## Stacked PRs

Each PR lives in its own worktree under
`~/repos/ncrmro/worktrees/3dPCB-paper/{branch}/`. One conventional
commit per PR.

### PR A — `chore(layout): move code into code/`

Worktree: `chore/code-layout`. Base: `main`.

- `git mv cad code/cad`
- `git mv kicad/spike/* kicad/` then `git mv kicad code/kicad`
  (flattens the `spike/` level; `code/kicad/spike.kicad_pcb` etc).
- Edit `AGENTS.md` Layout section: `cad/` → `code/cad/`,
  `kicad/` → `code/kicad/`.
- Edit `docs/kicad/images.md`: `cd kicad` → `cd code/kicad`.
- No code or content edits — pure move.

Blocks everything else.

### PR B — `feat(workspace): uv + bun workspace roots at code/`

Worktree: `feat/code-workspaces`. Base: A.

- Add `code/pyproject.toml`:
  ```toml
  [project]
  name = "3dpcb-paper"
  version = "0.0.0"
  requires-python = ">=3.13"
  [tool.uv.workspace]
  members = ["cad"]
  ```
- Add `code/package.json`:
  ```json
  {
    "name": "3dpcb-paper",
    "private": true,
    "workspaces": ["web"]
  }
  ```
  `web/` doesn't exist at this point — bun resolves workspace globs
  lazily and ignores missing members. PR C creates
  `code/web/package.json` and the workspace activates.
- Verify `code/cad/pyproject.toml` resolves cleanly under the uv
  workspace.
- Smoke-test: `cd code && nix develop -c uv sync`.

Parallel with C, D.

### PR C — `feat(web): astro+bun gallery scaffold`

Worktree: `feat/web-scaffold`. Base: A.

- `code/web/package.json` — workspace member; deps: `astro`,
  `@astrojs/check`, `@google/model-viewer`, `typescript`. Bun
  runtime. `name` is `@3dpcb-paper/web`.
- `code/web/astro.config.mjs` — static output mode.
- `code/web/flake.nix` — `pkgs.bun`, `pkgs.nodejs_20`.
- One placeholder route `/` listing an empty gallery (no models yet).
- Crib lightbox + CSS grid from `~/repos/ncrmro/cadeng/client/`.
- Smoke-test: `cd code && bun install`; `cd code/web && nix
  develop -c bun run dev`.

Parallel with B, D. Coordinates with B via the `code/package.json`
`workspaces: ["web"]` glob.

### PR D — `feat(kicad): render scripts + 3dmodel env`

Worktree: `feat/kicad-render-scripts`. Base: A.

- `code/kicad/bin/render-board` — wraps `kicad-cli pcb render` with
  the three-view convention (iso, top, bottom) from
  `docs/kicad/images.md`.
- `code/kicad/bin/render-glb` — wraps `kicad-cli pcb export glb`.
- `code/kicad/flake.nix` shellHook adds
  `export KICAD9_3DMODEL_DIR="${pkgs.kicad}/share/kicad/3dmodels"`.
- Smoke-test on the KiCad demo board if `spike.kicad_pcb` doesn't
  exist yet.

Parallel with B, C.

### PR E — `feat(web): anchorscad outputs wired into gallery`

Worktree: `feat/web-anchorscad`. Base: merged B + C.

- Extend `code/cad/bin/render` (or add `code/cad/bin/build-glb`) to
  run OpenSCAD → STL, then `assimp export` → GLB.
- Add `assimp` to `code/cad/flake.nix` packages.
- Astro prebuild script invokes `code/cad/bin/render` and copies
  GLBs to `code/web/public/models/cad/`.
- Manifest `code/web/src/manifest.cad.yaml` mirrors the cadeng.yaml
  shape: project, models[name, glb path, default camera].
- Gallery cards instantiate `<model-viewer src="…" camera-controls
  auto-rotate>`.

Parallel with F.

### PR F — `feat(web): kicad outputs wired into gallery`

Worktree: `feat/web-kicad`. Base: merged C + D.

- Astro prebuild invokes `code/kicad/bin/render-glb` for each
  `.kicad_pcb` under `code/kicad/`, copies GLBs to
  `code/web/public/models/kicad/`.
- Also invoke `render-board` for static iso PNG fallbacks
  (lightweight previews; `<model-viewer>` lazy-loads GLB on
  intersect).
- Manifest `code/web/src/manifest.kicad.yaml`.

Parallel with E.

### PR G — `feat(web): embodiment-pair view`

Worktree: `feat/web-embodiment`. Base: merged E + F.

- Route `/embodiment/[id].astro` reads
  `code/kicad/placements/[id].yaml`, resolves the matching KiCad
  netlist and the substrate GLB.
- Renders two `<model-viewer>` panes side-by-side with synchronized
  camera (via `model-viewer`'s `camera-orbit` attribute bound to a
  shared state).
- Linked from `/` gallery cards.

Final PR.

## Parallelism map

```
A    (sequential, blocks all)
│
├── B    ─┐
├── C    ─┤  3-way parallel
├── D    ─┘
│
├── E (after B + C)  ─┐
├── F (after C + D)  ─┤  2-way parallel
│
└── G (after E + F)   final
```

Wave timing: A → {B,C,D} → {E,F} → G. Four waves; waves 2 and 3
saturate three parallel agents.

## Parallel agent assignment

When delegating to autonomous agents, run them in four waves. Each
agent receives: target worktree absolute path, base branch, the PR
section above as its scope brief, and a hard rule that
cross-cutting files (`AGENTS.md`, `docs/`) only get touched by the
PR that explicitly says so.

| Wave | Agents | PRs | Notes |
|---|---|---|---|
| 1 | 1 | A | Sequential. Pure `git mv` + path edits. |
| 2 | 3 | B, C, D | Independent worktrees. No file overlap. |
| 3 | 2 | E, F | Both touch `code/web/` but disjoint subdirs (`public/models/cad/` vs `public/models/kicad/`; separate manifests). |
| 4 | 1 | G | Reads outputs from E and F; no merge conflict expected. |

## Loss accounting

- `kicad/spike/` directory removed; contents flatten one level.
- The word "spike" remains in `spike.kicad_pro` etc. — the *repo*
  is the spike, but the demo board itself can still carry the name.
- PR #2 commits reference the old `kicad/spike/` path. After PR A
  merges, the move commit names the rename so `git log --follow`
  continues to track the files.

## Verification

After PR G merges:

```bash
cd ~/repos/ncrmro/3dPCB-paper

# 1. uv + bun workspaces resolve from code/
cd code && nix develop -c uv sync
cd code && nix develop -c bun install

# 2. AnchorSCAD render emits GLB
cd code/cad && nix develop -c ./bin/render

# 3. KiCad render emits GLB + iso/top/bottom PNG
cd code/kicad && nix develop -c ./bin/render-board spike.kicad_pcb
cd code/kicad && nix develop -c ./bin/render-glb   spike.kicad_pcb

# 4. Astro dev server
cd code/web && nix develop -c bun run dev
# open http://localhost:4321
```

Acceptance:

1. Gallery index shows at least one AnchorSCAD vitamin card and the
   spike PCB card; each rotates in `<model-viewer>`.
2. `/embodiment/[id]` shows substrate ↔ PCB side-by-side with a
   synchronized camera.
3. `nix develop` works from every subdir (`code/`, `code/cad`,
   `code/kicad`, `code/web`).
4. `cd code && uv sync` resolves the uv workspace; `cd code && bun
   install` resolves the bun workspace. Both produce a single
   lockfile at the `code/` root.
