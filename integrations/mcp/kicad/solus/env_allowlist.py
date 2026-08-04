"""The declared child-environment allowlist for the kicad fork (T1a follow-up:
the declaration lives in solus/, and `bin/launch` plus its tests are pinned to
it). Changing this set is a PROVENANCE re-review trigger.

`bin/launch` scrubs the environment with `env -i` and passes exactly these
variables through. PATH is a fixed constant in the launcher (`/usr/bin:/bin`),
never inherited; `KICAD_*` are upstream's documented configuration knobs;
`SOLUS_MCP_WORKSPACE` is the one workspace/cwd knob the companion passes.
No credential-shaped variable may ever appear here — SecretStore values reach
servers only through the sanctioned delivery seam (integrations/mcp/CLAUDE.md
rule 7).
"""

CHILD_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "PATH",
        "KICAD_SEARCH_PATHS",
        "KICAD_USER_DIR",
        "KICAD_APP_PATH",
        "KICAD_CLI_PATH",
        "SOLUS_MCP_WORKSPACE",
    }
)
