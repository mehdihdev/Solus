"""Companion configuration and vendored-server discovery (ADR-031).

An integrations root holds one directory per vendored MCP server:
`<root>/<name>/allowlist.yaml` + `<root>/<name>/bin/launch`. Discovery is
deliberately paranoid — the launch command must resolve INSIDE the root
(no `..`/symlink escapes), exist, and be executable, or the server is
skipped with a hard log line. The companion never trusts the tree.

`SOLUS_COMPANION_WORKSPACE` (optional): the project working directory this
companion serves. When set, `CompanionConfig.workspace` carries it and
callers pass it to `discover_servers(root, workspace=config.workspace)` so
every vendored server's declared env carries `SOLUS_MCP_WORKSPACE` — the
knob a fork's own confinement trusts (e.g. the kicad fork's
`solus/workspace.py::workspace_root()`, H3). When unset, no server receives
that variable, and a fork built to fail closed on an absent workspace
refuses its confined operations rather than falling back to an arbitrary
cwd — this is deliberate, not a gap: a companion instance with no configured
workspace should not silently let a fork guess one.
"""

import asyncio
import json
import logging
import os
import re
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from solus_companion import __version__
from solus_companion.credentials import CredentialRelay

logger = logging.getLogger("solus.companion.config")

# MCP-05 pre-parse guard: no stdin control line is ever parsed past this bound
# (tokens and credential frames are all far smaller — Addendum C caps control
# frames at 16 KiB; the slack covers JSON envelope overhead).
_MAX_STDIN_LINE_BYTES = 32 * 1024

SERVER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
# ponytail: minimal `server:` field extraction — the only YAML field discovery
# needs. Swap for a real YAML parser if allowlists grow structure we consume.
_SERVER_LINE_RE = re.compile(r"^server:\s*[\"']?([A-Za-z0-9_-]+)[\"']?\s*$")

DEFAULT_INSTANCE_FILE = "~/.solus/companion_id"
# SEC-M2: the bearer token only ever rides to an allowlisted host. Packaged
# builds bake the real backend origin at build time (SOLUSDEV-148/149);
# setting SOLUS_COMPANION_ALLOWED_HOSTS is the explicit user/app consent.
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1")
_LOCAL_HOSTS = frozenset(DEFAULT_ALLOWED_HOSTS)

# The bridge WS path (bridge-protocol.md §8); the artifact upload origin and
# project id are derived from it so the HTTPS API host is always the SAME
# allowlisted host the socket dials (SEC-M2 — one consent covers both).
_BRIDGE_PATH_RE = re.compile(r"^/api/v1/projects/([^/]+)/bridge/?$")


@dataclass(frozen=True)
class ServerLaunch:
    """One vendored MCP server: how to launch it and its declared child env."""

    name: str
    command: Path
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)


