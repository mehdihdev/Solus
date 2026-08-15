"""SOLUS-TU-06 — vendor control catalog + doc-domain allowlist.

This is the "allowlist at the source" that docs/contracts/tool-knowledge.md
demands of the ingestion guard: the CTR-05 patterns are a net UNDER this, never
the filter. A control is "known vendor surface" iff vendor documentation says
so — either a curated seed file here, or a previously PUBLISHED row whose
provenance is vendor_docs. The probe (api_geometry) and visual paths may only
attach to known controls when their source could mix in customer content.

`VENDOR_DOC_DOMAINS` decides what counts as vendor documentation. Entries are
``host`` or ``host/path-prefix``; matching is exact-host (never suffix — that
would admit ``docs.kicad.org.attacker.example``) and https-only. Curation of
both lists is a human sign-off item (Phase 0 §7.5).
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.contracts.tool_knowledge import Provenance, ToolFamily
from solus_api.toolkb.schema import KnowledgeStatus, ToolKnowledgeEntry

logger = logging.getLogger("solus.toolkb")

_CATALOG_DIR: Final = Path(__file__).resolve().parent / "catalog"

#: What counts as official vendor documentation, per tool. host or host/prefix.
VENDOR_DOC_DOMAINS: Final[dict[ToolFamily, tuple[str, ...]]] = {
    ToolFamily.FUSION: ("help.autodesk.com",),
    ToolFamily.ONSHAPE: ("cad.onshape.com/help", "learn.onshape.com"),
    ToolFamily.SOLIDWORKS: ("help.solidworks.com",),
    ToolFamily.AUTOCAD: ("help.autodesk.com",),
    # docs.kicad.org = the manuals; gitlab.com/kicad/code/kicad = the GPL source
    # whose TOOL_ACTION defs are the authoritative machine-precise command
    # catalog (TU-02). Both are official vendor sources. (Curation: Phase 0 §7.5.)
    ToolFamily.KICAD: ("docs.kicad.org", "gitlab.com/kicad/code/kicad"),
    ToolFamily.ALTIUM: ("www.altium.com/documentation",),
    ToolFamily.SPICE: ("ngspice.sourceforge.io",),
}


def is_vendor_doc_url(tool: ToolFamily, url: str) -> bool:
    """True iff ``url`` is official vendor documentation for ``tool``."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    for entry in VENDOR_DOC_DOMAINS[tool]:
        host, _, prefix = entry.partition("/")
        if parts.hostname != host:
            continue
        # Prefix matches end at a path-segment boundary — a bare startswith
        # admits /helpdesk-upload/… under a /help prefix (review finding).
        path = parts.path.lstrip("/")
        if not prefix or path == prefix or path.startswith(prefix + "/"):
            return True
    return False


@lru_cache(maxsize=len(ToolFamily))
def _seed_controls(tool: ToolFamily) -> frozenset[str]:
    seed_file = _CATALOG_DIR / f"{tool.value}.json"
    if not seed_file.exists():
        return frozenset()
    controls = json.loads(seed_file.read_text())["controls"]
    return frozenset(controls)


async def is_known_vendor_control(session: AsyncSession, tool: ToolFamily, control_id: str) -> bool:
    """Seed catalog ∪ published vendor_docs rows — nothing else is 'known'."""
    if control_id in _seed_controls(tool):
        return True
    known = await session.scalar(
        select(
            exists().where(
                ToolKnowledgeEntry.deleted_at.is_(None),
                ToolKnowledgeEntry.status == KnowledgeStatus.PUBLISHED,
                ToolKnowledgeEntry.provenance == Provenance.VENDOR_DOCS,
                ToolKnowledgeEntry.tool == tool,
                ToolKnowledgeEntry.control_id == control_id,
            )
        )
    )
    return bool(known)
