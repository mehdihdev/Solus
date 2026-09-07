"""Namespace anchor for the Solus-authored `local` MCP server (SOLUSDEV-249).

Exists so the Solus-authored `tests/` package resolves as `local.tests` (and
`solus/` as `local.solus`) instead of claiming the bare top-level names — the
same reason the altium fork carries one: bare `tests`/`solus` names would be
one sys.modules slot shared with every other fork's identically-named
packages in a single pytest/mypy run.

The launcher's runtime import of `solus` is unaffected: `bin/launch` execs
`solus/server.py`, which puts the fork directory on the child's import path,
where `solus/` remains a top-level package regardless of this file.
"""