class TokenBox:
    """Mutable access-token holder (BRG-04 stdin relay). Callable, so it slots
    straight into `CompanionConfig.token_source`; the channel awaits
    `available` instead of dialing while the box is empty."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token
        self.available = asyncio.Event()
        # MCP-05: the credential relay rides the same stdin control channel as
        # tokens. Attached by the channel once the discovered-server set is
        # known; None until then (credential lines are dropped with a log).
        self.credentials: CredentialRelay | None = None
        if token:
            self.available.set()

    def get(self) -> str:
        return self._token or ""

    def __call__(self) -> str:
        return self.get()

    def set(self, token: str) -> None:
        self._token = token
        self.available.set()

    def clear(self) -> None:
        self._token = None
        self.available.clear()


def apply_token_line(box: TokenBox, line: str | bytes) -> None:
    """One stdin line from the desktop app: `{"type":"token","access_token":..}`
    updates the box, `{"type":"signout"}` clears it, `{"type":"credential",..}`
    routes to the attached MCP-05 credential relay, garbage is logged and
    ignored. Never raises; never logs token or credential material (§7 —
    only key NAMES may appear in logs, never values)."""
    if len(line) > _MAX_STDIN_LINE_BYTES:
        # Oversize is refused BEFORE parsing: nothing this channel carries is
        # legitimately this large (Addendum C 16 KiB control cap).
        logger.warning("ignored oversize stdin line (%d bytes)", len(line))
        return
    try:
        message = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        logger.warning("ignored malformed stdin line (not JSON)")
        return
    if not isinstance(message, dict):
        logger.warning("ignored malformed stdin line (not an object)")
        return
    kind = message.get("type")
    if kind == "token":
        token = message.get("access_token")
        if isinstance(token, str) and token:
            box.set(token)
            logger.info("access token updated via stdin")
        else:
            logger.warning("ignored token line without a usable access_token")
    elif kind == "signout":
        box.clear()
        logger.info("signed out via stdin; channel idles until a new token arrives")
    elif kind == "credential":
        if box.credentials is None:
            logger.warning("ignored credential line: no relay attached yet")
        else:
            box.credentials.offer(message)  # validates, queues, never raises
    else:
        logger.warning("ignored unknown stdin line type %.32r", kind)


@dataclass(frozen=True)
class CompanionConfig:
    url: str
    token_source: Callable[[], str]
    integrations_root: Path
    instance_id: str
    servers: tuple[ServerLaunch, ...] = ()
    ping_interval: float = 20.0
    companion_version: str = __version__
    # SEC-M2: the one allowlist gating every host the bearer token rides to —
    # the WS dial (checked at config time) AND artifact uploads (artifacts.py).
    allowed_hosts: frozenset[str] = frozenset(DEFAULT_ALLOWED_HOSTS)
    # H3 (companion half): the project working directory this companion
    # serves, from `SOLUS_COMPANION_WORKSPACE` — optional. When set, callers
    # pass it to `discover_servers(..., workspace=config.workspace)` so every
    # vendored server's declared env carries `SOLUS_MCP_WORKSPACE`; when
    # unset, no server gets that variable and each fork's own
    # `workspace_root()` fails closed rather than confining to an arbitrary
    # cwd (docs/architecture — kicad fork `solus/workspace.py`).
    workspace: str | None = None


@dataclass(frozen=True)
class ApiEndpoint:
    """The HTTPS API origin + project id derived from the bridge WS URL."""

    origin: str
    project_id: str


def api_endpoint_from_ws_url(url: str) -> ApiEndpoint | None:
    """`wss://host/api/v1/projects/{id}/bridge` → (`https://host`, id).
    `ws://` maps to `http://` (localhost dev only, mirroring the URL guard).
    Any other shape → None: artifact uploads stay disabled."""
    parsed = urlparse(url)
    match = _BRIDGE_PATH_RE.match(parsed.path)
    if match is None or parsed.scheme not in ("ws", "wss"):
        return None
    scheme = "https" if parsed.scheme == "wss" else "http"
    return ApiEndpoint(origin=f"{scheme}://{parsed.netloc}", project_id=match.group(1))


def _read_server_name(allowlist: Path) -> str | None:
    try:
        text = allowlist.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        match = _SERVER_LINE_RE.match(line)
        if match is not None:
            return match.group(1)
    return None


_WINDOWS_LAUNCHER_NAME = "launch.cmd"
_WINDOWS_EXECUTABLE_SUFFIXES = frozenset({".bat", ".cmd", ".com", ".exe"})


def _is_windows() -> bool:
    """Read at call time so tests can monkeypatch `sys.platform`. Routed
    through a plain str so mypy (strict, warn_unreachable) does not mark the
    win32 branch unreachable on the checking platform."""
    platform: str = sys.platform
    return platform == "win32"


def _is_executable(path: Path) -> bool:
    """Per-platform executability guard: on Windows `os.access(..., X_OK)` is
    True for ANY existing file, so the meaningful check there is the resolved
    launcher's extension; on POSIX it is the execute bit."""
    if _is_windows():
        return path.suffix.lower() in _WINDOWS_EXECUTABLE_SUFFIXES
    return os.access(path, os.X_OK)


def _launch_command(root_resolved: Path, server_dir: Path, name: str) -> Path | None:
    """The ADR-031 launch guard: the launcher must RESOLVE inside the root,
    exist, and be executable — anything else is refused with a hard log.
    Specs keep pointing at `bin/launch`; on Windows the sibling
    `bin/launch.cmd` is the real launcher (the altium fork ships both), and
    its absence fails closed — a POSIX shell script is never spawned there."""
    command = server_dir / "bin" / "launch"
    if _is_windows():
        windows_command = command.with_name(_WINDOWS_LAUNCHER_NAME)
        if not windows_command.is_file():
            logger.error(
                "REFUSED server %r: no Windows launcher %s next to the POSIX launch script",
                name,
                windows_command,
            )
            return None
        command = windows_command
    resolved = command.resolve()
    if not resolved.is_relative_to(root_resolved):
        logger.error(
            "REFUSED server %r: launch command escapes the integrations root (resolved outside %s)",
            name,
            root_resolved,
        )
        return None
    if not resolved.is_file():
        logger.error("REFUSED server %r: launch command %s does not exist", name, command)
        return None
    if not _is_executable(resolved):
        logger.error("REFUSED server %r: launch command %s is not executable", name, command)
        return None
    # SEC-L2: return the RESOLVED path so the validated target is what gets
    # executed — no symlink-swap window between check and launch.
    return resolved


