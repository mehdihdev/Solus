"""The Solus-authored launcher, env passthrough list and allowlist paper trail
of the gazebo fork (P3-T1). The launcher is never run past its exit-78 guards."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml
from solus_api.bridge.allowlist import load_allowlist
from solus_companion.config import _env_passthrough
from solus_companion.supervisor import child_env

REPO_ROOT = Path(__file__).resolve().parents[4]
MCP_ROOT = REPO_ROOT / "integrations" / "mcp"
FORK = MCP_ROOT / "gazebo"
LAUNCH = FORK / "bin" / "launch"
ENV_ALLOW = FORK / "solus" / "env.allow"

# The launcher's env -i list. SOLUS_MCP_WORKSPACE is companion-SET (config.discover_servers),
# so env.allow — the names the companion may copy from its AMBIENT environment — must NOT
# list it: with no folder linked an ambient value would otherwise reach bin/launch and
# become the confinement root.
PASSTHROUGH = (
    "SOLUS_MCP_WORKSPACE",
    "SOLUS_GAZEBO_PATH",
    "SOLUS_SIM_ROOTS",
    "GZ_CONFIG_PATH",
    "GZ_SIM_SYSTEM_PLUGIN_PATH",
    "GZ_SIM_RESOURCE_PATH",
    "GZ_PARTITION",
    "GZ_IP",
    "IGN_CONFIG_PATH",
    "IGN_GAZEBO_SYSTEM_PLUGIN_PATH",
    "IGN_GAZEBO_RESOURCE_PATH",
    "IGN_PARTITION",
    "IGN_IP",
    "GAZEBO_MODEL_PATH",
    "GAZEBO_PLUGIN_PATH",
    "GAZEBO_RESOURCE_PATH",
    "GAZEBO_MASTER_URI",
    "GAZEBO_IP",
    "LD_LIBRARY_PATH",
)
EXPECTED_TOOLS = {
    "probe": (False, 20, False),
    "list_worlds": (False, 20, False),
    "open_world": (False, 120, True),
    "attach": (False, 20, False),
    "list_models": (False, 20, False),
    "spawn": (False, 60, True),
    "joint_state": (False, 30, False),
    "set_joint_targets": (False, 20, True),
    "control": (False, 60, True),
    "run_routine": (False, 90, True),
    "stop": (False, 30, True),
    "save_world": (True, 30, True),
    "put_asset": (False, 30, True),
}


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(LAUNCH)], env=env, capture_output=True, text=True, timeout=20, check=False
    )


def test_launch_exits_78_without_interpreter_or_workspace(tmp_path: Path) -> None:
    assert os.access(LAUNCH, os.X_OK)
    base = {"PATH": "/usr/bin:/bin"}
    assert _run(base).returncode == 78
    assert _run({**base, "SOLUS_MCP_PYTHON": str(tmp_path / "missing")}).returncode == 78
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o755)
    assert _run({**base, "SOLUS_MCP_PYTHON": str(python)}).returncode == 78
    with_empty = {**base, "SOLUS_MCP_PYTHON": str(python), "SOLUS_MCP_WORKSPACE": ""}
    assert _run(with_empty).returncode == 78


def test_launch_is_env_i_with_exactly_the_declared_passthrough() -> None:
    text = LAUNCH.read_text()
    assert text.startswith("#!/bin/sh\n")
    assert "PATH=/usr/bin:/bin" in text
    assert "exec /usr/bin/env -i " in text
    assert '"$FORK_DIR/solus/gazebo_server.py"' in text
    for token in ("npx", "uvx", "pip ", "curl", "wget"):
        assert token not in text
    exec_line = next(line for line in text.splitlines() if line.startswith("exec "))
    exported = set(re.findall(r" ([A-Z_][A-Z0-9_]*)=", exec_line)) - {"PATH", "LANG"}
    declared = {
        line.strip()
        for line in ENV_ALLOW.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert exported == set(PASSTHROUGH)
    assert declared == set(PASSTHROUGH) - {"SOLUS_MCP_WORKSPACE"}
    for name in PASSTHROUGH:
        if name != "SOLUS_MCP_WORKSPACE":
            assert f'{name}="${{{name}:-}}"' in exec_line


def test_ambient_workspace_never_reaches_the_fork_when_no_folder_is_linked() -> None:
    """child_env copies env.allow names from the companion's ambient environment BEFORE the
    declared values; an ambient SOLUS_MCP_WORKSPACE must therefore be refused by name so the
    launcher's exit-78 guard fires instead of confining to an arbitrary directory."""
    passthrough = _env_passthrough(FORK, "gazebo")
    assert "SOLUS_MCP_WORKSPACE" not in passthrough
    env = child_env(declared={}, passthrough=passthrough, source={"SOLUS_MCP_WORKSPACE": "/tmp/x"})
    assert "SOLUS_MCP_WORKSPACE" not in env


