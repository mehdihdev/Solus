"""The tools the `code` server registers — the single Python-side
statement of what `allowlist.yaml` exposes (tests pin allowlist == roster ==
registered)."""

READ_TOOLS: frozenset[str] = frozenset(
    {
        "probe_environment",
        "plan",
        "git_status",
        "git_log",
        "git_diff",
        "arduino_probe",
        "process_status",
        "profile_list",
        # SOLUSDEV-321 P6: ungated only under a SYSTEM profile, judged by the fork itself.
        "ros2_nodes",
        "ros2_topics",
    }
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
        "exec",
        "process_start",
        "process_stop",
        "process_input",
        "profile_capture",
        "profile_delete",
    }
)
TOOL_ROSTER: frozenset[str] = READ_TOOLS | GATED_TOOLS
