"""Solus-authored `local` MCP server (SOLUSDEV-249 / ADR-031 Pattern 1).

The companion launches this server on the user's machine via `bin/launch`
with `SOLUS_MCP_WORKSPACE` = the linked folder. It exposes exactly three
workspace-confined tools (`scan_folder`, `folder_digest`, `open_in_tool`) per
`docs/api/local-folder.md` §4. There is NO upstream: every byte here is Solus
code. Internal imports are relative so the package works under any name
(`solus` at runtime, `local_solus` in the repo test session).
"""
