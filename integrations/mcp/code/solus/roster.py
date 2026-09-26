"""The tools the `code` server registers — the single Python-side
statement of what `allowlist.yaml` exposes (tests pin allowlist == roster ==
registered)."""

READ_TOOLS: frozenset[str] = frozenset(
    {"probe_environment", "plan", "git_status", "git_log", "git_diff", "arduino_probe"}
)
GATED_TOOLS: frozenset[str] = frozenset(
    {
        "create_environment",
        "install",
        "run",
        "test",
        "git_commit",
        "git_push",
        "arduino_prepare",
        "arduino_compile",
        "arduino_upload",
    }
)
TOOL_ROSTER: frozenset[str] = READ_TOOLS | GATED_TOOLS
