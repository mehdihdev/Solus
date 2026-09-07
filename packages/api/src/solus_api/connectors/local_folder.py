"""`LocalFolderConnector` — a working copy on the user's machine as a graph source
(SOLUSDEV-249 / INTEGRATIONS I2; `docs/api/local-folder.md`, `docs/architecture/local-folders.md`).

The connector never touches a disk. The companion's Solus-authored `local` server
scans its own workspace (the linked folder) and answers `local.scan_folder`; a
`FolderAcquirer` (the bridge one lives in `local_acquire.py`) hands that answer
here, and this module DERIVES the graph from it, purely:

* `.git/config`'s origin → `normalize_remote` → `owner/name` + host, so the sync
  cursor carries what `services/local_links.py` needs to edge the clone to the
  matching GitHub/GitLab repo node — a deterministic link, never a fingerprint;
* file suffixes (classified companion-side, re-validated here against the same
  closed vocabulary) → one node per tool PROJECT: a KiCad project per directory,
  an Altium project per `.PrjPcb`, a CAD folder per directory, an Arduino sketch
  per sketch directory, one Python node at the root. Never a node per file.

Every path in the graph is folder-relative; the scan model refuses absolute and
parent-escaping paths at the boundary (CLAUDE.md §7 — companion output is
untrusted). No acquirer, or an acquirer that declines (bridge offline, wrong
machine), is a NO-SIGNAL outcome (`api_unreachable`): the source keeps its
graph and the next `change` frame or manual sync tries again — never a fake
empty sync that would tombstone every node.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, ClassVar, Final, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Connector,
    ConnectorError,
    Credentials,
    Domain,
    EntityOut,
    RelationOut,
    SyncContext,
    SyncError,
    SyncResult,
)

PROVIDER: Final = "local"
CLONE_KEY: Final = "clone:"
CONTAINS: Final = "contains"
#: The companion tool names this connector dispatches (composed `{server}.{tool}`).
SCAN_TOOL: Final = "local.scan_folder"
DIGEST_TOOL: Final = "local.folder_digest"
OPEN_TOOL: Final = "local.open_in_tool"

MACHINE_ID_RE: Final = re.compile(r"^[0-9a-f]{32}$")
MAX_SCAN_FILES: Final = 2000
MAX_LISTED_CAD_FILES: Final = 100
MAX_LISTED_TOP_DIRS: Final = 50
NO_SIGNAL_MESSAGE: Final = "this machine's Solus companion is not connected"

ToolName = Literal["kicad", "altium", "cad", "arduino", "python"]
HostName = Literal["github", "gitlab", "other"]

#: Graph kinds this connector lands, by tool — read by the routes to know which
#: nodes are "detected projects" and which tool can open them.
PROJECT_KINDS: Final[dict[ToolName, str]] = {
    "kicad": "kicad_project",
    "altium": "altium_project",
    "cad": "cad_folder",
    "arduino": "arduino_sketch",
    "python": "python_code",
}
ROOT_KINDS: Final = frozenset({"local_clone", "local_folder"})
LOCAL_KINDS: Final = frozenset(PROJECT_KINDS.values()) | ROOT_KINDS


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


#: What the cloud's ingress redaction leaves behind (`agent/tools/untrusted.py`).
#: Paths travel as SEGMENTS precisely because a joined path over 40 chars is
#: secret-shaped to that gate; a single segment that long is rare, and when it
#: happens the file is dropped with a recorded error rather than invented.
REDACTED_SEGMENT: Final = "[REDACTED]"
MAX_PATH_PARTS: Final = 64
MAX_SEGMENT_CHARS: Final = 255
#: A joined path longer than this cannot become a `source_key`/`name` within the
#: contract's bounds; such a file is dropped and reported, never a raise.
MAX_JOINED_PATH_CHARS: Final = 900


def _segments(value: list[str]) -> list[str]:
    if not value:
        raise ValueError("a file needs at least one path segment")
    for part in value:
        if part in ("", ".", "..") or "/" in part or "\\" in part or "\x00" in part:
            raise ValueError("path segment must not escape or be empty")
        if len(part) > MAX_SEGMENT_CHARS:
            raise ValueError("path segment too long")
    return value


class ScannedFile(_Wire):
    parts: list[str] = Field(min_length=1, max_length=MAX_PATH_PARTS)
    size: int = Field(ge=0)
    hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    tool: ToolName

    _parts = field_validator("parts")(_segments)

    @property
    def path(self) -> str:
        return "/".join(self.parts)

    @property
    def redacted(self) -> bool:
        return any(part == REDACTED_SEGMENT for part in self.parts)


def _no_credentials(value: str | None) -> str | None:
    """A remote URL carrying `user:token@` is a credential the companion must
    have stripped (security review H2); refusing it here keeps the whole scan
    out rather than letting the token sit in process memory."""
    if value is None:
        return None
    if "://" in value:
        parts = urlsplit(value)
        if parts.password is not None or (parts.username and ":" in parts.username):
            raise ValueError("remote_url must not carry credentials")
    elif "@" in value and ":" in value.split("@", 1)[0]:
        raise ValueError("remote_url must not carry credentials")
    return value


class GitInfo(_Wire):
    remote_url: str | None = Field(default=None, max_length=2048)
    branch: str | None = Field(default=None, max_length=255)
    head: str | None = Field(default=None, max_length=40)

    _clean = field_validator("remote_url")(_no_credentials)


class FolderScan(_Wire):
    """`local.scan_folder`'s answer (`docs/api/local-folder.md` §4) — untrusted,
    validated at this boundary. `extra="forbid"` so a companion cannot smuggle
    an `artifact_path` or any other key past the model."""

    schema_version: Literal[1] = 1
    root_name: str = Field(min_length=1, max_length=255)
    git: GitInfo | None = None
    files: list[ScannedFile] = Field(default_factory=list, max_length=MAX_SCAN_FILES)
    digest: str = Field(min_length=1, max_length=128, pattern=r"^[0-9a-f]+$")
    truncated: bool = False
    tools_installed: dict[str, bool] = Field(default_factory=dict)

    @field_validator("tools_installed")
    @classmethod
    def _bounded_tools(cls, value: dict[str, bool]) -> dict[str, bool]:
        if len(value) > 32 or any(len(k) > 32 for k in value):
            raise ValueError("tools_installed is oversized")
        return value


class FolderDigest(_Wire):
    digest: str = Field(min_length=1, max_length=128, pattern=r"^[0-9a-f]+$")
    truncated: bool = False


class FolderAcquirer(Protocol):
    """How the connector reaches the machine. `None` = decline (offline, wrong
    machine, tool not offered, malformed answer) — never an exception the
    connector must interpret."""

    async def scan(self, config: dict[str, Any]) -> FolderScan | None: ...

    async def digest(self, config: dict[str, Any]) -> str | None: ...


# ---------------------------------------------------------------- git remotes


@dataclass(frozen=True)
class RemoteRef:
    host: HostName
    repo: str  # owner/name (GitLab: group/sub/name)


_SCP_REMOTE: Final = re.compile(r"^(?:[A-Za-z0-9_.-]+@)?([A-Za-z0-9_.-]+):(?!//)(.+)$")
_REPO_PATH: Final = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+$")


def _host_kind(host: str, gitlab_host: str | None) -> HostName:
    host = host.lower()
    if host == "github.com":
        return "github"
    if host == "gitlab.com" or (gitlab_host and host == gitlab_host.lower()):
        return "gitlab"
    return "other"


def normalize_remote(url: str, *, gitlab_host: str | None) -> RemoteRef | None:
    """`git@github.com:o/r.git`, `https://github.com/o/r`, `ssh://git@host/o/r.git`
    → `(host kind, "o/r")`. Case is preserved in the repo path (GitHub matches
    case-insensitively, but the stored `Source.config["repo"]` is what the
    provider returned; the linker compares case-folded). Anything unparseable,
    credential-bearing or not host/owner/name shaped → None, never a guess."""
    raw = url.strip()
    if not raw or raw.startswith("-") or any(c.isspace() for c in raw):
        return None
    host: str | None = None
    path: str | None = None
    if "://" in raw:
        parts = urlsplit(raw)
        if parts.scheme not in ("https", "http", "ssh", "git", "git+ssh", "ssh+git"):
            return None
        host, path = parts.hostname, parts.path
    else:
        match = _SCP_REMOTE.match(raw)
        if match is None:
            return None
        host, path = match.group(1), match.group(2)
    if not host or not path:
        return None
    repo = path.strip("/")
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not _REPO_PATH.match(repo):
        return None
    return RemoteRef(host=_host_kind(host, gitlab_host), repo=repo)


# --------------------------------------------------------------- the mapping


def _dir_of(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return "" if parent == "." else parent


def _name_of_dir(directory: str, root_name: str) -> str:
    return PurePosixPath(directory).name if directory else root_name


def _kicad_projects(files: list[ScannedFile]) -> list[tuple[EntityOut, str]]:
    by_dir: dict[str, list[ScannedFile]] = defaultdict(list)
    for file in files:
        by_dir[_dir_of(file.path)].append(file)
    out: list[tuple[EntityOut, str]] = []
    for directory in sorted(by_dir):
        group = by_dir[directory]
        project = next((f.path for f in group if f.path.lower().endswith(".kicad_pro")), None)
        schematics = sorted(f.path for f in group if f.path.lower().endswith(".kicad_sch"))
        boards = sorted(f.path for f in group if f.path.lower().endswith(".kicad_pcb"))
        name = PurePosixPath(project).stem if project else PurePosixPath(directory).name
        entity = EntityOut(
            source_key=f"kicad:{directory}",
            type=PROJECT_KINDS["kicad"],
            domain=Domain.ELECTRICAL,
            name=name or directory or "kicad",
            properties={
                "path": directory or ".",
                "project_file": project,
                "schematics": schematics,
                "boards": boards,
            },
        )
        out.append((entity, project or (schematics + boards)[0]))
    return out


def _altium_projects(files: list[ScannedFile]) -> list[tuple[EntityOut, str]]:
    by_dir: dict[str, list[ScannedFile]] = defaultdict(list)
    for file in files:
        by_dir[_dir_of(file.path)].append(file)
    out: list[tuple[EntityOut, str]] = []
    for directory in sorted(by_dir):
        group = by_dir[directory]
        projects = sorted(f.path for f in group if f.path.lower().endswith(".prjpcb"))
        schematics = sorted(f.path for f in group if f.path.lower().endswith(".schdoc"))
        boards = sorted(f.path for f in group if f.path.lower().endswith(".pcbdoc"))
        candidates: list[str | None] = list(projects) or [None]
        for project in candidates:
            key = f"altium:{project}" if project else f"altium:{directory}"
            name = PurePosixPath(project).stem if project else PurePosixPath(directory).name
            entity = EntityOut(
                source_key=key,
                type=PROJECT_KINDS["altium"],
                domain=Domain.ELECTRICAL,
                name=name or "altium",
                properties={
                    "path": directory or ".",
                    "project_file": project,
                    "schematics": schematics,
                    "boards": boards,
                },
            )
            out.append((entity, project or (schematics + boards)[0]))
    return out


def _cad_folders(files: list[ScannedFile], root_name: str) -> list[tuple[EntityOut, str]]:
    by_dir: dict[str, list[str]] = defaultdict(list)
    for file in files:
        by_dir[_dir_of(file.path)].append(file.path)
    out: list[tuple[EntityOut, str]] = []
    for directory in sorted(by_dir):
        listed = sorted(by_dir[directory])
        entity = EntityOut(
            source_key=f"cad:{directory}",
            type=PROJECT_KINDS["cad"],
            domain=Domain.MECHANICAL,
            name=_name_of_dir(directory, root_name),
            properties={
                "path": directory or ".",
                "files": listed[:MAX_LISTED_CAD_FILES],
                "file_count": len(listed),
            },
        )
        out.append((entity, directory or "."))
    return out


def _arduino_sketches(files: list[ScannedFile], root_name: str) -> list[tuple[EntityOut, str]]:
    by_dir: dict[str, list[str]] = defaultdict(list)
    for file in files:
        by_dir[_dir_of(file.path)].append(file.path)
    out: list[tuple[EntityOut, str]] = []
    for directory in sorted(by_dir):
        sketch = sorted(by_dir[directory])[0]
        entity = EntityOut(
            source_key=f"arduino:{directory}",
            type=PROJECT_KINDS["arduino"],
            domain=Domain.CODE,
            name=_name_of_dir(directory, root_name),
            properties={"path": directory or ".", "sketch_file": sketch},
        )
        out.append((entity, sketch))
    return out


def _python_code(files: list[ScannedFile], root_name: str) -> list[tuple[EntityOut, str]]:
    if not files:
        return []
    top_dirs = sorted({p.parts[0] for f in files if len((p := PurePosixPath(f.path)).parts) > 1})
    entity = EntityOut(
        source_key="python:",
        type=PROJECT_KINDS["python"],
        domain=Domain.CODE,
        name=f"{root_name} (python)",
        properties={"file_count": len(files), "top_dirs": top_dirs[:MAX_LISTED_TOP_DIRS]},
    )
    return [(entity, ".")]


def _root_entity(scan: FolderScan, remote: RemoteRef | None, machine_name: str) -> EntityOut:
    git = scan.git
    return EntityOut(
        source_key=CLONE_KEY,
        type="local_clone" if git is not None else "local_folder",
        domain=Domain.CODE,
        name=scan.root_name,
        properties={
            "machine_name": machine_name,
            "branch": git.branch if git else None,
            "head": git.head if git else None,
            "remote": remote.repo if remote else None,
            "host": remote.host if remote else None,
            "file_count": len(scan.files),
            "truncated": scan.truncated,
        },
    )


@dataclass(frozen=True)
class LocalGraph:
    entities: list[EntityOut]
    relations: list[RelationOut]
    #: Per detected node: the folder-relative path a tool opens (`.` for the root).
    open_paths: dict[str, str]
    remote: RemoteRef | None
    #: Files whose name the ingress redaction masked — skipped, reported, never guessed.
    dropped_redacted: int = 0
    #: Files whose joined path exceeds what a graph key can hold — skipped, reported.
    dropped_oversize: int = 0


def derive_local_graph(
    scan: FolderScan, *, machine_name: str, gitlab_host: str | None
) -> LocalGraph:
    remote = (
        normalize_remote(scan.git.remote_url, gitlab_host=gitlab_host)
        if scan.git is not None and scan.git.remote_url
        else None
    )
    by_tool: dict[ToolName, list[ScannedFile]] = defaultdict(list)
    dropped = 0
    oversize = 0
    for file in scan.files:
        if file.redacted:
            dropped += 1
            continue
        if len(file.path) > MAX_JOINED_PATH_CHARS:
            oversize += 1
            continue
        by_tool[file.tool].append(file)
    projects: list[tuple[EntityOut, str]] = [
        *_kicad_projects(by_tool["kicad"]),
        *_altium_projects(by_tool["altium"]),
        *_cad_folders(by_tool["cad"], scan.root_name),
        *_arduino_sketches(by_tool["arduino"], scan.root_name),
        *_python_code(by_tool["python"], scan.root_name),
    ]
    root = _root_entity(scan, remote, machine_name)
    entities = [root, *(entity for entity, _ in projects)]
    relations = [
        RelationOut(from_key=CLONE_KEY, to_key=entity.source_key, type=CONTAINS)
        for entity, _ in projects
    ]
    open_paths = {CLONE_KEY: ".", **{entity.source_key: path for entity, path in projects}}
    return LocalGraph(
        entities=entities,
        relations=relations,
        open_paths=open_paths,
        remote=remote,
        dropped_redacted=dropped,
        dropped_oversize=oversize,
    )


def build_local_graph(
    scan: FolderScan, *, machine_name: str, gitlab_host: str | None
) -> tuple[list[EntityOut], list[RelationOut]]:
    graph = derive_local_graph(scan, machine_name=machine_name, gitlab_host=gitlab_host)
    return graph.entities, graph.relations


def detected_entries(graph: LocalGraph) -> list[dict[str, Any]]:
    """The cursor's `detected` list (`docs/api/local-folder.md` §2): what the
    routes hand the desktop without re-deriving anything from the graph."""
    kind_to_tool = {kind: tool for tool, kind in PROJECT_KINDS.items()}
    return [
        {
            "entity_key": entity.source_key,
            "tool": kind_to_tool.get(entity.type),
            "name": entity.name,
            "path": graph.open_paths[entity.source_key],
        }
        for entity in graph.entities
    ]


# --------------------------------------------------------------- the connector


class LocalFolderConnector(Connector):
    provider: ClassVar[str] = PROVIDER
    auth_kind: ClassVar[AuthKind] = AuthKind.NONE
    config_fields: ClassVar[tuple[str, ...]] = ("machine_id", "machine_name", "folder_name")
    #: Read duck-typed by `runtime.run_sync` (like `selection`/`access_modes` in
    #: the registry): an auth-none connector that CAN answer "did it change?"
    #: cheaply, so the freshness gate applies to it too.
    cheap_probe: ClassVar[bool] = True

    def __init__(
        self, *, acquirer: FolderAcquirer | None = None, gitlab_host: str | None = None
    ) -> None:
        self._acquirer = acquirer
        self._gitlab_host = gitlab_host

    async def validate_credentials(self, credentials: Credentials) -> AccountInfo:
        return AccountInfo(external_id="local", login="local folder", name="This computer")

    async def detect_changes(self, ctx: SyncContext) -> bool:
        if self._acquirer is None:
            raise ConnectorError("api_unreachable", NO_SIGNAL_MESSAGE)
        digest = await self._acquirer.digest(dict(ctx.config))
        if digest is None:
            raise ConnectorError("api_unreachable", NO_SIGNAL_MESSAGE)
        return digest != ctx.cursor.get("digest")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        if self._acquirer is None:
            raise ConnectorError("api_unreachable", NO_SIGNAL_MESSAGE)
        scan = await self._acquirer.scan(dict(ctx.config))
        if scan is None:
            raise ConnectorError("api_unreachable", NO_SIGNAL_MESSAGE)
        machine_name = str(ctx.config.get("machine_name") or "this computer")
        graph = derive_local_graph(scan, machine_name=machine_name, gitlab_host=self._gitlab_host)
        errors: list[SyncError] = []
        if graph.dropped_redacted:
            errors.append(
                SyncError(
                    item=CLONE_KEY,
                    message=(
                        f"{graph.dropped_redacted} file(s) skipped: a path segment looked "
                        "secret-shaped to the ingress filter and was masked"
                    ),
                )
            )
        if graph.dropped_oversize:
            errors.append(
                SyncError(
                    item=CLONE_KEY,
                    message=f"{graph.dropped_oversize} file(s) skipped: path longer than "
                    f"{MAX_JOINED_PATH_CHARS} characters",
                )
            )
        if scan.truncated:
            errors.append(
                SyncError(
                    item=CLONE_KEY,
                    message=(
                        f"scan truncated at {MAX_SCAN_FILES} files; later files were not classified"
                    ),
                )
            )
        cursor: dict[str, Any] = {
            "digest": scan.digest,
            "remote": graph.remote.repo if graph.remote else None,
            "host": graph.remote.host if graph.remote else None,
            "branch": scan.git.branch if scan.git else None,
            "tools_installed": dict(scan.tools_installed),
            "detected": detected_entries(graph),
        }
        return SyncResult(
            entities=graph.entities, relations=graph.relations, cursor=cursor, errors=errors
        )
