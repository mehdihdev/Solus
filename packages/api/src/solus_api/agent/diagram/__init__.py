"""Wiring diagrams from the graph (SOLUSDEV-252 S5): pure model → pure SVG.

Nothing here reads a database or names a vendor. `build.py` turns a bounded
`Neighborhood` (+ the robot's `HardwareConfig`) into a `Diagram`; `svg.py` lays it
out deterministically. A pin is `known` only when the graph or the config names it.
"""
