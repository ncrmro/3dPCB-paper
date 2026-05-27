"""Route experiment helpers — pure-Python (no AnchorSCAD).

Two small APIs:

  - `Waypoint` / `waypoints_to_path` lets a route experiment author a
    `SignalPath` as a list of `(x, y, layer)` checkpoints instead of
    a wall of `WireSegment(...)` calls. See `router.paths`.
  - `RouteScore` / `score_paths` scores a set of paths so two
    candidate topologies can be compared. See `router.score`.
"""

from router.paths import Waypoint, waypoints_to_path
from router.score import RouteScore, score_paths

__all__ = [
    "RouteScore",
    "Waypoint",
    "score_paths",
    "waypoints_to_path",
]
