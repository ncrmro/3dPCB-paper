# Job Management

This folder and its subfolders are managed using `deepwork_jobs` workflows.

## Project-specific context

### Voxel-test gate

A geometric collision gate exists at
`code/cad/tests/test_substrate_routing.py` and is the authoritative
mechanical check for materialized substrates. Invoke via
`scripts/run_voxel_check.sh` — the script handles the `nix develop` shell
and pytest invocation, and exits 0 with "PASS — all voxel checks green"
or non-zero with the colliding (signal, x, y) lines from the assertion.

The test fixture in `code/cad/tests/test_substrate_routing.py` uses a
hard-coded `params=[Tier1Substrate, Tier2Substrate, Tier2SubstrateBundled]`
list and rasterizes each at 0.1 mm resolution. New substrate classes must
be added to that params list explicitly — they are not picked up
automatically from AnchorSCAD's `registry.py` (which is for vitamin-shape
auto-registration, a separate mechanism).

### Known failure modes catalog

The full list of seven known failure modes lives in `job.yml` under
"Known failure modes the check_routing step MUST catch". Failure modes
5–7 were added 2026-05-21 after the bundled Tier 2 substrate session:
mode 5 (L2-inside-pocket / board contact), mode 6 (bus-return-blocked-
by-power-corridor-stubs), and mode 7 (sub-printable wall thickness).

### Known printability issue (currently in-tree, NOT a test failure yet)

The bundled Tier 2 substrate has a sub-printable wall (mode 7)
between VCC's L1 east leg at y=-16 and the sensor pin row at y=-17.
Channel south edge at -16.4, pin hole north edge at -16.5 → 0.1 mm
CAD wall, well below the 0.6 mm FDM floor (see
`docs/fdm_tolerance_notes.md`). Two follow-ups needed:

1. Update `code/cad/tests/test_substrate_routing.py` to enforce the
   wall buffer (currently only checks for zero-distance overlap, not
   sub-printable proximity). Once added, the test will fail on the
   current substrate and the issue becomes visible.
2. Move VCC's L1 east corridor further from the pin row (e.g. y=-16
   → y=-15.5 or restructure the power topology entirely).

### Materialization gap

The `single_plan` workflow produces `substrate_plan.md` (text) but does
not automatically translate per-net YAML routing blocks into substrate.py
code. Today that translation is hand-edited in
`code/cad/src/vitamins/substrate.py` — each substrate class defines its
own `_get_signal_paths()` returning `SignalPath` instances. Future
automation (a `materialize_substrate` step that parses the plan YAML and
emits a substrate class) would close this gap.

## Recommended Workflows

- `deepwork_jobs/new_job` - Full lifecycle: define → implement → test → iterate
- `deepwork_jobs/learn` - Improve instructions based on execution learnings
- `deepwork_jobs/repair` - Clean up and migrate from prior DeepWork versions

## Directory Structure

```
.
├── .deepreview        # Review rules for the job itself using Deepwork Reviews
├── AGENTS.md          # This file - project context and guidance
├── job.yml            # Job definition (step instructions are inlined here)
├── hooks/             # Custom validation scripts and prompts
│   └── *.md|*.sh      # Hook files referenced in job.yml
├── scripts/           # Reusable scripts and utilities created during job execution
│   └── *.sh|*.py      # Helper scripts referenced in step instructions
└── templates/         # Example file formats and templates
    └── *.md|*.yml     # Templates referenced in step instructions
```

## Editing Guidelines

1. **Use workflows** for structural changes (adding steps, modifying job.yml)
2. **Direct edits** are fine for minor instruction tweaks

## Bespoke learnings (from prior `learn` runs)

### 2026-05-20 — `optimize_net_sharing` step added

`single_plan` gained a new step between `draft_plan` and
`check_routing`: `optimize_net_sharing`. Triggered by the Tier 2
OLED + SCD41 stack realisation that the two devices' GND pins are
physically adjacent in 3D once the OLED PCB cantilevers north
across the substrate's interior — routing them as one merged
trunk saves wire vs the existing one-trunk-per-device topology.

Per-net rules baked into the step instructions:
- **GND**: always a merge candidate.
- **VCC**: candidate with a droop-warning note.
- **SDA / SCL**: NEVER merged — I²C is already multi-drop and the
  corridor model already handles fan-out; merging breaks the model.
- **Singletons** (ADDR / NC / unused): not candidates.

The step asks the user via `AskUserQuestion`. In autonomous mode
(no interactive user available), it defaults to TRUE for every
proposal and annotates the plan with `merged in auto mode` so
the choice is auditable.

Concrete bespoke case this was designed for:
- See `code/cad/src/vitamins/substrate.py` `Tier2Substrate` —
  OLED at `_J4_*` cantilevers north from y=-22, PCB body
  overlapping SCD41 / BH1750 area.
- Substrate physical bounds + pocket positions used to identify
  "stacked" devices: see `substrate.py` `_COLUMN_ANCHORS` and
  pocket setup in `Tier1Substrate.build()`.
- Net definitions / which devices share which signals: see
  `code/cad/src/netlist.py` `PRIMARY_BUS` + per-device PINOUTs.

The `printable_pcb/spike_v2/substrate_plan.md` artefact predates
the optimisation step and does **not** contain merge annotations.
Re-running `single_plan` over the same brief will surface the
OLED+SCD41 GND merge as the first proposal.

### 2026-05-20 — slicer-based print-time tracking (same session)

User flagged that wire-length saved is a proxy — the cost that
matters is FDM print time + filament. The `optimize_net_sharing`
step now also reports slicer-derived Δtime and Δfilament per
proposal, via a thin wrapper at `code/cad/bin/slicer-estimate`
(not yet implemented — graceful degradation: skip the deltas and
record the skip in the step summary). The process_requirement
"Print-time deltas attempted" enforces that the slicer pass is
either run or explicitly noted as unavailable; silently dropping
the metric is a process failure.

TODO upstream: implement `code/cad/bin/slicer-estimate` as a
wrapper around the user's slicer CLI (PrusaSlicer
`--slice --info`, Bambu Studio's equivalent, or OrcaSlicer).
Extract `estimated_print_time` and `filament_used` from the
slicer's stdout / gcode header.

### 2026-05-20 — DeepSchema for substrate_plan.md

To prevent the failure mode where a plan ships without the new
Net merge audit section, added
`.deepwork/schemas/printable_pcb_substrate_plan/deepschema.yml`.
Matchers cover `printable_pcb/*/substrate_plan.md`; requirements
enforce the nine-section structure, the inline YAML routing
blocks, the Net merge audit presence, and the auto-vs-user
annotation. This is structural prevention — the schema fires on
every save regardless of whether the optimize_net_sharing step
was run, so a missing audit section surfaces immediately rather
than at downstream consumption time.
