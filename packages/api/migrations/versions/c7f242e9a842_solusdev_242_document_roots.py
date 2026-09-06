"""solusdev-242 wrap existing Onshape graphs in stable document roots.

Revision ID: c7f242e9a842
Revises: b6f242d8e731

Local data only: no provider reads, resync, part mutation, or identity replacement.
Empty selected documents receive roots too. Additive and idempotent so migration
retries preserve every existing entity and edge ID.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7f242e9a842"
down_revision: str | None = "b6f242d8e731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SELECT id FROM sources WHERE type = 'onshape' ORDER BY id FOR UPDATE")
    op.execute("""
        WITH documents AS (
            SELECT s.id AS source_id, s.project_id, d.id AS document_id
            FROM sources s JOIN projects p ON p.id = s.project_id
            CROSS JOIN LATERAL jsonb_array_elements_text(
                CASE WHEN jsonb_typeof(s.config::jsonb->'documents') = 'array'
                     THEN s.config::jsonb->'documents' ELSE '[]'::jsonb END
            ) d(id)
            WHERE s.type = 'onshape' AND p.deleted_at IS NULL
              AND s.status <> 'disconnected'
            UNION
            SELECT s.id, s.project_id, s.config::jsonb->>'document_id'
            FROM sources s JOIN projects p ON p.id = s.project_id
            WHERE s.type = 'onshape' AND p.deleted_at IS NULL
              AND s.status <> 'disconnected' AND s.config::jsonb ? 'document_id'
            UNION
            SELECT s.id, s.project_id, n.attrs->>'document_id'
            FROM sources s JOIN projects p ON p.id = s.project_id
            JOIN graph_entity n ON n.source_id = s.id AND n.project_id = s.project_id
            WHERE s.type = 'onshape' AND p.deleted_at IS NULL
              AND s.status <> 'disconnected' AND n.deleted_at IS NULL
              AND n.origin = 'connector' AND n.attrs ? 'document_id'
        )
        INSERT INTO graph_entity
            (id, project_id, source_id, source_connector, external_ref,
             kind, domain, name, origin, version, attrs, modality_hints,
             created_at, updated_at)
        SELECT gen_random_uuid(), d.project_id, d.source_id, 'onshape',
               d.document_id || ':' || 'document', 'cad_document', 'mechanical',
               d.document_id, 'connector', 1,
               jsonb_build_object('document_id', d.document_id), '{}'::jsonb, now(), now()
        FROM documents d
        WHERE d.document_id ~ '^[A-Za-z0-9]{1,40}$'
          AND NOT EXISTS (
            SELECT 1 FROM graph_entity n WHERE n.source_id = d.source_id
              AND n.external_ref = d.document_id || ':' || 'document' AND n.deleted_at IS NULL
          )
    """)
    op.execute("""
        INSERT INTO graph_edge
            (id, project_id, source_id, src_id, dst_id, relation_type,
             domain_pair, confidence, origin, attrs, created_at, updated_at)
        SELECT gen_random_uuid(), root.project_id, root.source_id, root.id, child.id,
               'contains', 'mechanical<->mechanical', 1, 'connector', '{}'::jsonb, now(), now()
        FROM graph_entity root
        JOIN graph_entity child ON child.project_id = root.project_id
          AND child.source_id = root.source_id
          AND child.attrs->>'document_id' = root.attrs->>'document_id'
        WHERE root.kind = 'cad_document' AND root.source_connector = 'onshape'
          AND root.origin = 'connector' AND root.deleted_at IS NULL
          AND child.kind <> 'cad_document' AND child.origin = 'connector'
          AND child.domain = 'mechanical' AND child.deleted_at IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM graph_edge e JOIN graph_entity parent ON (
                (e.relation_type = 'part_of' AND e.src_id = child.id AND parent.id = e.dst_id)
                OR (e.relation_type = 'contains' AND e.dst_id = child.id AND parent.id = e.src_id)
            )
            WHERE e.source_id = root.source_id AND e.project_id = root.project_id
              AND e.deleted_at IS NULL AND parent.deleted_at IS NULL
              AND parent.source_id = root.source_id AND parent.project_id = root.project_id
              AND parent.attrs->>'document_id' = root.attrs->>'document_id'
          )
    """)


def downgrade() -> None:
    """Retain additive wrappers so application rollback never discards identities."""
