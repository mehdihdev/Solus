"""Solus overlay for the vendored salitronic/eda-agent fork (SOLUSDEV-102).

Everything Solus-authored for this fork lives here: the env-allowlist
declaration the launchers pin (`env_allowlist.py`), the fail-closed workspace
guard (`workspace.py`), the confined file-drop IPC pointer computation
(`pointer.py`), the universal path-argument confinement (`confinement.py`),
and — ALT-5's deliverable — the trimmed-roster entry point `server.py` that
`bin/launch` / `bin/launch.cmd` exec instead of upstream's `eda_agent`
server module. This package runs STANDALONE on customer machines: stdlib +
the vendored `eda_agent` + the MCP SDKs from the fork lockfile only — never
anything from the Solus cloud codebase.

Modules in this package import each other RELATIVELY so the package works
both as `solus` (the launchers' standalone runtime) and under the
test-unique alias `altium_solus` (both forks' overlays share one pytest
session, and one sys.modules slot cannot hold two `solus` packages).
"""