def discover_servers(root: Path, *, workspace: str | None = None) -> tuple[ServerLaunch, ...]:
    """Scan `<root>/*/allowlist.yaml` for vendored servers (ADR-031).

    H3 (companion half): when *workspace* is given (non-empty), every
    discovered server's declared env carries `SOLUS_MCP_WORKSPACE=workspace`
    — the one knob a fork's own confinement (e.g. the kicad fork's
    `solus/workspace.py::workspace_root()`) trusts. Omitted or empty means no
    server gets that variable, and each fork fails closed rather than
    confining to an arbitrary cwd."""
    root_resolved = root.resolve()
    declared_env = {"SOLUS_MCP_WORKSPACE": workspace} if workspace else {}
    servers: list[ServerLaunch] = []
    for allowlist in sorted(root.glob("*/allowlist.yaml")):
        server_dir = allowlist.parent
        name = _read_server_name(allowlist)
        if name is None or SERVER_NAME_RE.fullmatch(name) is None or name != server_dir.name:
            logger.warning(
                "skipping %s: server field %r missing, unsafe, or != directory name %r",
                allowlist,
                name,
                server_dir.name,
            )
            continue
        command = _launch_command(root_resolved, server_dir, name)
        if command is None:
            continue
        servers.append(ServerLaunch(name=name, command=command, env=declared_env))
    return tuple(servers)


def load_instance_id(path: Path) -> str:
    """Read the persisted companion instance id, or create one (0600)."""
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{32}", existing):
            return existing
    except OSError:
        pass
    instance_id = uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(instance_id)
    return instance_id


def _require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "")
    if not value:
        raise ValueError(f"{key} is required")
    return value


def config_from_env(env: Mapping[str, str] | None = None) -> CompanionConfig:
    """Build a config from the environment. Servers are discovered separately
    (`discover_servers`) so callers control when the tree is scanned."""
    source = os.environ if env is None else env
    url = _require(source, "SOLUS_COMPANION_URL")
    parsed = urlparse(url)
    if parsed.scheme != "wss" and not (parsed.scheme == "ws" and parsed.hostname in _LOCAL_HOSTS):
        raise ValueError("SOLUS_COMPANION_URL must be wss:// (ws:// allowed only for localhost)")
    allowed_env = source.get("SOLUS_COMPANION_ALLOWED_HOSTS", "")
    allowed = (
        frozenset(host.strip().lower() for host in allowed_env.split(",") if host.strip())
        if allowed_env.strip()
        else frozenset(DEFAULT_ALLOWED_HOSTS)
    )
    host = (parsed.hostname or "").lower()
    if host not in allowed:
        raise ValueError(
            f"SOLUS_COMPANION_URL host {host!r} is not allowlisted; the bearer token is only "
            "sent to allowlisted hosts. Set SOLUS_COMPANION_ALLOWED_HOSTS to permit it."
        )
    # The env token is OPTIONAL under the Electron launch flow (BRG-04): the
    # app relays tokens over stdin AFTER spawn, and an empty box makes the
    # channel idle (never dialing blank) until the first token line arrives.
    token = source.get("SOLUS_COMPANION_TOKEN")
    if token is None and sys.stdin.isatty():
        raise ValueError("SOLUS_COMPANION_TOKEN is required when no stdin token relay is attached")
    integrations_root = Path(_require(source, "SOLUS_COMPANION_INTEGRATIONS_ROOT"))
    instance_file = Path(
        source.get("SOLUS_COMPANION_INSTANCE_FILE", DEFAULT_INSTANCE_FILE)
    ).expanduser()
    # H3 (companion half): the project directory this companion serves —
    # optional. `None` (never an empty string) means "not configured", so
    # `discover_servers(..., workspace=config.workspace)` omits the env var
    # for every server rather than passing an empty one.
    workspace = source.get("SOLUS_COMPANION_WORKSPACE") or None
    return CompanionConfig(
        url=url,
        # The env token pre-seeds the box; stdin token lines refresh it later.
        token_source=TokenBox(token) if token is not None else TokenBox(),
        integrations_root=integrations_root,
        instance_id=load_instance_id(instance_file),
        allowed_hosts=allowed,
        workspace=workspace,
    )
