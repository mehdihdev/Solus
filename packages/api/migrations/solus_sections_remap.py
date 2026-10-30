"""SOLUSDEV-320: frozen data step behind a32000000003 (loaded by path, never imported).

Five `.solus` sections become seven with subsections. Every `solus_entries` row, deleted
ones included, moves per `OLD_TO_NEW`; the `section`/`subsection` attrs of entry nodes and
of the edges touching them follow; the four retired `solus_section` nodes and their
`contains` edges are soft-deleted with `attrs.retired_by` so the downgrade can find them.
Entry node kinds follow `entry_node_kind` (`details` notes become `solus_goal`; a hardware
CONFIG without a subject becomes `solus_note`). The downgrade mirrors all of it and retires
the tree the new world built (new-only section nodes, every subsection node, their
`contains` edges) under `retired_by = "<rev>:downgrade"`, which a re-upgrade un-retires.
Totals per old section are compared before and after; a mismatch raises.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

logger = logging.getLogger("solus.migrations.solus_sections_remap")

REVISION = "a32000000003"
OLD_TO_NEW: dict[str, tuple[str, str | None]] = {
    "hardware": ("environment", "hardware"),
    "code": ("environment", "software"),
    "docs": ("documentation", "guides"),
    "details": ("goals", "general"),
    "errors": ("errors", None),
}
RETIRED_SECTIONS = ("hardware", "details", "docs", "code")
NEW_ONLY_SECTIONS = ("goals", "constraints", "documentation", "environment", "members", "history")
ENTRY_NODE_KINDS = ("document", "hardware_config", "solus_note", "solus_error", "solus_goal")
DOWNGRADE = f"{REVISION}:downgrade"


def _in(name: str) -> sa.BindParameter[Any]:
    return sa.bindparam(name, expanding=True)


_COUNT_OLD = sa.text(
    "SELECT section, count(*) FROM solus_entries WHERE section IN :olds GROUP BY section"
).bindparams(_in("olds"))
_COUNT_NEW = sa.text(
    "SELECT section, subsection, count(*) FROM solus_entries GROUP BY section, subsection"
)
_MOVE = sa.text("UPDATE solus_entries SET section = :new, subsection = :sub WHERE section = :old")
_RESTORE = sa.text(
    "UPDATE solus_entries SET section = :old, subsection = NULL "
    "WHERE section = :new AND subsection IS NOT DISTINCT FROM :sub"
)
_NODE_ATTRS = sa.text(
    "UPDATE graph_entity n SET attrs = coalesce(n.attrs, '{}'::jsonb) || "
    "jsonb_build_object('section', e.section, 'subsection', e.subsection) "
    "FROM solus_entries e WHERE n.id = e.entity_id AND n.kind IN :kinds"
).bindparams(_in("kinds"))
_NODE_ATTRS_BACK = sa.text(
    "UPDATE graph_entity n SET attrs = (coalesce(n.attrs, '{}'::jsonb) || "
    "jsonb_build_object('section', e.section)) - 'subsection' "
    "FROM solus_entries e WHERE n.id = e.entity_id AND n.kind IN :kinds"
).bindparams(_in("kinds"))
_EDGE_ATTRS = sa.text(
    "UPDATE graph_edge g SET attrs = coalesce(g.attrs, '{}'::jsonb) || "
    "jsonb_build_object('section', e.section, 'subsection', e.subsection) "
    "FROM solus_entries e WHERE (g.src_id = e.entity_id OR g.dst_id = e.entity_id) "
    "AND g.attrs->>'section' IN :retired"
).bindparams(_in("retired"))
_EDGE_ATTRS_BACK = sa.text(
    "UPDATE graph_edge g SET attrs = (coalesce(g.attrs, '{}'::jsonb) || "
    "jsonb_build_object('section', e.section)) - 'subsection' "
    "FROM solus_entries e WHERE (g.src_id = e.entity_id OR g.dst_id = e.entity_id) "
    "AND g.attrs ? 'subsection' AND e.section IN :olds"
).bindparams(_in("olds"))
_RETIRE_NODES = sa.text(
    "UPDATE graph_entity SET deleted_at = now(), attrs = coalesce(attrs, '{}'::jsonb) || "
    "jsonb_build_object('retired_by', CAST(:rev AS text)) WHERE kind = 'solus_section' "
    "AND attrs->>'section' IN :retired AND deleted_at IS NULL"
).bindparams(_in("retired"))
_RETIRE_NEW_TREE = sa.text(
    "UPDATE graph_entity SET deleted_at = now(), attrs = coalesce(attrs, '{}'::jsonb) || "
    "jsonb_build_object('retired_by', CAST(:rev AS text)) WHERE deleted_at IS NULL "
    "AND (kind = 'solus_subsection' OR (kind = 'solus_section' AND attrs->>'section' IN :new))"
).bindparams(_in("new"))
_RETIRE_EDGES = sa.text(
    "UPDATE graph_edge g SET deleted_at = now(), attrs = coalesce(g.attrs, '{}'::jsonb) || "
    "jsonb_build_object('retired_by', CAST(:rev AS text)) FROM graph_entity s "
    "WHERE s.kind IN ('solus_section', 'solus_subsection') AND s.attrs->>'retired_by' = :rev "
    "AND (g.src_id = s.id OR g.dst_id = s.id) "
    "AND g.relation_type = 'contains' AND g.deleted_at IS NULL"
)
_UNRETIRE_NODES = sa.text(
    "UPDATE graph_entity SET deleted_at = NULL, attrs = attrs - 'retired_by' "
    "WHERE attrs->>'retired_by' = :rev"
)
_UNRETIRE_EDGES = sa.text(
    "UPDATE graph_edge SET deleted_at = NULL, attrs = attrs - 'retired_by' "
    "WHERE attrs->>'retired_by' = :rev"
)
_NODE_KIND = sa.text(
    "UPDATE graph_entity n SET kind = :to FROM solus_entries e "
    "WHERE n.id = e.entity_id AND n.kind = :frm AND e.section = :section"
)
_UNBOUND_CONFIG_KIND = sa.text(
    "UPDATE graph_entity n SET kind = :to FROM solus_entries e "
    "WHERE n.id = e.entity_id AND n.kind = :frm AND e.section = :section "
    "AND e.kind = 'config' AND e.configured_entity_id IS NULL"
)


def _key(section: str, subsection: str | None) -> str:
    return f"{section}/{subsection}" if subsection else section


def _cells(connection: Any) -> dict[str, int]:
    return {
        _key(str(section), subsection): int(n)
        for section, subsection, n in connection.execute(_COUNT_NEW).all()
    }


def _rewrite_kinds(connection: Any, *, forward: bool) -> None:
    """Entry node kinds follow entry_node_kind() in the world the rows now live in."""
    goal, note, config = "solus_goal", "solus_note", "hardware_config"
    if forward:
        connection.execute(_NODE_KIND, {"frm": note, "to": goal, "section": "goals"})
        connection.execute(
            _UNBOUND_CONFIG_KIND, {"frm": config, "to": note, "section": "environment"}
        )
    else:
        connection.execute(_NODE_KIND, {"frm": goal, "to": note, "section": "details"})
        connection.execute(_UNBOUND_CONFIG_KIND, {"frm": note, "to": config, "section": "hardware"})


def remap_sections(connection: Any) -> dict[str, Any]:
    olds = list(OLD_TO_NEW)
    connection.execute(_UNRETIRE_NODES, {"rev": DOWNGRADE})  # a re-upgrade after a rollback
    connection.execute(_UNRETIRE_EDGES, {"rev": DOWNGRADE})
    before = {
        str(section): int(n) for section, n in connection.execute(_COUNT_OLD, {"olds": olds}).all()
    }
    for old, (new, sub) in OLD_TO_NEW.items():
        if (new, sub) != (old, None):
            connection.execute(_MOVE, {"old": old, "new": new, "sub": sub})
    connection.execute(_NODE_ATTRS, {"kinds": list(ENTRY_NODE_KINDS)})
    connection.execute(_EDGE_ATTRS, {"retired": list(RETIRED_SECTIONS)})
    _rewrite_kinds(connection, forward=True)
    nodes = connection.execute(
        _RETIRE_NODES, {"rev": REVISION, "retired": list(RETIRED_SECTIONS)}
    ).rowcount
    edges = connection.execute(_RETIRE_EDGES, {"rev": REVISION}).rowcount
    after = _cells(connection)
    for old, n in before.items():
        moved = after.get(_key(*OLD_TO_NEW[old]), 0)
        if moved != n:
            raise RuntimeError(f"section {old!r}: {n} rows before, {moved} after the remap")
    counts = {
        "before": before,
        "after": after,
        "section_nodes_retired": int(nodes or 0),
        "edges_retired": int(edges or 0),
    }
    logger.info(".solus sections remapped %s", counts)
    return counts


def restore_sections(connection: Any) -> dict[str, Any]:
    """The downgrade: the reverse map; rows in cells the old world cannot hold refuse it."""
    reversible = {_key(new, sub) for new, sub in OLD_TO_NEW.values()}
    stray = {cell: n for cell, n in _cells(connection).items() if cell not in reversible}
    if stray:
        raise RuntimeError(f".solus rows live in cells the five-section world cannot hold: {stray}")
    for old, (new, sub) in OLD_TO_NEW.items():
        if (new, sub) != (old, None):
            connection.execute(_RESTORE, {"old": old, "new": new, "sub": sub})
    connection.execute(_NODE_ATTRS_BACK, {"kinds": list(ENTRY_NODE_KINDS)})
    connection.execute(_EDGE_ATTRS_BACK, {"olds": list(OLD_TO_NEW)})
    _rewrite_kinds(connection, forward=False)
    tree = connection.execute(
        _RETIRE_NEW_TREE, {"rev": DOWNGRADE, "new": list(NEW_ONLY_SECTIONS)}
    ).rowcount
    connection.execute(_RETIRE_EDGES, {"rev": DOWNGRADE})
    nodes = connection.execute(_UNRETIRE_NODES, {"rev": REVISION}).rowcount
    edges = connection.execute(_UNRETIRE_EDGES, {"rev": REVISION}).rowcount
    return {
        "section_nodes_restored": int(nodes or 0),
        "edges_restored": int(edges or 0),
        "tree_nodes_retired": int(tree or 0),
    }