def test_launch_keeps_only_absolute_entries_in_library_and_plugin_paths(tmp_path: Path) -> None:
    """An empty or relative element in LD_LIBRARY_PATH means the cwd (ld.so(8)), and the
    launcher cds into the cloned workspace — so repo-supplied .so files could load."""
    dump = tmp_path / "env.txt"
    python = tmp_path / "python"
    python.write_text(f"#!/bin/sh\n/usr/bin/env > {dump}\n")
    python.chmod(0o755)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    env = {
        "PATH": "/usr/bin:/bin",
        "SOLUS_MCP_PYTHON": str(python),
        "SOLUS_MCP_WORKSPACE": str(workspace),
        "LD_LIBRARY_PATH": ":/opt/x:.:rel",
        "GZ_SIM_SYSTEM_PLUGIN_PATH": "rel::/opt/plugins/",
        "GZ_SIM_RESOURCE_PATH": "./models:/usr/share/gz",
        "GAZEBO_MODEL_PATH": ":",
        "GZ_PARTITION": "bench",
    }
    assert _run(env).returncode == 0
    child = dict(line.split("=", 1) for line in dump.read_text().splitlines() if "=" in line)
    assert child["LD_LIBRARY_PATH"] == "/opt/x"
    assert child["GZ_SIM_SYSTEM_PLUGIN_PATH"] == "/opt/plugins/"
    assert child["GZ_SIM_RESOURCE_PATH"] == "/usr/share/gz"
    assert child["GAZEBO_MODEL_PATH"] == ""
    assert child["GZ_PARTITION"] == "bench"  # non-path values cross untouched
    assert child["SOLUS_MCP_WORKSPACE"] == str(workspace)


def test_allowlist_parses_with_the_api_loader() -> None:
    loaded = load_allowlist(MCP_ROOT)
    tools = loaded.servers["gazebo"]
    assert {
        name: (t.requires_confirmation, t.timeout_seconds, t.files_errors)
        for name, t in tools.items()
    } == EXPECTED_TOOLS
    assert all(t.reason for t in tools.values()), "every entry carries a Solus-written reason"
    assert [n for n, t in tools.items() if t.requires_confirmation] == ["save_world"]
    raw = yaml.safe_load((FORK / "allowlist.yaml").read_text())
    assert raw["server"] == "gazebo"
    assert [t["name"] for t in raw["tools"]] == list(EXPECTED_TOOLS)
    assert not any(t.returns_image for t in tools.values())
    # SOLUSDEV-322 P10: the whole server is `exposure: internal` (bridge-protocol.md);
    # only the owned `gazebo.*` wrappers in the API are model-facing.
    assert "gazebo" in loaded.internal
    assert raw["exposure"] == "internal"


def test_paper_trail_files_exist_with_blank_sign_offs() -> None:
    provenance = (FORK / "PROVENANCE.md").read_text()
    assert "Solus-authored" in provenance
    assert "Sign-off" in provenance or "sign-off" in provenance
    assert not re.search(r"Signed[- ]off by: *\S", provenance)
    review = (FORK / "SECURITY_REVIEW.md").read_text()
    assert "LD_LIBRARY_PATH" in review  # the recorded passthrough residual (Q4)
    assert (FORK / "requirements.lock.txt").read_bytes() == (
        MCP_ROOT / "isaac" / "requirements.lock.txt"
    ).read_bytes()
