"""The declared child-environment allowlist for the `local` server.

`bin/launch` scrubs the environment with `env -i` and passes exactly these
variables through (pinned by `tests/test_launch_entrypoint.py`). Smaller than
the kicad fork's set: the POSIX basics, a PATH that is a launcher CONSTANT
(`/usr/bin:/bin`, never inherited), and the one workspace knob the companion
passes. No tool-specific knobs, and no credential-shaped variable may ever
appear here (integrations/mcp/CLAUDE.md rule 7). Changing this set is a
PROVENANCE re-review trigger.
"""

CHILD_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {"HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "PATH", "SOLUS_MCP_WORKSPACE"}
)
