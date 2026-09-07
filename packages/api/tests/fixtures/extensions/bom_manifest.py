"""The BOM widget's manifest as the ST4/ST5 suites seed it (SOLUSDEV-246)."""

from __future__ import annotations

from typing import Any

BOM_MANIFEST: dict[str, Any] = {
    "schema_version": 2,
    "extension": {
        "id": "bom",
        "name": "BOM",
        "version": "0.1.0",
        "publisher": "Solus",
        "summary": "Every part in the robot, raw materials and purchases — one row per part.",
        "requires": [["eda", "cad"]],
    },
    "views": {"page": {"entry": "page.html", "icon": "icon.svg", "label": "BOM"}},
    "backend": {"capability": "bom", "routes": True},
    "graph": {"kinds": [{"name": "item", "domain": "project"}]},
    "tools": {"names": ["add_item"]},
    "settings": {
        "fields": [
            {"key": "preferred_suppliers", "type": "string", "label": "Preferred suppliers"},
            {"key": "cost_target", "type": "number", "label": "Cost target", "min": 0},
            {
                "key": "max_items",
                "type": "number",
                "label": "Hand-added rows to keep",
                "min": 1,
                "max": 20000,
                "default": 2000,
            },
            {
                "key": "currency",
                "type": "select",
                "label": "Currency",
                "options": ["USD", "EUR", "GBP"],
                "default": "USD",
            },
        ]
    },
    "store": {"overview": "OVERVIEW.md"},
}

__all__ = ["BOM_MANIFEST"]
