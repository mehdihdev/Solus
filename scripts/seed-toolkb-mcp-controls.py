#!/usr/bin/env python3
"""Seed the tool-knowledge entries SOL's write tools act on (SOLUSDEV-251 / I4).

Tool knowledge is a GLOBAL, tenant-free table (ADR-033). The entries below are
vendor-documentation facts about the UI control each MCP write tool operates —
the KiCad Symbol Properties dialog, Onshape's Variable Table and Feature list —
admitted through the guard's docs path (which publishes directly because the
source is the vendor's own documentation). Idempotent: an existing live entry is
returned unchanged. Run once per database:

    uv run python scripts/seed-toolkb-mcp-controls.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "api" / "src"))

ENTRIES = [
    (
        {
            "tool": "kicad",
            "version_range": ">=8.0 <10.0",
            "surface": "dialog",
            "control_id": "kicad.eeschema.edit_symbol_properties",
            "label": "Symbol Properties",
            "effect": "modify_feature",
            "description": (
                "Edits one placed symbol's fields — Reference, Value, Footprint and custom "
                "properties — in the schematic editor; the change is saved with the schematic."
            ),
            "provenance": "vendor_docs",
        },
        "https://docs.kicad.org/9.0/en/eeschema/eeschema.html",
    ),
    (
        {
            "tool": "onshape",
            "version_range": ">=1.0 <2.0",
            "surface": "panel",
            "control_id": "onshape.partstudio.variable_table",
            "label": "Variable Table",
            "effect": "modify_feature",
            "description": (
                "A Part Studio's named variables; writing the table REPLACES it, so every "
                "variable must be sent back, not only the one that changed."
            ),
            "provenance": "vendor_docs",
        },
        "https://cad.onshape.com/help/Content/variable.htm",
    ),
    (
        {
            "tool": "onshape",
            "version_range": ">=1.0 <2.0",
            "surface": "panel",
            "control_id": "onshape.partstudio.feature_list",
            "label": "Feature list",
            "effect": "create_feature",
            "description": (
                "The ordered features of a Part Studio; adding or editing one regenerates "
                "the studio at that feature's position in the list."
            ),
            "provenance": "vendor_docs",
        },
        "https://cad.onshape.com/help/Content/featurelist.htm",
    ),
]


async def seed() -> int:
    from dotenv import load_dotenv
    from solus_api.core.config import Settings
    from solus_api.core.db import build_engine, build_sessionmaker
    from solus_api.toolkb.guard import IngestContext, IngestRejectedError, ingest
    from solus_api.toolkb.schema import AcquisitionMethod

    load_dotenv(REPO_ROOT / ".env")
    settings = Settings(_env_file=REPO_ROOT / ".env")  # type: ignore[call-arg]
    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)
    seeded = 0
    async with sessionmaker() as session:
        for entry, doc_url in ENTRIES:
            try:
                row = await ingest(
                    session,
                    entry=entry,
                    ctx=IngestContext(acquired_via=AcquisitionMethod.DOCS, doc_url=doc_url),
                )
            except IngestRejectedError as exc:
                print(f"REFUSED {entry['control_id']}: {exc}")
                continue
            print(f"{row.status.value:9} {entry['tool']:8} {entry['control_id']}")
            seeded += 1
        await session.commit()
    await engine.dispose()
    return 0 if seeded == len(ENTRIES) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(seed()))
