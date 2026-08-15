"""A hand-built mechanical CAD IR fixture (SOLUS-CAD-00).

Mirrors the three-level assembly the OCCT XDE round-trip test builds, so the
mapping tests and the parser tests describe the SAME design:

    Bracket (assembly)
    ├── BasePlate            @ (0, 0, 0)
    └── PegPair (assembly)   @ (0, 0, 0)
        ├── Peg[0]           @ (5, 8, 5)
        └── Peg[1]           @ (20, 8, 5)

`Peg` is instanced twice — the case that proves occurrence keys stay unique
when one product appears more than once (W0-08 §6.1 instance-vs-product
identity).
"""

from __future__ import annotations

from solus_api.connectors.mechanical import CadModel, CadNode

BRACKET = CadModel(
    nodes=(
        CadNode(key="Bracket", name="Bracket", is_assembly=True),
        CadNode(
            key="Bracket/BasePlate",
            name="BasePlate",
            is_assembly=False,
            parent_key="Bracket",
            placement=(0.0, 0.0, 0.0),
            part_number="AL-6061-PLATE",
            material="Aluminium 6061",
        ),
        CadNode(
            key="Bracket/PegPair",
            name="PegPair",
            is_assembly=True,
            parent_key="Bracket",
            placement=(0.0, 0.0, 0.0),
        ),
        CadNode(
            key="Bracket/PegPair/Peg[0]",
            name="Peg",
            is_assembly=False,
            parent_key="Bracket/PegPair",
            placement=(5.0, 8.0, 5.0),
            part_number="DIN-912-M4",
        ),
        CadNode(
            key="Bracket/PegPair/Peg[1]",
            name="Peg",
            is_assembly=False,
            parent_key="Bracket/PegPair",
            placement=(20.0, 8.0, 5.0),
            part_number="DIN-912-M4",
        ),
    )
)
