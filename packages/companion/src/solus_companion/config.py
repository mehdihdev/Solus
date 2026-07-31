"""Companion configuration and vendored-server discovery (ADR-031).

An integrations root holds one directory per vendored MCP server:
`<root>/<name>/allowlist.yaml` + `<root>/<name>/bin/launch`. Discovery is
deliberately paranoid — the launch command must resolve INSIDE the root
(no `..`/symlink escapes), exist, and be executable, or the server is
skipped with a hard log line. The companion never trusts the tree.
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

logger = logging.getLogger("solus.companion.config")

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
    updates the box, `{"type":"signout"}` clears it, garbage is logged and
    ignored. Never raises; never logs token material (§7)."""
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


def _launch_command(root_resolved: Path, server_dir: Path, name: str) -> Path | None:
    """The ADR-031 launch guard: `bin/launch` must RESOLVE inside the root,
    exist, and be executable — anything else is refused with a hard log."""
    command = server_dir / "bin" / "launch"
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
    if not os.access(resolved, os.X_OK):
        logger.error("REFUSED server %r: launch command %s is not executable", name, command)
        return None
    # SEC-L2: return the RESOLVED path so the validated target is what gets
    # executed — no symlink-swap window between check and launch.
    return resolved


def discover_servers(root: Path) -> tuple[ServerLaunch, ...]:
    """Scan `<root>/*/allowlist.yaml` for vendored servers (ADR-031)."""
    root_resolved = root.resolve()
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
        servers.append(ServerLaunch(name=name, command=command))
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
    return CompanionConfig(
        url=url,
        # The env token pre-seeds the box; stdin token lines refresh it later.
        token_source=TokenBox(token) if token is not None else TokenBox(),
        integrations_root=integrations_root,
        instance_id=load_instance_id(instance_file),
    )
