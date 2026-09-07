"""The declared child-environment allowlist for the `code` server.

`bin/launch` scrubs the environment with `env -i` and passes exactly these
variables through (pinned by `tests/test_code_launch_entrypoint.py`): the
`local` fork's set plus `VIRTUAL_ENV`, which the server never TRUSTS — it
overrides it with the workspace venv for every child it spawns
(`execute.py::scrubbed_env`). PATH is a launcher CONSTANT (`/usr/bin:/bin`,
never inherited); binaries are resolved against the pinned roots in
`probe.py`. No credential-shaped variable may ever appear here
(integrations/mcp/CLAUDE.md rule 7). Changing this set is a PROVENANCE
re-review trigger.
"""

CHILD_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {"HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV", "PATH", "SOLUS_MCP_WORKSPACE"}
)
