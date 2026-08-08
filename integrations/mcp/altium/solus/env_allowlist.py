"""The declared child-environment allowlist for the altium fork (SOLUSDEV-102
ALT-3 — mirrors the kicad fork's declaration; `bin/launch`, `bin/launch.cmd`,
and their tests are pinned to it). Changing either set below is a PROVENANCE
re-review trigger.

`bin/launch` scrubs the environment with `env -i` and assigns exactly the
`CHILD_ENV_ALLOWLIST` names. PATH is a fixed constant in the launcher
(`/usr/bin:/bin`), never inherited. The three `EDA_AGENT_*` names are
launcher-SET pins — assigned values DERIVED from `SOLUS_MCP_WORKSPACE`, never
inherited from the parent environment — because upstream's file-drop IPC
honours them (`upstream/src/eda_agent/config.py`) and an inherited value
could point the DelphiScript bridge at a machine-global drop box. On Windows
(`bin/launch.cmd`, no `env -i`), the launcher sets only the pins.

M3 CORRECTION — the Windows child-env floor is NOT empty, so `_child_env` is
NOT a from-scratch scrub there. The companion launches every vendored server
through the MCP SDK's `stdio_client`, which merges the launch spec's env ON
TOP OF `get_default_environment()`; on Windows that inherited floor is the
SDK's `DEFAULT_INHERITED_ENV_VARS` — APPDATA, HOMEDRIVE, HOMEPATH,
LOCALAPPDATA, PATH, PATHEXT, PROCESSOR_ARCHITECTURE, SYSTEMDRIVE, SYSTEMROOT,
TEMP, USERNAME, USERPROFILE. So `USERPROFILE` and `LOCALAPPDATA` (both listed
in `UPSTREAM_ENV_NEVER_FORWARDED` below) DO reach the child on Windows. The
pins still hold: the launcher/`_child_env` SET `EDA_AGENT_WORKSPACE` /
`EDA_AGENT_POINTER_FILE` to confined paths, and those explicit pins WIN over
upstream's `USERPROFILE`-based machine-global pointer fallback
(`upstream/src/eda_agent/config.py`) — the file-drop IPC stays confined
regardless of the inherited profile roots. POSIX (`bin/launch`) is unaffected:
`env -i` clears the environment before the allowlist, so its child floor
really is empty (verified end-to-end by `test_launch_entrypoint.py`).

No credential-shaped name may ever appear in the child allowlist —
SecretStore values reach servers only through the sanctioned delivery seam
(integrations/mcp/CLAUDE.md rule 7).
"""

CHILD_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "PATH",
        "SOLUS_MCP_WORKSPACE",
        # Launcher-SET pins (never inherited): backend selection plus the
        # confined file-drop IPC workspace and pointer file, both derived
        # from SOLUS_MCP_WORKSPACE by bin/launch / bin/launch.cmd
        # (solus/pointer.py is the Python-side computation ALT-5's server
        # bootstrap validates against).
        "EDA_AGENT_BACKEND",
        "EDA_AGENT_WORKSPACE",
        "EDA_AGENT_POINTER_FILE",
    }
)

#: Upstream's remaining environment surface — every env-shaped name
#: `upstream/src` reads that the launcher must NOT forward (enumerated by
#: grep over upstream/src; tests/test_overlay_env_allowlist.py re-runs that
#: grep so a re-vendor cannot silently widen the surface). `env -i` drops
#: these mechanically; the written declaration exists so drift is caught in
#: review. Credential names appear here as NAMES ONLY (rule 7) — they are
#: listed precisely so nobody ever allowlists them.
UPSTREAM_ENV_NEVER_FORWARDED: frozenset[str] = frozenset(
    {
        # server/CLI behaviour knobs
        "EDA_AGENT_TOOLSET",
        "EDA_AGENT_CACHE_DIR",
        "EDA_AGENT_ALTIUM_PROCESS",
        "EDA_AGENT_ALTIUM_LIBRARIES",
        "EDA_AGENT_ASSUME_YES",
        "EDA_AGENT_PRIORS",
        "EDA_AGENT_QUALITY_MODEL",
        "EDA_AGENT_PREFERENCES_LOG",
        "EDA_AGENT_PLACEMENT_LOG",
        "EDA_AGENT_NO_DASHBOARD",
        "EDA_AGENT_DISABLE_DASHBOARD",
        "EDA_AGENT_HEADLESS",
        "EDA_AGENT_HEADLESS_REVIEW",
        "EDA_AGENT_PART_PROVIDERS",
        "EDA_AGENT_KICAD_SYMBOL_DIR",
        "EDA_AGENT_KICAD_FOOTPRINT_DIR",
        "EDA_AGENT_KICAD_3DMODEL_DIR",
        "_EDA_AGENT_BACKEND_REEXEC",
        # part-sourcing network endpoints and tunables
        "PARTS_REGISTRY_URL",
        "PARTS_REGISTRY_ASSET_HOSTS",
        "EASYEDA_API_BASE",
        "EASYEDA_MODEL_BASE",
        "EASYEDA_EXTRA_HOSTS",
        "ELEMENT14_STORE",
        "TME_COUNTRY",
        # distributor credentials — NAMES only (rule 7); never allowlisted
        "DIGIKEY_CLIENT_ID",
        "DIGIKEY_CLIENT_SECRET",
        "MOUSER_API_KEY",
        "NEXAR_CLIENT_ID",
        "NEXAR_CLIENT_SECRET",
        "ELEMENT14_API_KEY",
        "TME_TOKEN",
        "TME_SECRET",
        # Windows profile roots upstream falls back to for its drop box/cache
        "USERPROFILE",
        "LOCALAPPDATA",
        # KiCad library discovery (upstream's kicad backend reads these)
        "KICAD_SYMBOL_DIR",
        "KICAD8_SYMBOL_DIR",
        "KICAD9_SYMBOL_DIR",
        "KICAD10_SYMBOL_DIR",
        "KICAD_FOOTPRINT_DIR",
        "KICAD8_FOOTPRINT_DIR",
        "KICAD9_FOOTPRINT_DIR",
        "KICAD10_FOOTPRINT_DIR",
        "KICAD_3DMODEL_DIR",
        "KICAD10_3DMODEL_DIR",
    }
)
