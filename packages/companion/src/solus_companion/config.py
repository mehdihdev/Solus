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
import ipaddress
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

from solus_contracts import SOLUS_HOME_DIRNAME

from solus_companion import __version__
from solus_companion.credentials import CredentialRelay
from solus_companion.kicad_discovery import KICAD_CLI_ENV, find_kicad_cli
from solus_companion.platforms import unavailable_reason

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

#: Where a vendored fork's private dependency environment lives, relative to the
#: server directory (CAD-00b). Materialized at install time from the fork's
#: committed lockfile — never at launch, and `bin/launch` does no network I/O.
PRIVATE_ENV_INTERPRETER = Path(".venv") / "bin" / "python"

#: The variable a fork's `bin/launch` reads to find that interpreter. It is an
#: ABSOLUTE path because the README forbids PATH resolution, and because a
#: PyInstaller-frozen companion's `sys.executable` is the companion itself — so
#: a launcher that re-execs `sys.executable` would re-exec the companion.
INTERPRETER_ENV = "SOLUS_MCP_PYTHON"

#: One variable NAME per line; `#` comments and blanks ignored. Solus-authored,
#: reviewed with the fork — this is the "env allowlist declared in solus/" the
#: MCP-03 launcher contract promises, made mechanical.
ENV_ALLOW_FILE = Path("solus") / "env.allow"

#: A POSIX environment variable name. Anything else in env.allow is a defect in
#: OUR file, so it is dropped loudly rather than passed through.
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Where a packaged build puts the vendored tree, relative to the binary.
_PACKAGED_TREE = "mcp"

#: `url: <...>` in an allowlist — a VENDOR-RUN server on this machine (CAD-02:
#: Autodesk's Fusion MCP at 127.0.0.1:27182). Read with the same line-regex as
#: `server:` so the companion keeps its no-YAML-dependency posture.
_URL_LINE_RE = re.compile(r"^url:\s*[\"\']?(\S+?)[\"\']?\s*$")

#: `launched_by:` in an allowlist — who starts the server. Anything other than
#: `companion` is not ours to launch: `cloud` is a fork the API spawns (the brave
#: fork needs Node, which we do not ship) and `builtin` is a server this process
#: implements natively, so neither has a `bin/launch` to find. Absent = companion.
_LAUNCHED_BY_RE = re.compile(r"^launched_by:\s*[\"\']?([a-z]+)[\"\']?\s*$")

#: Hostnames that mean "this machine". Compared exactly — a name that merely
#: STARTS with one (`127.0.0.1.evil.com`) is a different host.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
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
    #: stdio: the vendored fork's launcher. None for a vendor-run URL server.
    command: Path | None = None
    #: streamable-http: a VENDOR-RUN server on this machine (CAD-02). Mutually
    #: exclusive with `command`; always loopback.
    url: str | None = None
    args: tuple[str, ...] = ()
    #: Values Solus SETS for the child (the private interpreter, and — once the
    #: bridge carries them — delivered license credentials). These win over the
    #: ambient environment: a hostile value must not be able to redirect a fork.
    env: Mapping[str, str] = field(default_factory=dict)
    #: Variable NAMES the fork declared it may inherit from the host. Values are
    #: read at spawn time, so a license variable set after install still works.
    env_passthrough: tuple[str, ...] = ()
    #: The fork runs in its own directory. Without this it inherits the
    #: companion's, which the launch contract forbids.
    cwd: Path | None = None
    unavailable_reason: str | None = None


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


