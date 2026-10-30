"""SOLUSDEV-320: frozen data step behind a32000000001 (loaded by path, never imported).

Every `graph_edge` row, tombstones included: `domain_pair` becomes the two endpoint domains
in alphabetical order joined by `<->`; `attrs.evidence` exists (legacy `{by, source}` items
become `{kind: config, ref: by, detail: source}`); origins `linking` → `fingerprint` and
`derived` → `system`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import sqlalchemy as sa

logger = logging.getLogger("solus.migrations.edge_normalize")

_PAIR_UPDATE = sa.text(
    "UPDATE graph_edge e SET domain_pair = p.pair FROM ("
    "SELECT e2.id, least(s.domain::text, d.domain::text) || '<->' || "
    "greatest(s.domain::text, d.domain::text) AS pair FROM graph_edge e2 "
    "JOIN graph_entity s ON s.id = e2.src_id JOIN graph_entity d ON d.id = e2.dst_id) p "
    "WHERE p.id = e.id AND e.domain_pair IS DISTINCT FROM p.pair"
)


def _legacy_item(item: Any) -> Any:
    if isinstance(item, dict) and "kind" not in item and "by" in item:
        return {"kind": "config", "ref": str(item["by"]), "detail": item.get("source")}
    return item


def _convert_legacy_evidence(connection: Any) -> int:
    rows = connection.execute(
        sa.text(
            "SELECT id, attrs FROM graph_edge WHERE jsonb_typeof(attrs->'evidence') = 'array' "
            "AND attrs->'evidence' @? '$[*] ? (!exists(@.kind))'"
        )
    ).all()
    for edge_id, attrs in rows:
        attrs = json.loads(attrs) if isinstance(attrs, str) else dict(attrs)
        attrs["evidence"] = [_legacy_item(item) for item in attrs["evidence"]]
        connection.execute(
            sa.text("UPDATE graph_edge SET attrs = CAST(:attrs AS jsonb) WHERE id = :id"),
            {"attrs": json.dumps(attrs), "id": edge_id},
        )
    return len(rows)


def normalize_edges(connection: Any) -> dict[str, int]:
    dangling = connection.execute(
        sa.text(
            "SELECT e.id FROM graph_edge e "
            "LEFT JOIN graph_entity s ON s.id = e.src_id "
            "LEFT JOIN graph_entity d ON d.id = e.dst_id "
            "WHERE s.id IS NULL OR d.id IS NULL LIMIT 1"
        )
    ).all()
    if dangling:
        raise RuntimeError(f"graph_edge {dangling[0][0]} has a missing endpoint entity")
    rows = connection.execute(sa.text("SELECT count(*) FROM graph_edge")).scalar()
    colon_before = connection.execute(
        sa.text("SELECT count(*) FROM graph_edge WHERE domain_pair LIKE '%:%'")
    ).scalar()
    pairs = connection.execute(_PAIR_UPDATE).rowcount
    converted = _convert_legacy_evidence(connection)
    evidence = connection.execute(
        sa.text(
            "UPDATE graph_edge SET attrs = coalesce(attrs, '{}'::jsonb) || '{\"evidence\": []}' "
            "WHERE attrs->'evidence' IS NULL OR jsonb_typeof(attrs->'evidence') = 'null'"
        )
    ).rowcount
    origins = connection.execute(
        sa.text(
            "UPDATE graph_edge SET origin = CASE origin WHEN 'linking' THEN 'fingerprint' "
            "WHEN 'derived' THEN 'system' END WHERE origin IN ('linking', 'derived')"
        )
    ).rowcount
    counts = {
        "rows": int(rows or 0),
        "pairs_rewritten": int(pairs),
        "colon_before": int(colon_before or 0),
        "evidence_added": int(evidence),
        "evidence_converted": converted,
        "origins_rewritten": int(origins),
    }
    logger.info("graph_edge normalized %s", counts)
    return counts
