# Personal source revisions — SOLUSDEV-260

`source_revisions`: UUID primary key, project FK, base_source FK, immutable
commit_id, materialized_source FK, branch provenance, creation timestamp; unique
(base_source_id, commit_id). Materialized source ID is unique and references an
internal source with real graph entities. No credentials or file bodies in this row.

`source_view_selections`: UUID primary key, project FK, user FK, base_source FK,
active_revision FK nullable, requested_branch nullable, request generation UUID,
status, sanitized error nullable, timestamps. Unique (user_id, base_source_id).
FK deletion and explicit cleanup prevent orphaned snapshot sources. Active revisions
must belong to the same project and base source; enforce in the selection service.

## Revision reference index

Migration `a26000000005` indexes `source_view_selections.active_revision_id` so
revision deletion and its SET NULL foreign-key action do not scan all selections.
The additive migration builds the index concurrently.