def is_loopback_url(url: str) -> bool:
    """Whether `url` names an MCP server on THIS machine.

    THE security boundary for vendor-run servers. The companion runs inside the
    customer's network, so a companion that will dial an arbitrary URL is an
    SSRF primitive reachable through whatever can influence an allowlist file —
    cloud metadata at 169.254.169.254 being the classic target.

    Scheme is restricted to http/https and the host is matched EXACTLY against
    the loopback names, plus the whole 127.0.0.0/8 block. A hostname that merely
    starts with "127.0.0.1" is a different host and is refused.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _launched_by(allowlist: Path) -> str:
    """Who starts this server, per its allowlist. Unreadable or undeclared means
    the historical default: a vendored fork this companion launches."""
    try:
        text = allowlist.read_text(encoding="utf-8")
    except OSError:
        return "companion"
    for line in text.splitlines():
        match = _LAUNCHED_BY_RE.match(line)
        if match is not None:
            return match.group(1)
    return "companion"


def _server_url(allowlist: Path, name: str) -> str | None:
    """The declared vendor-run endpoint, or None for a vendored stdio fork."""
    try:
        text = allowlist.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        match = _URL_LINE_RE.match(line)
        if match is None:
            continue
        url = match.group(1)
        if not is_loopback_url(url):
            logger.error(
                "REFUSED server %r: url %r is not loopback; the companion only "
                "connects to MCP servers on this machine",
                name,
                url,
            )
            return ""
        return url
    return None


def _private_interpreter(root_resolved: Path, server_dir: Path, name: str) -> Path | None:
    """The fork's own interpreter, or None when it has no private env.

    A fork with no dependencies needs none, so absence is not an error. A
    present-but-escaping one IS: the same symlink-swap guard the launch command
    gets, because this path is executed.
    """
    interpreter = server_dir / PRIVATE_ENV_INTERPRETER
    if not interpreter.exists():
        return None
    resolved = interpreter.resolve()
    if not resolved.is_relative_to(root_resolved):
        logger.error("REFUSED private interpreter for %r: resolves outside %s", name, root_resolved)
        return None
    if not os.access(resolved, os.X_OK):
        logger.error("REFUSED private interpreter for %r: %s is not executable", name, interpreter)
        return None
    return resolved


def _env_passthrough(server_dir: Path, name: str) -> tuple[str, ...]:
    """Variable names the fork declared, from its Solus-authored env.allow."""
    try:
        text = (server_dir / ENV_ALLOW_FILE).read_text(encoding="utf-8")
    except OSError:
        return ()
    names: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _ENV_NAME_RE.fullmatch(line) is None:
            logger.error(
                "ignoring %r in %s env.allow: not an environment variable name", line, name
            )
            continue
        names.append(line)
    return tuple(names)


def _host_discovered_env(name: str) -> dict[str, str]:
    """Values only the companion can discover about this machine, by server.

    The kicad fork cannot find a GUI install under its pinned PATH; we can."""
    cli = find_kicad_cli() if name == "kicad" else None
    return {KICAD_CLI_ENV: cli} if cli is not None else {}


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
        owner = _launched_by(allowlist)
        if owner != "companion":
            # Not ours to start. Skipping is the WHOLE behaviour: trying anyway
            # is how a cloud-side fork (no Node here) took the bridge down with
            # an abnormal session end before `hello` (SOLUSDEV-252, live).
            logger.info("server %r is launched by %s; not starting it here", name, owner)
            continue
        reason = unavailable_reason(root_resolved, server_dir, sys.platform)
        if reason is not None:
            servers.append(ServerLaunch(name=name, unavailable_reason=reason))
            continue
        url = _server_url(allowlist, name)
        if url == "":  # declared, but refused as non-loopback
            continue
        command = None
        if url is None:
            # No url ⇒ a vendored fork, which must have a launcher.
            command = _launch_command(root_resolved, server_dir, name)
            if command is None:
                continue
        # Start from main's H3 workspace knob, then add ours — one dict, so
        # neither variable is lost.
        env: dict[str, str] = dict(declared_env)
        interpreter = _private_interpreter(root_resolved, server_dir, name)
        if interpreter is not None:
            env[INTERPRETER_ENV] = str(interpreter)
        env.update(_host_discovered_env(name))
        servers.append(
            ServerLaunch(
                name=name,
                command=command,
                url=url,
                env=env,
                env_passthrough=_env_passthrough(server_dir, name),
                cwd=server_dir.resolve(),
            )
        )
    if not servers:
        # A wrong root and a correct-but-empty one used to be indistinguishable:
        # the glob simply yielded nothing and the companion ran with no tools.
        logger.warning("no MCP servers found under %s — is the integrations root correct?", root)
    return tuple(servers)


def default_integrations_root(executable: str | None = None) -> Path | None:
    """The vendored tree next to a packaged companion binary, if it is there.

    `SOLUS_COMPANION_INTEGRATIONS_ROOT` was required with no default and the
    desktop app never set it, so a packaged companion died at config validation
    while shipping the tree right beside itself. No default is invented when the
    tree is absent — that would turn a packaging mistake into a silent
    zero-server run.
    """
    binary = Path(executable or sys.executable)
    candidate = binary.parent / _PACKAGED_TREE
    return candidate if candidate.is_dir() else None


def _tighten_solus_home(parent: Path) -> None:
    """Ensure ~/.solus is 0700 (ADR-034, SOLUSDEV-166).

    MCP forks inherit HOME, so the directory must never be group/world
    readable. Runs on EVERY load — the common path reads a pre-existing valid
    id and would otherwise never re-tighten a dir an older build created with
    the default umask. Scoped to the Solus home ONLY: a custom
    SOLUS_COMPANION_INSTANCE_FILE points elsewhere (e.g. /tmp), and chmodding
    that would be wrong (review M6). Best-effort — a chmod failure must never
    stop the companion from starting.
    """
    if parent.name != SOLUS_HOME_DIRNAME:
        return
    try:
        if parent.is_dir():
            os.chmod(parent, 0o700)
    except OSError:
        pass


def load_instance_id(path: Path) -> str:
    """Read the persisted companion instance id, or create one (0600)."""
    _tighten_solus_home(path.parent)
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{32}", existing):
            return existing
    except OSError:
        pass
    instance_id = uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    _tighten_solus_home(path.parent)  # a freshly created dir also gets 0700
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
    configured = source.get("SOLUS_COMPANION_INTEGRATIONS_ROOT", "")
    if configured:
        integrations_root = Path(configured)
    else:
        fallback = default_integrations_root()
        if fallback is None:
            raise ValueError("SOLUS_COMPANION_INTEGRATIONS_ROOT is required")
        integrations_root = fallback
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
