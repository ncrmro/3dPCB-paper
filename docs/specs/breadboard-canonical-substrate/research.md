# Breadboard-canonical substrate Research

## Clearance-family audit (codebase, 2026-05-28)

Traced every clearance constant through `code/cad/src`. Finding: the scattered
clearance family is really **one quantity** — `min_wall_thickness`, the minimum
solid material between a wire edge and any neighbor. Every keep-out is
`(half-feature-extent) + min_wall_thickness`:

| Keep-out | Formula | Value | Location |
|---|---|---|---|
| wire halo | `channel_width + min_wall_thickness − res/2` | 1.15 | `blocking.py:37` |
| wire halo (align rebuild) | same formula, re-derived | 1.15 | `align.py:616` |
| via halo | `via_diameter/2 + min_wall_thickness` | 1.35 | `blocking.py:38` |
| score edge inflate | `channel_width/2 + min_wall_thickness` | 1.0 | `score.py:149` |
| wall_floor invariant | `channel_width + min_wall_thickness` | 1.4 | `cli_report.py:128` |
| pocket margin | `pocket_clearance + channel_width/2` | 0.7 | `grid.py:242` |

**Conclusion:** promoting `min_wall_thickness` → `buffer` and centralizing the
derivations on `ResolvedDims` realizes the spec's universal-buffer model with
minimal churn. `pocket_margin` is the lone outlier (uses `pocket_clearance`,
0.3, not `min_wall_thickness`); folding it into `buffer` is a deliberate Phase-2
value change, not part of the behavior-preserving Phase 1.

## Dead / drifting code found

- **`hole_pair_clearance`** — defined in `_DEFAULTS` (build.py:40),
  `ResolvedDims` (build.py:54), and `DimOverrides` (board.py:76); **consumed
  nowhere**. Safe deletion, behavior-preserving.
- **Duplicated halo formula** — `channel_width + min_wall_thickness − res/2`
  computed independently in `blocking.py:37` and `align.py:616`. Must stay
  numerically identical; nothing enforces it today. DRY hazard → one accessor.
- **Duplicated pocket inflation** — `build.py:287` (pocket cut = footprint +
  2·pocket_clearance) vs `grid.py:242` (routing keep-out = pocket_clearance +
  channel_width/2). Related but not identical; both should derive from one
  source.
- **Shadow defaults** — `score.py:130-131` hardcodes `channel_width=0.8,
  min_wall_thickness=0.6`; `paths.py:52` hardcodes `via_diameter=1.5`. Real
  callers pass `dims.*`, so these literals are drift-prone fallbacks.
- **`resolve_dims` boilerplate** — every knob named 3× (defaults dict → dataclass
  field → kwarg splat, build.py:62-72). Adding a knob means editing all three.

## FDM tolerance basis (hardware-validated)

From `docs/fdm_tolerance_notes.md` (validation printer, 0.4 mm nozzle, PLA,
default Bambu Studio):

- Worst-case over-extrusion ~**+0.43 mm** at recess transitions; interior shrink
  only ~0.05 mm. Motivates the **1.0 mm** default buffer.
- Receptacle coupon v2 (2026-05-19): **1.25 mm** is the smallest CAD bore that
  both passes light and accepts/holds a standard DuPont pin. Bores ≤ ~0.8 mm
  vanish under default slicer settings. Motivates the unified **1.25 mm** hole.
- Grip at 1.25 mm is low (over-extrusion eats the interference); the notes
  recommend slicer hole/elephant's-foot compensation. Clarify Q4 chose to also
  add a **CAD grip target** so grip doesn't depend on slicer settings.

## Design decisions

1. **`buffer` lives on `ResolvedDims` as derived accessors**, not a new module —
   keeps the single source where the rest of the pipeline already reads.
2. **`via_diameter` defaults to `hole_diameter`** but stays an independent
   override (clarify Q1).
3. **Fail-loud over auto-relax** for over-constraint (clarify Q2) — matches the
   constitution's no-silent-violation gate.
4. **Synchronized chamfers are automatic for every adjacent bus pair**
   (clarify Q3), applied after pitch alignment, before per-path collapse.
5. **Vectorized 45° deferred to Phase 5** — highest risk; the locked docs/spec
   precede the code churn.

## Risk assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Phase 1 silently changes output | Med | Golden-output test on reference boards; pocket_margin keeps `pocket_clearance` term until Phase 2 |
| Buffer→1.0 makes a board unroutable | Med | Fail-with-report (FR-11); buffer is per-board overridable |
| Vectorized 45° regresses clearance | High | Sequenced last; report gate + targeted tests; chamfers must not cut via/pin (US-7) |
| Grip target over-tightens bore | Low | Hardware coupon re-print is the human gate; printer-dependent + overridable |
| Snapping conflicts with buffer | Med | Fail-with-report; designer resolves placement |

## References

- `docs/fdm_tolerance_notes.md` — coupon results, over-extrusion measurements.
- `docs/plan.md`, `AGENTS.md`, `code/AGENTS.md` — pipeline + module layout.
- Source audited: `board/{board,build,connectors}.py`,
  `router/{grid,blocking,score,collapse,align,paths}.py`,
  `board/{cli_report,cli_score}.py`.
