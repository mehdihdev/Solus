"""solusdev-242 backfill real .solus section and entry graph identities.

Revision ID: b6f242d8e731
Revises: a3f242b9c610

Data-only, idempotent, and independent of application models. Existing entry,
document, and artifact IDs and stored bytes are preserved. Project row locks
serialize the backfill with runtime hierarchy creation and entry mutations.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6f242d8e731"
down_revision: str | None = "a3f242b9c610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SELECT id FROM projects WHERE deleted_at IS NULL ORDER BY id FOR UPDATE")
    op.execute("""
        INSERT INTO graph_entity
            (id, project_id, kind, domain, name, origin, version, attrs,
             modality_hints, created_at, updated_at)
        SELECT gen_random_uuid(), p.id, 'solus_config', 'project', '.solus', 'manual',
               1, '{}'::jsonb, '{}'::jsonb, now(), now()
        FROM projects p
        WHERE p.deleted_at IS NULL AND NOT EXISTS (
            SELECT 1 FROM graph_entity n WHERE n.project_id = p.id
              AND n.kind = 'solus_config' AND n.domain = 'project'
              AND n.origin = 'manual' AND n.source_id IS NULL AND n.deleted_at IS NULL
        )
    """)
    op.execute("""
        INSERT INTO graph_entity
            (id, project_id, kind, domain, name, origin, version, attrs,
             modality_hints, created_at, updated_at)
        SELECT gen_random_uuid(), p.id, 'solus_section', 'project', s.label, 'manual',
               1, jsonb_build_object('section', s.key), '{}'::jsonb, now(), now()
        FROM projects p CROSS JOIN (VALUES
            ('hardware', 'Hardware configs'), ('details', 'Project details'),
            ('errors', 'Error logging'), ('docs', 'Documentation'),
            ('code', 'Code environment')
        ) AS s(key, label)
        WHERE p.deleted_at IS NULL AND NOT EXISTS (
            SELECT 1 FROM graph_entity n WHERE n.project_id = p.id
              AND n.kind = 'solus_section' AND n.attrs->>'section' = s.key
              AND n.domain = 'project' AND n.origin = 'manual'
              AND n.source_id IS NULL AND n.deleted_at IS NULL
        )
    """)
    op.execute("""
        WITH inserted AS (
            INSERT INTO graph_entity
                (id, project_id, kind, domain, name, origin, version, attrs,
                 modality_hints, created_at, updated_at)
            SELECT gen_random_uuid(), e.project_id,
                   CASE WHEN e.section = 'errors' THEN 'solus_error' ELSE 'solus_note' END,
                   'project', coalesce(nullif(left(trim(regexp_replace(
                       coalesce(e.text, ''), '\\s+', ' ', 'g')), 120), ''), 'Untitled note'),
                   'manual', 1, jsonb_build_object('solus_entry_id', e.id::text,
                       'section', e.section), '{}'::jsonb, now(), now()
            FROM solus_entries e JOIN projects p ON p.id = e.project_id
            WHERE p.deleted_at IS NULL AND e.deleted_at IS NULL
              AND e.kind IN ('text', 'sol') AND e.entity_id IS NULL
            RETURNING id, attrs
        )
        UPDATE solus_entries e SET entity_id = n.id
        FROM inserted n WHERE e.id = (n.attrs->>'solus_entry_id')::uuid
    """)
    # A foreign/malformed FK must never be reinterpreted as ownership by this entry.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM solus_entries e JOIN projects p ON p.id = e.project_id
                LEFT JOIN graph_entity n ON n.id = e.entity_id
                WHERE p.deleted_at IS NULL AND e.deleted_at IS NULL AND (
                    n.id IS NULL OR n.project_id <> e.project_id OR n.deleted_at IS NOT NULL
                    OR n.domain <> 'project' OR n.origin <> 'manual' OR n.source_id IS NOT NULL
                    OR n.kind <> CASE WHEN e.kind = 'artifact' THEN 'document'
                        WHEN e.section = 'errors' THEN 'solus_error' ELSE 'solus_note' END
                    OR (n.attrs ? 'solus_entry_id' AND n.attrs->>'solus_entry_id' <> e.id::text)
                    OR (e.kind = 'artifact' AND
                        n.attrs->>'artifact_id' IS DISTINCT FROM e.artifact_id::text)
                )
            ) THEN
                RAISE EXCEPTION 'Invalid .solus entry graph identity; repair before migrating';
            END IF;
        END $$
    """)
    op.execute("""
        UPDATE graph_entity n
        SET attrs = n.attrs || jsonb_build_object('solus_entry_id', e.id::text,
                                                 'section', e.section)
        FROM solus_entries e JOIN projects p ON p.id = e.project_id
        WHERE n.id = e.entity_id AND n.project_id = e.project_id
          AND p.deleted_at IS NULL AND e.deleted_at IS NULL
          AND n.attrs IS DISTINCT FROM n.attrs || jsonb_build_object(
              'solus_entry_id', e.id::text, 'section', e.section)
    """)
    op.execute("""
        WITH roots AS (
            SELECT DISTINCT ON (n.project_id) n.project_id, n.id
            FROM graph_entity n JOIN projects p ON p.id = n.project_id
            WHERE p.deleted_at IS NULL AND n.deleted_at IS NULL
              AND n.kind = 'solus_config' AND n.domain = 'project'
              AND n.origin = 'manual' AND n.source_id IS NULL
            ORDER BY n.project_id, n.created_at, n.id
        ), sections AS (
            SELECT DISTINCT ON (n.project_id, n.attrs->>'section')
                   n.project_id, n.id, n.attrs->>'section' AS section
            FROM graph_entity n JOIN projects p ON p.id = n.project_id
            WHERE p.deleted_at IS NULL AND n.deleted_at IS NULL
              AND n.kind = 'solus_section' AND n.domain = 'project'
              AND n.origin = 'manual' AND n.source_id IS NULL
              AND n.attrs->>'section' IN ('hardware', 'details', 'errors', 'docs', 'code')
            ORDER BY n.project_id, n.attrs->>'section', n.created_at, n.id
        ), desired AS (
            SELECT r.project_id, r.id AS src, s.id AS dst, 'contains' AS kind, s.section
            FROM roots r JOIN sections s ON s.project_id = r.project_id
            UNION ALL
            SELECT s.project_id, s.id, e.entity_id, 'contains', s.section
            FROM sections s JOIN solus_entries e
              ON e.project_id = s.project_id AND e.section = s.section
            WHERE e.deleted_at IS NULL
            UNION ALL
            SELECT r.project_id, r.id, e.entity_id, 'references', e.section
            FROM roots r JOIN solus_entries e ON e.project_id = r.project_id
            WHERE e.deleted_at IS NULL AND e.kind = 'artifact'
        )
        INSERT INTO graph_edge
            (id, project_id, src_id, dst_id, relation_type, domain_pair,
             confidence, origin, attrs, created_at, updated_at)
        SELECT gen_random_uuid(), d.project_id, d.src, d.dst, d.kind,
               'project<->project', 1, 'manual', jsonb_build_object('section', d.section),
               now(), now()
        FROM desired d WHERE NOT EXISTS (
            SELECT 1 FROM graph_edge e WHERE e.project_id = d.project_id
              AND e.src_id = d.src AND e.dst_id = d.dst AND e.relation_type = d.kind
              AND e.deleted_at IS NULL
        )
    """)


def downgrade() -> None:
    """Keep additive graph data: deleting it would discard stable user identities.

    W1 accepts these existing generic graph kinds and nullable entry references;
    its schema and artifact storage need no reversal for an application rollback.
    """
