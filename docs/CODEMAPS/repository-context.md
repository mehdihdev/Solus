# Repository context
<!-- Updated: 2026-09-11 | Scope: SOLUSDEV-260 repository follow-up -->

## Personal branch flow

`SourceRevisionPicker.tsx` → `lib/api/resources.revisions.ts` →
`routers/source_revisions.py` → `services/git_revisions.py` (provider discovery) /
`services/source_revisions.py` (selection + acquisition) → ARQ `source_revision`.
`scripts/dev-all.sh` owns the worker when Redis is configured.

`SourceViewSelection(project,user,base source)` → `SourceRevision(commit)` →
internal `Source` → real `GraphEntity` rows. Migration: `a26000000004`.

`deps.get_project_read_context` binds `graph/read_scope.py` per request.
`get_project_context` stays awaitable for direct WebSocket callers.
`GraphReadScope` substitutes selected snapshots, carries personal branch labels,
and projects root links. SOL freezes it for the whole turn. Shared writes explicitly
use base scope. Graph, search, neighborhood, impact, retrieval and tools use scope.

## Saved code flow

`agent/tools/read_code_file.py` resolves graph identity and live base credentials.
`connectors/code_content.py` fetches bounded immutable GitHub blobs or GitLab files.
Matching local checkout: `local.scan_folder` → fresh repo/branch proof → approved
`machine.read_code_file` → verify identity again → labeled, redacted source text.

Native reader: `packages/companion/src/solus_companion/machine/code_reader.py`.
Policy: `integrations/mcp/machine/allowlist.yaml`. Generic `read_file` remains gated.
Local Git metadata and root presentation are in companion LocalGit, API local-folder
connector/linking, and desktop `accountAnchors.ts` / `navigation/nodeTypes.ts`.

## Refresh

`sourceViewEvents.ts` carries project-only refresh signals across renderer windows.
`useWorkspaceGraph`, `useMentionSearch`, `useMentionPicker` invalidate stale state.
Completion publishes `graph.changed`; no branch choices are broadcast as selections.

## Verification

API: `test_source_revisions.py`, `test_graph_read_scope.py`, `test_git_revisions.py`,
`test_read_code_file.py`, `test_code_content.py`. Companion: native-reader/Git tests.
Desktop: picker race tests, transport envelope test, sidebar/root/mention tests.
Handoff: `docs/qa/COWORK_QA_repository-revisions.md`.

Authority: `docs/architecture/source-revisions.md`, `docs/api/source-revisions.md`.
