"""The BOM widget's backend (SOLUSDEV-246, STORE ST4) — id ``bom``.

Every part in the robot, raw materials and anything purchased, as ONE view over
canonical parts: a part in CAD, the schematic and the purchase list is one row
(`rows.py`), lifecycle state per row (R5), supplier preferences and cost targets
from the bundle's settings / repo `[ext.bom]` section, CSV export (`routes.py`),
and a SOL tool for planned rows (`tools.py`). The bundle folder lives at
``packages/api/src/solus_api/extensions/bundled/bom/``.
"""

from __future__ import annotations

from solus_api.widgets.bom.routes import router
from solus_api.widgets.bom.tools import build_add_item
from solus_api.widgets.capability import DeclaredKind, WidgetCapability

SLUG = "bom"

CAPABILITY = WidgetCapability(
    id=SLUG,
    kinds=(DeclaredKind(name="item", domain="project"),),
    tools={"add_item": build_add_item},
    router=router,
)

__all__ = ["CAPABILITY", "SLUG"]
