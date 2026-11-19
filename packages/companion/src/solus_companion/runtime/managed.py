"""The Solus-managed Python — mcp-fork-runtime.md §7.

The manifest ships inside the companion and alone decides URL, hash and size.
Until a human has verified real python-build-standalone hashes it is a
placeholder (`verified: false`, all-zero hashes) and installation REFUSES with
`managed_hash_mismatch` before touching the network.

Download: HTTPS only, redirects only to HTTPS GitHub release hosts, streamed to
disk with the byte cap enforced while reading, SHA-256 verified BEFORE the
archive is opened. Extraction: every member vetted first (no absolute paths,
no `..`, no escaping links, no devices), then `tarfile` `filter="data"`, into a
temp tree swapped atomically into `<data>/mcp-python/<release>/`."""

import hashlib
import json
import logging
import posixpath
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from solus_companion.runtime.errors import RuntimeSetupError
from solus_companion.runtime.ownership import OwnerOnly
from solus_companion.runtime.protocol import ProgressLine, RuntimeLine
from solus_companion.runtime.provision import remove_path

logger = logging.getLogger("solus.companion.runtime")

MANIFEST_RESOURCE = "managed_manifest.json"
ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)
DOWNLOAD_TIMEOUT_SECONDS = 60.0
CHUNK_BYTES = 1024 * 1024
MAX_MEMBERS = 100_000
MAX_EXTRACTED_BYTES = 1_500_000_000
ZERO_HASH = "0" * 64
_URL_PATTERN = (
    r"^https://github\.com/astral-sh/python-build-standalone/releases/download/"
    r"[A-Za-z0-9._-]+/[A-Za-z0-9._+-]+\.tar\.gz$"
)
_DRIVE = re.compile(r"^[A-Za-z]:")

AssetKey = Literal["darwin-arm64", "darwin-x64", "win32-x64", "linux-x64", "linux-arm64"]


class ManagedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    url: Annotated[str, Field(pattern=_URL_PATTERN, max_length=512)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    max_bytes: Annotated[StrictInt, Field(gt=0, le=200_000_000)]


class ManagedManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    release: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$")]
    python_version: Annotated[str, Field(pattern=r"^3\.12\.(x|\d+)$")]
    #: Solus addition to the §7 shape: the human gate, flipped only together
    #: with real hashes checked against the release's SHA256SUMS.
    verified: StrictBool = False
    assets: dict[AssetKey, ManagedAsset]


def load_manifest() -> ManagedManifest:
    raw = resources.files("solus_companion.runtime").joinpath(MANIFEST_RESOURCE).read_bytes()
    return ManagedManifest.model_validate(json.loads(raw))


def platform_key(platform: str, machine: str) -> AssetKey | None:
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(
        machine.lower()
    )
    keys: dict[tuple[str, str | None], AssetKey] = {
        ("darwin", "arm64"): "darwin-arm64",
        ("darwin", "x64"): "darwin-x64",
        ("win32", "x64"): "win32-x64",
        ("linux", "x64"): "linux-x64",
        ("linux", "arm64"): "linux-arm64",
    }
    return keys.get((platform, arch))


def managed_interpreter(release_dir: Path, platform: str) -> Path:
    if platform == "win32":
        return release_dir / "python" / "python.exe"
    return release_dir / "python" / "bin" / "python3"


def redirect_allowed(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "") in ALLOWED_DOWNLOAD_HOSTS


class Stream(Protocol):
    def read(self, n: int, /) -> bytes: ...

    def close(self) -> None: ...


Fetcher = Callable[[str, float], tuple[Stream, int | None]]


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> urllib.request.Request | None:
        if not redirect_allowed(newurl):
            raise urllib.error.HTTPError(newurl, code, "redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_fetch(url: str, timeout: float) -> tuple[Stream, int | None]:  # pragma: no cover
    """The real fetcher (network). Only manifest URLs reach it (pinned pattern)."""
    if not redirect_allowed(url):
        raise urllib.error.URLError("refused non-https or non-GitHub URL")
    opener = urllib.request.build_opener(_GuardedRedirect())
    response = opener.open(url, timeout=timeout)  # noqa: S310 — https GitHub only, see above
    length = response.headers.get("Content-Length")
    return response, int(length) if length and length.isdigit() else None


def _refuse() -> RuntimeSetupError:
    return RuntimeSetupError("managed_extract_refused")


def _escapes(path: str) -> bool:
    norm = posixpath.normpath(path)
    return norm == ".." or norm.startswith("../") or norm.startswith("/")


def _vet(member: tarfile.TarInfo) -> None:
    name = member.name.replace("\\", "/")
    if name.startswith("/") or _DRIVE.match(name) or ".." in name.split("/"):
        raise _refuse()
    if not (member.isreg() or member.isdir() or member.issym() or member.islnk()):
        raise _refuse()  # devices, fifos, anything exotic
    if member.issym() or member.islnk():
        target = member.linkname.replace("\\", "/")
        if target.startswith("/") or _DRIVE.match(target):
            raise _refuse()
        base = posixpath.dirname(name) if member.issym() else ""
        if _escapes(posixpath.join(base, target)):
            raise _refuse()


def safe_extract(archive: Path, dest: Path) -> None:
    """Vet EVERY member before writing anything, then extract with the
    stdlib `data` filter as a second line of defence."""
    try:
        with tarfile.open(archive, mode="r:gz") as tar:
            members = tar.getmembers()
            if len(members) > MAX_MEMBERS:
                raise _refuse()
            if sum(m.size for m in members if m.isreg()) > MAX_EXTRACTED_BYTES:
                raise _refuse()
            for member in members:
                _vet(member)
            tar.extractall(dest, filter="data")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise _refuse() from exc


class ManagedInstaller:
    def __init__(
        self,
        *,
        python_root: Path,
        manifest: ManagedManifest,
        fetcher: Fetcher,
        policy: OwnerOnly,
        emit: Callable[[RuntimeLine], object],
        platform: str,
        asset_key: str | None,
    ) -> None:
        self._root = python_root
        self._manifest = manifest
        self._fetch = fetcher
        self._policy = policy
        self._emit = emit
        self._platform = platform
        self._key = asset_key

    def install(self) -> Path:
        asset = self._manifest.assets.get(self._key) if self._key else None  # type: ignore[call-overload]
        if asset is None:
            raise RuntimeSetupError("managed_download_failed", "No managed Python for this system.")
        if not self._manifest.verified or asset.sha256 == ZERO_HASH:
            raise RuntimeSetupError("managed_hash_mismatch")
        self._policy.ensure(self._root)
        work = Path(tempfile.mkdtemp(prefix=".managed-", dir=self._root))
        try:
            archive = work / "python.tar.gz"
            if self._download(asset, archive) != asset.sha256:
                raise RuntimeSetupError("managed_hash_mismatch")
            self._progress("verify")
            tree = work / "tree"
            tree.mkdir(mode=0o700)
            safe_extract(archive, tree)
            if not managed_interpreter(tree, self._platform).is_file():
                raise _refuse()
            self._progress("extract")
            return self._swap(tree)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _progress(self, step: str, done: int = 1, total: int | None = 1) -> None:
        self._emit(ProgressLine(fork=None, step=step, done=done, total=total))  # type: ignore[arg-type]

    def _download(self, asset: ManagedAsset, target: Path) -> str:
        try:
            stream, length = self._fetch(asset.url, DOWNLOAD_TIMEOUT_SECONDS)
        except OSError as exc:  # URLError/HTTPError are OSErrors
            logger.warning("managed Python download failed: %s", type(exc).__name__)
            raise RuntimeSetupError("managed_download_failed") from exc
        try:
            if length is not None and length > asset.max_bytes:
                raise RuntimeSetupError("managed_too_large")
            return self._stream_to(stream, target, asset.max_bytes, length)
        except OSError as exc:
            raise RuntimeSetupError("managed_download_failed") from exc
        finally:
            stream.close()

    def _stream_to(self, stream: Stream, target: Path, cap: int, length: int | None) -> str:
        digest = hashlib.sha256()
        received = 0
        self._progress("download", 0, length)
        with target.open("wb") as out:
            while chunk := stream.read(CHUNK_BYTES):
                received += len(chunk)
                if received > cap:
                    raise RuntimeSetupError("managed_too_large")
                digest.update(chunk)
                out.write(chunk)
        self._progress("download", received, length)
        return digest.hexdigest()

    def _swap(self, tree: Path) -> Path:
        dest = self._root / self._manifest.release
        old = self._root / f".{self._manifest.release}.old"
        if dest.exists() or dest.is_symlink():
            remove_path(old)
            dest.replace(old)
        tree.replace(dest)
        remove_path(old)
        return managed_interpreter(dest, self._platform)
