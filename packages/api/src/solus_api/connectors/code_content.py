"""Bounded, immutable code reads through the connected provider's HTTP client."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import quote

import httpx

from solus_api.connectors.code_host import REPO_ROOT_KEY
from solus_api.connectors.contracts import (
    Connector,
    Credentials,
    RelationOut,
    SyncError,
    SyncResult,
)
from solus_api.connectors.github import GITHUB_API, GitHubConnector
from solus_api.connectors.gitlab import GitLabConnector
from solus_api.connectors.local_folder import ros_entities
from solus_api.graph import kinds
from solus_api.software.policy_reader import CONFIG_SUFFIXES, read_policy
from solus_api.software.ros_reader import (
    RosPackageSources,
    RosSourceFile,
    package_name,
    parse_ros_workspace,
)

logger = logging.getLogger("solus.connectors.code_content")

MAX_CODE_BYTES: Final = 262_144
_SECRET_NAMES: Final = frozenset(
    {
        ".git",
        ".ssh",
        ".aws",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
    }
)


class CodeContentError(ValueError):
    """Safe, authored failure; never includes provider response bodies."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def safe_code_path(path: str) -> str:
    parts = path.split("/")
    if (
        not path
        or len(path) > 1024
        or "\\" in path
        or ":" in parts[0]
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise CodeContentError("File path must be a valid repository-relative path.")
    if any(part.lower().startswith(".env") or part.lower() in _SECRET_NAMES for part in parts):
        raise CodeContentError("Credential files cannot be read as code context.")
    if parts[-1].lower().endswith((".pem", ".key", ".p12", ".pfx", ".keystore")):
        raise CodeContentError("Credential files cannot be read as code context.")
    return path


def decode_code(raw: bytes) -> str:
    if len(raw) > MAX_CODE_BYTES:
        raise CodeContentError("File exceeds the code context byte limit.")
    if b"\x00" in raw:
        raise CodeContentError("Binary files cannot be read as code context.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodeContentError("File is not UTF-8 text.") from exc


class CodeContentReader:
    def __init__(self, connector: GitHubConnector | GitLabConnector) -> None:
        self.connector = connector

    def _url(self, repo: str, path: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", repo) or any(
            part in {".", ".."} for part in repo.split("/")
        ):
            raise CodeContentError("The source has an invalid repository identity.")
        if isinstance(self.connector, GitHubConnector):
            if repo.count("/") != 1:
                raise CodeContentError("The source has an invalid repository identity.")
            return f"{GITHUB_API}/repos/{repo}/contents/{quote(path, safe='/')}"
        return f"{self.connector._project_url(repo)}/repository/files/{quote(path, safe='')}/raw"

    async def read(
        self,
        credentials: Credentials,
        *,
        repo: str,
        path: str,
        commit: str,
        blob_sha: str | None = None,
    ) -> str:
        safe_code_path(path)
        if re.fullmatch(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?", commit) is None:
            raise CodeContentError(
                "No immutable synced commit is available; sync this source first."
            )
        url = self._url(repo, path)
        params = {"ref": commit}
        if isinstance(self.connector, GitHubConnector) and blob_sha is not None:
            if re.fullmatch(r"[0-9a-fA-F]{40}", blob_sha) is None:
                raise CodeContentError("The graph file blob identity is invalid; sync again.")
            url = f"{GITHUB_API}/repos/{repo}/git/blobs/{blob_sha}"
            params = {}
        headers = (
            {"Accept": "application/vnd.github.raw+json"}
            if isinstance(self.connector, GitHubConnector)
            else {}
        )
        try:
            async with self.connector._http(credentials) as client:
                async with client.stream(
                    "GET", url, params=params, headers=headers, follow_redirects=False
                ) as response:
                    return await self._text(response)
        except httpx.HTTPError as exc:
            raise CodeContentError("The repository provider could not be reached.") from exc

    @staticmethod
    async def _text(response: httpx.Response) -> str:
        if response.status_code != 200:
            raise CodeContentError(
                "The repository provider refused the file read.", status=response.status_code
            )
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_CODE_BYTES:
            raise CodeContentError("File exceeds the code context byte limit.")
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            if len(raw) + len(chunk) > MAX_CODE_BYTES:
                raise CodeContentError("File exceeds the code context byte limit.")
            raw.extend(chunk)
        return decode_code(bytes(raw))


# ----------------------------------------------- the software readers (SOLUSDEV-321 P6)

#: The files one code-host sync reads for the software readers, at most.
MAX_SOFTWARE_READS: Final = 64
MAX_SOFTWARE_PACKAGES: Final = 32
MAX_PACKAGE_FILES: Final = 32
MAX_PACKAGE_DEPTH: Final = 3
_LAUNCH_SUFFIXES: Final = (".launch.py", ".launch.xml")
_SETUP_FILES: Final = ("setup.py", "setup.cfg")
_TEST_DIRS: Final = frozenset({"test", "tests"})
#: The files one sync reads for the policy reader, at most (within MAX_SOFTWARE_READS): the
#: `.py` and config files whose own name or directory names a policy, a controller, an
#: environment or a config, no deeper than MAX_POLICY_DEPTH and outside vendored trees.
MAX_POLICY_READS: Final = 16
MAX_POLICY_DEPTH: Final = 4
_POLICY_WORDS: Final = ("policy", "controller", "env", "config")
_VENDORED: Final = frozenset({"site-packages", "node_modules", "venv", "vendor", "third_party"})
#: The companion's credential-shaped name rule (`integrations/mcp/local/solus/ros.py:
#: SECRET_NAME`, R135), applied to every path component of a file before it is read.
_SECRET_NAME: Final = re.compile(
    r"secret|credential|token|passw|apikey|api_key|private|auth|id_rsa|id_ed25519"
    r"|\.env|\.pem|\.key|\.p12|\.pfx",
    re.IGNORECASE,
)


def _shippable_path(parts: list[str]) -> bool:
    """No hidden, test or credential-shaped component (the companion's R135 rule)."""
    return not any(
        part.startswith(".") or part.lower() in _TEST_DIRS or _SECRET_NAME.search(part)
        for part in parts
    )


def _launch_like(rel: list[str]) -> bool:
    name = rel[-1].lower()
    if name.endswith(_LAUNCH_SUFFIXES) or (len(rel) == 1 and name in _SETUP_FILES):
        return True
    return len(rel) == 2 and rel[0] == "launch" and name.endswith((".yaml", ".yml"))


def _package_members(
    directory: str, name: str | None, paths: list[str], nested: set[str]
) -> list[str]:
    """What the ROS reader needs of one package and nothing more: its launch and setup files and
    the modules of its own module directory, launch and setup files first, within the caps."""
    prefix = f"{directory}/" if directory else ""
    found: list[list[str]] = []
    for path in paths:
        rel = path[len(prefix) :].split("/") if path.startswith(prefix) else []
        inner = any(path.startswith(f"{other}/") for other in nested)
        if not rel or rel == ["package.xml"] or inner or len(rel) > MAX_PACKAGE_DEPTH:
            continue
        own = name is not None and len(rel) > 1 and rel[0] == name and rel[-1].endswith(".py")
        if _shippable_path(rel) and (_launch_like(rel) or own):
            found.append(rel)
    ordered = sorted(found, key=lambda rel: (not _launch_like(rel), rel))
    return [prefix + "/".join(rel) for rel in ordered[:MAX_PACKAGE_FILES]]


class _SoftwareReads:
    """One sync's bounded reads: at most MAX_SOFTWARE_READS, each failure a SyncError."""

    def __init__(
        self,
        reader: CodeContentReader,
        credentials: Credentials,
        repo: str,
        commit: str,
        blobs: dict[str, str | None],
    ) -> None:
        self.reader, self.credentials, self.repo, self.commit = reader, credentials, repo, commit
        self.blobs = blobs
        self.left = MAX_SOFTWARE_READS
        self.errors: list[SyncError] = []
        self.capped = False

    async def text(self, path: str) -> str | None:
        if self.left <= 0:
            self.capped = True
            return None
        self.left -= 1
        sha = self.blobs.get(path)
        blob = sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha) else None
        try:
            return await self.reader.read(
                self.credentials, repo=self.repo, path=path, commit=self.commit, blob_sha=blob
            )
        except CodeContentError as exc:
            self.errors.append(SyncError(item=path, message=f"{path}: {exc}"))
            return None


def _policy_candidates(paths: list[str]) -> list[str]:
    """The files the policy reader may state an interface in, at most MAX_POLICY_READS."""
    found = []
    for path in sorted(paths):
        parts = path.split("/")
        named = " ".join(parts[-2:]).lower()
        if (
            path.endswith((".py", *CONFIG_SUFFIXES))
            and len(parts) <= MAX_POLICY_DEPTH
            and _shippable_path(parts)
            and not _VENDORED & set(parts)
            and any(word in named for word in _POLICY_WORDS)
        ):
            found.append(path)
    return found[:MAX_POLICY_READS]


async def _policy_interfaces(
    reads: _SoftwareReads, candidates: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Each candidate that states an interface → its interfaces, as `attrs.module_interfaces`."""
    found: dict[str, list[dict[str, Any]]] = {}
    for path in candidates:
        text = await reads.text(path)
        interfaces = read_policy(path, text) if text is not None else []
        if interfaces:
            found[path] = [interface.model_dump(mode="json") for interface in interfaces]
    return found


async def read_software(
    connector: Connector, credentials: Credentials, config: Mapping[str, Any], result: SyncResult
) -> SyncResult:
    """A code-host sync's result with what the software readers find in its files: the ROS
    packages it commits, as nodes and topics under the repo node, and the policy and controller
    interfaces its modules state, on those files as `module_interfaces`. Reads go through
    `CodeContentReader` at the synced commit, at most MAX_SOFTWARE_READS of them; a failed read
    is a sync error on its path. Any other connector, or anything going wrong, leaves the result
    as it was: the readers never fail a sync. No model call."""
    if not isinstance(connector, GitHubConnector | GitLabConnector):
        return result
    try:
        reader = CodeContentReader(connector)
        return await _read_software(reader, credentials, str(config.get("repo", "")), result)
    except Exception:  # noqa: BLE001 — the software readers never fail a sync
        logger.exception("software reads failed; the sync lands without them")
        return result


async def _read_software(
    reader: CodeContentReader, credentials: Credentials, repo: str, result: SyncResult
) -> SyncResult:
    commit = result.cursor.get("sha")
    blobs: dict[str, str | None] = {
        entity.properties["path"]: entity.properties.get("sha")
        for entity in result.entities
        if entity.type == kinds.CODE_FILE and isinstance(entity.properties.get("path"), str)
    }
    manifests = sorted(
        path
        for path in blobs
        if path.rsplit("/", 1)[-1] == "package.xml" and _shippable_path(path.split("/"))
    )[:MAX_SOFTWARE_PACKAGES]
    candidates = _policy_candidates(list(blobs))
    if not (manifests or candidates) or not isinstance(commit, str):
        return result
    reads = _SoftwareReads(reader, credentials, repo, commit, blobs)
    packages = await _ros_packages(reads, manifests, sorted(blobs)) if manifests else []
    ros = ros_entities(parse_ros_workspace(packages)) if packages else []
    interfaces = await _policy_interfaces(reads, candidates)
    if reads.capped:
        reads.errors.append(
            SyncError(
                item=REPO_ROOT_KEY,
                message=f"software reads stopped at {MAX_SOFTWARE_READS} files; "
                "later ROS and policy files were not read",
            )
        )
    stated = [
        entity.model_copy(
            update={
                "properties": {
                    **entity.properties,
                    "module_interfaces": interfaces[entity.properties["path"]],
                }
            }
        )
        if entity.type == kinds.CODE_FILE and entity.properties.get("path") in interfaces
        else entity
        for entity in result.entities
    ]
    return result.model_copy(
        update={
            "entities": [*stated, *ros],
            "relations": [
                *result.relations,
                *(
                    RelationOut(from_key=REPO_ROOT_KEY, to_key=e.source_key, type="contains")
                    for e in ros
                ),
            ],
            "errors": [*result.errors, *reads.errors],
        }
    )


async def _ros_packages(
    reads: _SoftwareReads, manifests: list[str], paths: list[str]
) -> list[RosPackageSources]:
    """Every manifest first (so a cap keeps the packages), then each package's members."""
    texts = {manifest: await reads.text(manifest) for manifest in manifests}
    directories = {manifest: manifest.rpartition("/")[0] for manifest in manifests}
    packages: list[RosPackageSources] = []
    for manifest, text in texts.items():
        if text is None:
            continue
        directory = directories[manifest]
        nested = {d for d in directories.values() if d != directory and d.startswith(directory)}
        files: list[RosSourceFile] = []
        for path in _package_members(directory, package_name(text), paths, nested):
            body = await reads.text(path)
            if body is not None:
                files.append(RosSourceFile(path, body))
        packages.append(RosPackageSources(RosSourceFile(manifest, text), tuple(files)))
    return packages
