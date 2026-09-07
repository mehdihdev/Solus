"""The six tools the `code` server registers — the single Python-side
statement of what `allowlist.yaml` exposes (tests pin allowlist == roster ==
registered)."""

READ_TOOLS: frozenset[str] = frozenset({"probe_environment", "plan"})
GATED_TOOLS: frozenset[str] = frozenset({"create_environment", "install", "run", "test"})
TOOL_ROSTER: frozenset[str] = READ_TOOLS | GATED_TOOLS
