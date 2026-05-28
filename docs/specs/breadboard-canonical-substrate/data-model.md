# Breadboard-canonical substrate Data Model

This project has no database. The "data model" is the **declarative dimension
schema** — the knobs a board author sets and the resolved/derived values every
pipeline stage reads. This document is the canonical record of that schema and
its derivations (the Phase 0 deliverable referenced by the constitution).

## Entity Relationship

```
Board (YAML) ──1──> DimOverrides ──merge over──> _DEFAULTS
                          │                          │
                          └──────► resolve_dims() ◄──┘
                                        │
                                        ▼
                                  ResolvedDims  ──derived accessors──┐
                                        │                            │
        ┌───────────────┬──────────────┼───────────────┬────────────┤
        ▼               ▼              ▼                ▼            ▼
   builder geometry  grid blockers  path halos      scorer      report
   (build.py)        (grid.py)      (blocking.py,   (score.py)  (cli_report.py)
                                     align.py)
```

`Connector` (catalog) is a sibling entity consumed by the builder for headered
devices; its bore derives from the unified hole size.

## Entities

### DimOverrides (YAML knob surface)

Per-board overrides; anything `None` falls back to `_DEFAULTS`. **This feature
shrinks the surface.**

| Field | Type | Default (source) | Status | Description |
|-------|------|------------------|--------|-------------|
| `buffer` | float \| None | 1.0 (Phase 2; 0.6 in Phase 1) | **new** | Min solid-material gap between any feature pair |
| `pitch` | float \| None | 2.54 | **new** | Breadboard module; snapping + spacing unit |
| `hole_diameter` | float \| None | 1.25 (Phase 3; 1.0 before) | unified bore source |
| `via_diameter` | float \| None | = `hole_diameter` | overridable per board (clarify Q1) |
| `channel_width` | float \| None | 0.8 | kept | Wire channel width |
| `channel_depth` | float \| None | 0.8 | kept | Channel cut depth |
| `overcut` | float \| None | 0.1 | kept | CSG over-cut margin |
| `pocket_clearance` | float \| None | 0.3 | **kept** | Device drop-in fit tolerance (sizes the recess). The pocket *routing* margin adds a full `buffer` wall on top — see `pocket_margin_mm` |
| `edge_clearance` | float \| None | 0.8 | **kept** | Board-outline keep-out strip; left independent of `buffer` |
| `min_wall_thickness` | float \| None | renamed → `buffer` | renaming | Was 0.6; it *is* the buffer |
| `hole_pair_clearance` | float \| None | — | **DELETE** | Defined 3×, consumed 0× (dead) |

Constraints: all floats `> 0` (Pydantic). `model_config = frozen, extra=forbid`.

### ResolvedDims (single source of truth)

Frozen dataclass produced by `resolve_dims(board)`. Holds the raw resolved knobs
plus **derived accessors** that are the *only* definition of each clearance
formula. Today these formulas are duplicated across modules; consolidating them
here is the core of Phase 1.

| Accessor | Derivation | Value (buffer=1.0) | Replaces (today duplicated at) |
|----------|-----------|---------------|-------------------------------|
| `wall_floor_mm` | `channel_width + buffer` | 1.8 | `cli_report.py:128` |
| `wall_halo_mm` | `channel_width + buffer − res/2` | 1.55 | `blocking.py:37`, `align.py:616` |
| `via_halo_mm` | `via_diameter/2 + buffer` | 1.75 | `blocking.py:38` |
| `edge_inflate_mm` | `channel_width/2 + buffer` | 1.4 | `score.py:149` |
| `pocket_margin_mm` | `pocket_clearance + buffer + channel_width/2` | 1.7 | `grid.py:242`, `build.py:93` |
| `hole_bore_mm` | `hole_diameter` | 1.0→1.25 | `build.py:180`, `connectors.py` |

Every gap — `wall_floor`, `wall_halo`, `via_halo`, `edge_inflate` **and**
`pocket_margin` — scales with `buffer`, so the channel-to-recess wall is the
same thickness as any other wall. `pocket_clearance` remains only the device
drop-in fit tolerance.

**Finding — buffer vs breadboard pitch, and the resolution.** Folding the full
`buffer` into the pocket margin (so the recess wall is a real wall, not a
knife-edge) makes the cramped 68×50 reference layouts unroutable: the inflated
pocket keep-outs choke the 2.54 mm-pitch pin-approach corridors, so routing only
succeeds if `buffer` collapses back to ~0.2–0.4 — re-thinning the wall. The fix
is to **size the plate to the routing, not the reverse**: spread the devices so
the corridors reopen at the generous default. Both production boards then route
at `buffer=1.0` and pass `wall_floor` cleanly with zero violations
(`i2c_midline_no_oled` on 78×50; `i2c_midline_sensors` on 98×68 — the OLED's
extra trunk branch needs the larger plate). The cramped reference boards
(`i2c_starter`, `i2c_sensors_flipped`) were retired.

**Lifecycle:** constructed once per `build_board` / `route_board` call; immutable
thereafter. No persistence, no migration — it is recomputed from the spec each
render.

### Connector (catalog entity)

Off-the-shelf header descriptor in `CONNECTOR_REGISTRY`. *This feature adds bore
derivation + seating geometry.*

| Field | Type | Constraint | Change |
|-------|------|------------|--------|
| `name` | str | | |
| `pin_count` | int | `> 0` | |
| `pitch` | float | `> 0` | should equal board `pitch` (2.54) |
| `drill_diameter` | float | `> 0` | **derive from `hole_bore_mm`** (was hardcoded 1.0 ×3) |
| `lead_in_depth` | float | `>= 0` | **new** — countersink depth at bore top (FR-4) |
| `lead_in_angle` | float | | **new** — chamfer angle for self-guiding |
| `grip_diameter` | float | `> 0` | **new** — undersized/tapered lower bore for grip (FR-12) |
| `body_width` / `body_depth` / `standard_height` | float | `> 0` | unchanged |

### Routing geometry (emitted, not stored)

The router emits these into the builder; they are not persisted. Listed for
completeness because Phase 5 changes their shape.

| Type | Fields | Phase-5 change |
|------|--------|----------------|
| `WireSegment` | `start: Point2D, end: Point2D, layer: int` | diagonals become exact 45° vectors, not cell staircases |
| `Via` | `position: Point2D, diameter: float` | diameter = `hole_bore_mm` (unified) |
| `SignalPath` | `name: str, elements: [WireSegment\|Via]` | synced chamfers inserted for adjacent bus pairs |

## Derivation Invariants (must hold after consolidation)

1. Every clearance read anywhere equals its `ResolvedDims` accessor — grep must
   find **zero** re-derivations of `channel_width + min_wall_thickness …`
   outside `ResolvedDims`.
2. `via_diameter` defaults equal to `hole_diameter` unless explicitly overridden.
3. `wall_halo_mm` is identical in the blocking pass and the align rebuild (one
   helper, two callers).
4. Phase 1: all six accessors reproduce the pre-change numeric values exactly.
