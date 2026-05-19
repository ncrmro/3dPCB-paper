"""Routing helpers — collision checks + greedy hint optimiser.

The collision primitives in `collisions` are pure axis-aligned bbox
math reused by both the netlist test gate and the optimiser; the
optimiser in `optimiser` is a parameter-grid enumerator over the
`RoutingHint` knobs that picks the shortest collision-free hint set
per net.
"""
