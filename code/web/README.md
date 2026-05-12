# @3dpcb-paper/web

Static Astro gallery that renders AnchorSCAD substrates and KiCad PCBs as
`<model-viewer>` cards so the paper's "substrate and PCB are sibling
embodiments of one netlist" claim is visible in a browser. This PR is the
scaffold only: the index page reports "no models yet" until PRs E and F wire
the render pipelines into `public/models/`.

## Run

```bash
cd code/web
nix develop -c bun install
nix develop -c bun run dev   # http://localhost:4321
```
