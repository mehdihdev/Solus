"""The three tools the `local` server registers — the single Python-side
statement of what `allowlist.yaml` exposes (tests pin allowlist == roster ==
registered)."""

TOOL_ROSTER: frozenset[str] = frozenset({"scan_folder", "folder_digest", "open_in_tool"})
