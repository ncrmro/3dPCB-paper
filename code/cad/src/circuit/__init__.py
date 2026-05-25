"""Declarative circuit substrate spec (Pydantic + YAML).

Each substrate variant is described as a `CircuitSpec` — a stack of
Z-axis levels (each carrying an axis-aligned perimeter), the devices
that sit in those levels, and per-signal `Route`s authored as
waypoint lists. `load_spec` validates a YAML file into a CircuitSpec;
`build_substrate` turns it into an AnchorSCAD shape using the shared
`_cut_segment` / `_cut_via` helpers in `vitamins.substrate`.
"""

from circuit.build import build_substrate, route_to_signal_path
from circuit.loader import load_spec
from circuit.models import (
    CircuitSpec,
    Device,
    Level,
    Rect,
    Route,
    Waypoint as SpecWaypoint,
)

__all__ = [
    "CircuitSpec",
    "Device",
    "Level",
    "Rect",
    "Route",
    "SpecWaypoint",
    "build_substrate",
    "load_spec",
    "route_to_signal_path",
]
