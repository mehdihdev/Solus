"""Solus-authored `code` MCP server (SOLUSDEV-250 / ADR-031 Pattern 1, as
amended 2026-09-07).

The companion launches this server on the user's machine via `bin/launch`
with `SOLUS_MCP_WORKSPACE` = the linked folder. It exposes exactly six
workspace-confined tools per `docs/api/code-environment.md` §4: the reads
`probe_environment` and `plan`, and the confirmation-gated
`create_environment`, `install`, `run`, `test`. Every gated tool first calls
`plan` and executes EXACTLY that argv — one source of truth for what the
approval card shows and what runs. There is NO upstream: every byte here is
Solus code. Internal imports are relative so the package works under any name
(`solus` at runtime, `code_solus` in the repo test session).
"""
