"""End-to-end gate suites (SOLUS-FND-09 / SOLUSDEV-89).

This marker exists for MODULE NAMING, not for importable code. Without it,
`tests/e2e/conftest.py` and `packages/api/tests/conftest.py` both resolve to the
bare top-level module `conftest`: analysed together, mypy binds every
`from conftest import ...` in the API suite to THIS file (`Module "conftest" has
no attribute "TEST_JWT_SECRET"; maybe "_TEST_AUDIENCE"?`), and one pytest session
spanning both roots would clash the same way. With it, this tree's conftest is
`e2e.conftest` and the API suite keeps the bare name it relies on.

The marker is deliberately HERE and not at `tests/` — the vendored fork ships
`integrations/mcp/kicad/upstream/tests/__init__.py`, so a root-level `tests`
package makes the module name `tests` itself ambiguous (mypy: "Duplicate module
named tests"). `e2e` is unique repo-wide.

Not in pytest's `testpaths`: these gates run explicitly
(`uv run pytest tests/e2e/foundation_path.py`) against either an in-process app
or deployed staging, and own their throwaway database.
"""
