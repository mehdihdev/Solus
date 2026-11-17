"""SOLUSDEV-326: frozen data step behind a32600000001 (loaded by path, never imported).

A robot contains its parts directly. A `robot_category` node is owned when a manual `contains`
edge reaches it from a manual Physical Robot root of its project, that root is its
`attrs.robot_id` and its key is one of the seven (the old `_container_ids` rule, live or
deleted). Every manual source-less `contains` edge leaving an owned category, live and
tombstoned, moves to the robot root and keeps the label: `attrs.moved_from`, `moved_by`,
`category`. A live edge moves only when its category owned live and its robot does not already
hold the part live (directly or through another category); every live `contains` edge still
touching a category afterwards is retired (`deleted_at`, `attrs.retired_by`), and so is every
live category node: robot → category edges, duplicates and impostors (their parts become
honestly unassigned). Manual source-less parts a live robot now holds gain `attrs.robot_id`.
Post-checks raise unless no live category or category `contains` edge remains and the distinct
owned (robot, part) pairs are unchanged. A re-run changes nothing. One-way: the downgrade
restores nothing; the tags keep what a manual recovery needs.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa

logger = logging.getLogger("solus.migrations.robot_categories_retire")

REVISION = "a32600000001"
KEYS = ("sensors", "actuators", "controllers", "end_effectors", "power", "structure", "wiring")

#: category id → (robot id, key, owned live). The robot is pinned by `attrs.robot_id`.
_OWNERS = sa.text(
    "SELECT c.id, r.id, c.attrs->>'category', "
    "bool_or(o.deleted_at IS NULL) AND c.deleted_at IS NULL AND r.deleted_at IS NULL "
    "FROM graph_entity c JOIN graph_edge o ON o.dst_id = c.id "
    "JOIN graph_entity r ON r.id = o.src_id "
    "WHERE c.kind = 'robot_category' AND c.origin = 'manual' AND c.source_id IS NULL "
    "AND c.attrs->>'category' IN :keys AND c.attrs->>'robot_id' = r.id::text "
    "AND r.kind = 'physical_robot' AND r.origin = 'manual' AND r.source_id IS NULL "
    "AND r.project_id = c.project_id AND o.project_id = c.project_id "
    "AND o.relation_type = 'contains' AND o.origin = 'manual' AND o.source_id IS NULL "
    "GROUP BY c.id, r.id"
).bindparams(sa.bindparam("keys", expanding=True))
_CATEGORY_EDGES = sa.text(
    "SELECT g.id, g.src_id, g.dst_id, g.deleted_at IS NULL FROM graph_edge g "
    "JOIN graph_entity c ON c.id = g.src_id WHERE c.kind = 'robot_category' "
    "AND g.relation_type = 'contains' AND g.origin = 'manual' AND g.source_id IS NULL "
    "AND g.attrs->>'retired_by' IS DISTINCT FROM :rev ORDER BY g.created_at, g.id"
)
_HELD = sa.text(
    "SELECT g.src_id, g.dst_id FROM graph_edge g JOIN graph_entity r ON r.id = g.src_id "
    "WHERE r.kind = 'physical_robot' AND g.relation_type = 'contains' "
    "AND g.origin = 'manual' AND g.source_id IS NULL AND g.deleted_at IS NULL"
)
_MOVE = sa.text(
    "UPDATE graph_edge SET src_id = :robot, updated_at = now(), "
    "attrs = coalesce(attrs, '{}'::jsonb) || jsonb_build_object('moved_from', "
    "CAST(:category AS text), 'moved_by', CAST(:rev AS text), 'category', CAST(:key AS text)) "
    "WHERE id = :id"
)
_RETIRE_EDGES = sa.text(
    "UPDATE graph_edge g SET deleted_at = now(), updated_at = now(), "
    "attrs = coalesce(g.attrs, '{}'::jsonb) || jsonb_build_object('retired_by', "
    "CAST(:rev AS text)) FROM graph_entity c WHERE c.kind = 'robot_category' "
    "AND (g.src_id = c.id OR g.dst_id = c.id) AND g.relation_type = 'contains' "
    "AND g.deleted_at IS NULL"
)
_RETIRE_CATEGORIES = sa.text(
    "UPDATE graph_entity SET deleted_at = now(), updated_at = now(), "
    "attrs = coalesce(attrs, '{}'::jsonb) || jsonb_build_object('retired_by', "
    "CAST(:rev AS text)) WHERE kind = 'robot_category' AND deleted_at IS NULL"
)
_BACKFILL = sa.text(
    "UPDATE graph_entity p SET updated_at = now(), attrs = coalesce(p.attrs, '{}'::jsonb) || "
    "jsonb_build_object('robot_id', r.id::text) FROM graph_edge g "
    "JOIN graph_entity r ON r.id = g.src_id WHERE g.dst_id = p.id "
    "AND g.relation_type = 'contains' AND g.origin = 'manual' AND g.source_id IS NULL "
    "AND g.deleted_at IS NULL AND r.kind = 'physical_robot' AND r.origin = 'manual' "
    "AND r.source_id IS NULL AND r.deleted_at IS NULL AND r.project_id = p.project_id "
    "AND p.origin = 'manual' AND p.source_id IS NULL AND p.deleted_at IS NULL "
    "AND p.kind NOT IN ('physical_robot', 'robot_category') AND p.attrs->>'robot_id' IS NULL"
)
#: Distinct live (robot, part) pairs under the category-era rule: a live root owns what it
#: contains directly and what its live, owned categories contain. With no live category left
#: this is the new rule, so one query serves before and after.
_OWNED_PAIRS = sa.text(
    "WITH roots AS (SELECT id FROM graph_entity WHERE kind = 'physical_robot' "
    "AND origin = 'manual' AND source_id IS NULL AND deleted_at IS NULL), "
    "containers AS (SELECT id AS container, id AS robot FROM roots UNION "
    "SELECT c.id, r.id FROM graph_entity c JOIN graph_edge o ON o.dst_id = c.id "
    "JOIN roots r ON r.id = o.src_id WHERE c.kind = 'robot_category' AND c.origin = 'manual' "
    "AND c.source_id IS NULL AND c.deleted_at IS NULL AND c.attrs->>'category' IN :keys "
    "AND c.attrs->>'robot_id' = r.id::text AND o.project_id = c.project_id "
    "AND o.relation_type = 'contains' AND o.origin = 'manual' AND o.source_id IS NULL "
    "AND o.deleted_at IS NULL) "
    "SELECT count(*) FROM (SELECT DISTINCT k.robot, g.dst_id FROM graph_edge g "
    "JOIN containers k ON k.container = g.src_id JOIN graph_entity d ON d.id = g.dst_id "
    "WHERE g.relation_type = 'contains' AND g.origin = 'manual' AND g.source_id IS NULL "
    "AND g.deleted_at IS NULL AND d.kind <> 'robot_category') pairs"
).bindparams(sa.bindparam("keys", expanding=True))
_LIVE_CATEGORIES = sa.text(
    "SELECT count(*) FROM graph_entity WHERE kind = 'robot_category' AND deleted_at IS NULL"
)
_LIVE_CATEGORY_EDGES = sa.text(
    "SELECT count(*) FROM graph_edge g JOIN graph_entity c ON c.id IN (g.src_id, g.dst_id) "
    "WHERE c.kind = 'robot_category' AND g.relation_type = 'contains' AND g.deleted_at IS NULL"
)


def _owned_pairs(connection: Any) -> int:
    return int(connection.execute(_OWNED_PAIRS, {"keys": list(KEYS)}).scalar() or 0)


def _check(connection: Any, owned_before: int) -> None:
    categories = int(connection.execute(_LIVE_CATEGORIES).scalar() or 0)
    edges = int(connection.execute(_LIVE_CATEGORY_EDGES).scalar() or 0)
    owned = _owned_pairs(connection)
    if categories or edges or owned != owned_before:
        raise RuntimeError(
            f"robot_category retirement incomplete: {categories} live robot_category nodes, "
            f"{edges} live contains edges touching one, owned pairs {owned_before} -> {owned}"
        )


def _moves(connection: Any) -> list[dict[str, Any]]:
    """The edges to re-point, oldest first; one live edge per (robot, part) survives."""
    owners = {
        row[0]: (row[1], row[2], bool(row[3]))
        for row in connection.execute(_OWNERS, {"keys": list(KEYS)}).all()
    }
    held = {(row[0], row[1]) for row in connection.execute(_HELD).all()}
    moves = []
    for edge_id, category_id, part_id, live in connection.execute(
        _CATEGORY_EDGES, {"rev": REVISION}
    ).all():
        if category_id not in owners:
            continue  # an impostor's edge: retired below when live
        robot_id, key, owned_live = owners[category_id]
        if live and (not owned_live or (robot_id, part_id) in held):
            continue  # owned nothing live, or a duplicate: retired below
        if live:
            held.add((robot_id, part_id))
        moves.append({"id": edge_id, "robot": robot_id, "category": str(category_id), "key": key})
    return moves


def retire_categories(connection: Any) -> dict[str, int]:
    owned_before = _owned_pairs(connection)
    moves = _moves(connection)
    if moves:
        connection.execute(_MOVE, [{**move, "rev": REVISION} for move in moves])
    edges = connection.execute(_RETIRE_EDGES, {"rev": REVISION}).rowcount
    categories = connection.execute(_RETIRE_CATEGORIES, {"rev": REVISION}).rowcount
    backfilled = connection.execute(_BACKFILL).rowcount
    _check(connection, owned_before)
    counts = {
        "owned_pairs": owned_before,
        "edges_moved": len(moves),
        "edges_retired": int(edges or 0),
        "categories_retired": int(categories or 0),
        "parts_backfilled": int(backfilled or 0),
    }
    logger.info("robot categories retired %s", counts)
    return counts
