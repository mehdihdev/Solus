"""Where fork environments live — mcp-fork-runtime.md §2.

Environments are regenerable caches in the OS app-data folder, never in
`~/.solus`. `SOLUS_COMPANION_MCP_ENVS_ROOT` (absolute) replaces `<data>/mcp-envs`
for per-worktree dev isolation; the managed interpreter root is always the
envs root's sibling `mcp-python`."""

import re
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath

ENVS_ROOT_ENV = "SOLUS_COMPANION_MCP_ENVS_ROOT"
ENVS_DIRNAME = "mcp-envs"
PYTHON_DIRNAME = "mcp-python"
FORK_NAME_PATTERN = r"^[a-z][a-z0-9_-]{0,31}$"
_FORK_NAME_RE = re.compile(FORK_NAME_PATTERN)


def is_fork_name(name: str) -> bool:
    return _FORK_NAME_RE.fullmatch(name) is not None


def _absolute(value: str, platform: str) -> bool:
    if platform == "win32":
        return PureWindowsPath(value).is_absolute()
    return value.startswith("/")


def data_root(platform: str, env: Mapping[str, str], home: Path) -> Path:
    """`<data>` per OS: Application Support / %LOCALAPPDATA% / XDG data home."""
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Solus"
    if platform == "win32":
        local = env.get("LOCALAPPDATA", "")
        base = Path(local) if local and _absolute(local, platform) else home / "AppData" / "Local"
        return base / "Solus"
    xdg = env.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg and _absolute(xdg, platform) else home / ".local" / "share"
    return base / "solus"


def envs_root(platform: str, env: Mapping[str, str], home: Path) -> Path:
    """`<data>/mcp-envs`, or the dev override. A relative override is refused."""
    override = env.get(ENVS_ROOT_ENV, "")
    if override:
        if not _absolute(override, platform):
            raise ValueError(f"{ENVS_ROOT_ENV} must be an absolute path")
        return Path(override)
    return data_root(platform, env, home) / ENVS_DIRNAME


def python_root(envs: Path) -> Path:
    return envs.parent / PYTHON_DIRNAME


def env_interpreter(env_dir: Path, platform: str) -> Path:
    if platform == "win32":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"
