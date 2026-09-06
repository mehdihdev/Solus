"""The STORE ST1 fixture bundle's backend (SOLUSDEV-246) — id ``fixture-bundle``.

All five parts in one small package so the acceptance path is real: a page view
(in the bundle zip), routes (`routes.py`), a graph kind (`ext:fixture-bundle:note`),
two SOL tools (`tools.py`, one of them confirmation-gated), and the `[ext.fixture-bundle]`
section read through `widgets.solus_config`. The bundle folder itself lives at
``packages/shared-types/fixtures/extension-bundles/fixture-bundle/``.
"""

from __future__ import annotations

from solus_api.widgets.capability import DeclaredKind, WidgetCapability
from solus_api.widgets.fixture_bundle.routes import router
from solus_api.widgets.fixture_bundle.tools import build_add_note, build_clear_notes

SLUG = "fixture-bundle"

CAPABILITY = WidgetCapability(
    id=SLUG,
    kinds=(DeclaredKind(name="note", domain="code"),),
    tools={"add_note": build_add_note, "clear_notes": build_clear_notes},
    router=router,
)

__all__ = ["CAPABILITY", "SLUG"]
