"""Solus overlay for the vendored lamaalrajih/kicad-mcp fork (SOLUSDEV-100 T1b).

Everything Solus-authored for this fork lives here: the trimmed-roster entry
point (`server.py`, exec'd by `bin/launch` instead of `upstream/main.py`), the
env-allowlist declaration the launcher pins, headless kicad-cli detection, the
plan-locked `export_netlist` tool, and the registration shim that keeps every
non-allowlisted upstream tool dead in-process. This package runs STANDALONE on
customer machines: stdlib + the vendored `kicad_mcp` + the MCP SDKs from the
fork lockfile only — never anything from the Solus cloud codebase.
"""
