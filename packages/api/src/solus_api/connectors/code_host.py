"""Shared code-host → graph mapping (W0-08), used by GitHub and GitLab.

Both code-host connectors land the same entity shapes: a `code_repo` root,
`code_module` directories, `code_file` blobs — and committed design exports
(Gerber/STEP/netlist/SPICE fabrication/CAD outputs checked in next to firmware)
surfaced as cross-domain `design_export` entities for the EDA/CAD connectors to
parse. Keeping the mapping here means the roster can't drift per host.

Everything is pure (path in, entity out) per the checker/analyzer rule.
"""

from __future__ import annotations

from typing import Any, Final

from solus_api.connectors.contracts import Domain, EntityOut
from solus_api.widgets.solus_config import (
    MAX_PROJECT_TOML_BYTES,
    SOLUS_CONFIG_KIND,
    SOLUS_CONFIG_PATH,
    parse_project_toml_ext,
)

REPO_ROOT_KEY: Final = ":repo"

# Committed design-export detection (W0-08). Lowercased extension -> (kind, domain).
DESIGN_EXPORTS: Final[dict[str, tuple[str, Domain]]] = {
    # Gerber fabrication outputs.
    ".gbr": ("gerber", Domain.ELECTRICAL),
    ".ger": ("gerber", Domain.ELECTRICAL),
    ".gtl": ("gerber", Domain.ELECTRICAL),
    ".gbl": ("gerber", Domain.ELECTRICAL),
    ".gto": ("gerber", Domain.ELECTRICAL),
    ".gbo": ("gerber", Domain.ELECTRICAL),
    ".gts": ("gerber", Domain.ELECTRICAL),
    ".gbs": ("gerber", Domain.ELECTRICAL),
    ".gtp": ("gerber", Domain.ELECTRICAL),
    ".gbp": ("gerber", Domain.ELECTRICAL),
    ".gko": ("gerber", Domain.ELECTRICAL),
    ".drl": ("gerber", Domain.ELECTRICAL),
    ".xln": ("gerber", Domain.ELECTRICAL),
    ".gm1": ("gerber", Domain.ELECTRICAL),
    # STEP CAD models.
    ".step": ("step", Domain.MECHANICAL),
    ".stp": ("step", Domain.MECHANICAL),
    # Netlists.
    ".net": ("netlist", Domain.ELECTRICAL),
    ".netlist": ("netlist", Domain.ELECTRICAL),
    ".cnl": ("netlist", Domain.ELECTRICAL),
    # SPICE decks.
    ".cir": ("spice", Domain.ELECTRICAL),
    ".sp": ("spice", Domain.ELECTRICAL),
    ".spice": ("spice", Domain.ELECTRICAL),
    ".subckt": ("spice", Domain.ELECTRICAL),
    ".lib": ("spice", Domain.ELECTRICAL),
}


def basename(path: str) -> str:
    """The trailing path segment, or the path itself when it has no slash."""
    return path.rsplit("/", 1)[-1] if "/" in path else path


def parent_key(path: str, known_dirs: set[str]) -> str:
    """The graph parent of `path`: its directory if that directory is an emitted
    entity, otherwise the repo root. Guards against intermediate trees a host
    elides — relations only ever point at entities we actually land."""
    if "/" not in path:
        return REPO_ROOT_KEY
    parent = path.rsplit("/", 1)[0]
    return parent if parent in known_dirs else REPO_ROOT_KEY


def design_export_for(path: str) -> tuple[str, Domain] | None:
    """Return (export_kind, domain) if `path` is a recognised design export."""
    lowered = path.lower()
    dot = lowered.rfind(".")
    if dot == -1:
        return None
    return DESIGN_EXPORTS.get(lowered[dot:])


def solus_config_blob(tree: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The `.solus/project.toml` tree item, if the repo commits one (SOLUSDEV-246)."""
    for item in tree:
        if item.get("path") == SOLUS_CONFIG_PATH and item.get("type") == "blob":
            return item
    return None


def solus_config_too_large(item: dict[str, Any]) -> bool:
    """Decided from the tree's declared size, so an oversized file is never
    fetched. A missing or non-integer size fails CLOSED — the tree is untrusted
    input and "unknown" is not "small enough"."""
    size = item.get("size")
    return not isinstance(size, int) or isinstance(size, bool) or size > MAX_PROJECT_TOML_BYTES


def solus_config_entity(text: str) -> tuple[EntityOut | None, list[str]]:
    """Parse the committed `.solus/project.toml` into ONE `solus_config` entity
    (ADR-035 §4 as amended; widget-bundles.md §6). Invalid TOML → no entity and
    the problem; a valid file always lands, even with no `[ext]` table."""
    parsed = parse_project_toml_ext(text)
    if parsed.fatal:
        return None, parsed.problems
    entity = EntityOut(
        source_key=SOLUS_CONFIG_PATH,
        type=SOLUS_CONFIG_KIND,
        domain=Domain.CODE,
        name="project.toml",
        properties={"path": SOLUS_CONFIG_PATH, "ext": parsed.tables},
    )
    return entity, parsed.problems


def module_entity(path: str) -> EntityOut:
    return EntityOut(
        source_key=path,
        type="code_module",
        domain=Domain.CODE,
        name=basename(path),
    )


def file_entity(path: str, item: dict[str, Any]) -> EntityOut:
    export = design_export_for(path)
    if export is not None:
        kind, domain = export
        return EntityOut(
            source_key=path,
            type="design_export",
            domain=domain,
            name=basename(path),
            properties={
                "export_kind": kind,
                "path": path,
                "size": item.get("size"),
                "sha": item.get("sha"),
            },
        )
    return EntityOut(
        source_key=path,
        type="code_file",
        domain=Domain.CODE,
        name=basename(path),
        properties={"size": item.get("size"), "sha": item.get("sha"), "path": path},
    )
