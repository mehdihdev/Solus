"""Verify an explicitly pinned regular-file asset closure without path escape.

SOLUSDEV-322 P4-T1 adds :class:`ModelStore`, the chunked store Solus-generated models arrive
through (`put_asset`): the gazebo fork's ``model_assets.py`` shape, named apart because each
fork ships on its own. Chunks land under ``<workspace>/.solus/sim/models/<sha256>.partial/``,
the last chunk verifies every manifest file through fd-relative ``O_NOFOLLOW`` opens and ONE
atomic rename promotes the directory to ``.solus/sim/models/<sha256>/``; ``sha256`` is the
digest of the canonical manifest JSON (the API's ``Asset.sha256``). The legacy
``.solus/isaac/models/<sha256>/`` (files humans copied by hand) stays readable for `load_model`.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from .models import PutAsset

MANIFEST_FILE: Final = "MANIFEST.solus.json"
STATE_FILE: Final = "CHUNKS.solus.json"
RESERVED_FILES: Final = frozenset({MANIFEST_FILE, STATE_FILE})
#: The store's ancestors below the workspace, each opened one O_NOFOLLOW step at a time.
STORE_PARTS: Final = (".solus", "sim", "models")
LEGACY_PARTS: Final = (".solus", "isaac", "models")
MAX_CHUNK_BYTES: Final = 72 * 1024  # 96 KiB base64 decodes to at most 72 KiB
MAX_FILE_BYTES: Final = 20_000_000
MAX_TOTAL_BYTES: Final = 32_000_000
MODEL_SUFFIXES: Final = (".urdf", ".usd", ".usda", ".usdc", ".usdz")
#: Every manifest path ends in one of these: model, mesh, texture or model.config. Anything
#: loadable as code (.so .py .sh …) or extension-less is refused. Isaac adds the USD family.
ALLOWED_SUFFIXES: Final = frozenset(
    {
        ".urdf",
        ".sdf",
        ".xml",
        ".stl",
        ".dae",
        ".obj",
        ".mtl",
        ".png",
        ".jpg",
        ".jpeg",
        ".config",
        ".usd",
        ".usda",
        ".usdc",
        ".usdz",
    }
)
_DIR_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_SAFE_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


def verify_assets(root: Path, manifest: dict[str, str]) -> str:
    if not 1 <= len(manifest) <= 32:
        raise ValueError("asset count")
    root_fd = _open_root(root)
    total = 0
    try:
        for name, digest in sorted(manifest.items()):
            parts = PurePosixPath(name).parts
            if (
                not parts
                or name.startswith("/")
                or any(p in (".", "..") or not re.fullmatch("[A-Za-z0-9_.-]+", p) for p in parts)
                or not re.fullmatch("[0-9a-f]{64}", digest)
            ):
                raise ValueError("invalid asset path or digest")
            parent = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    os.close(parent)
                    parent = nxt
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    if not stat.S_ISREG(before.st_mode) or before.st_size > 20_000_000:
                        raise ValueError("invalid asset file")
                    total += before.st_size
                    if total > 32_000_000:
                        raise ValueError("asset closure too large")
                    calculated = _hash_fd(fd, before.st_size)
                    after = os.fstat(fd)
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    ) or calculated != digest:
                        raise ValueError("asset integrity mismatch")
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
    except OSError as error:
        raise ValueError("asset unavailable or unsafe") from error
    finally:
        os.close(root_fd)
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def copy_verified_assets(root: Path, manifest: dict[str, str], destination: Path) -> str:
    """Copy through no-follow descriptors, then verify the private immutable input."""
    expected = verify_assets(root, manifest)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    root_fd = _open_root(root)
    try:
        for name, digest in manifest.items():
            parts = PurePosixPath(name).parts
            parent = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    next_fd = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                    )
                    os.close(parent)
                    parent = next_fd
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 20_000_000:
                        raise ValueError("invalid asset")
                    chunks = []
                    size = 0
                    while chunk := os.read(fd, 65536):
                        size += len(chunk)
                        if size > 20_000_000:
                            raise ValueError("asset changed size")
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError("asset changed")
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
            target = destination / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(data)
            target.chmod(0o400)
    finally:
        os.close(root_fd)
    if verify_assets(destination, manifest) != expected:
        raise ValueError("copied asset mismatch")
    return expected


def _hash_fd(fd: int, maximum_size: int) -> str:
    calculated = hashlib.sha256()
    bytes_read = 0
    while chunk := os.read(fd, 65536):
        bytes_read += len(chunk)
        if bytes_read > maximum_size or bytes_read > 20_000_000:
            raise ValueError("asset grew during verification")
        calculated.update(chunk)
    return calculated.hexdigest()


@contextmanager
def model_asset_directory(workspace: Path, digest: str) -> Iterator[Path]:
    """Resolve every workspace-relative ancestor without following user symlinks."""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid model digest")
    for parts in (STORE_PARTS, LEGACY_PARTS):
        try:
            fd = _walk_dirs(workspace, (*parts, digest))
        except OSError:
            continue
        try:
            yield Path(f"/proc/self/fd/{fd}/.")
        finally:
            os.close(fd)
        return
    raise ValueError("model assets missing: push them with put_asset (.solus/sim/models/<sha256>)")


def _walk_dirs(root: Path, parts: tuple[str, ...]) -> int:
    """``root/parts…`` as a directory descriptor, every step ``O_NOFOLLOW``; ``OSError`` else."""
    fd = _open_root(root)
    try:
        for component in parts:
            next_fd = os.open(component, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    except OSError:
        os.close(fd)
        raise
    return fd


def _open_root(root: Path) -> int:
    # Only internal worker/controller descriptors use this form; no public path input exists.
    match = re.fullmatch(r"/proc/self/fd/([0-9]+)", str(root))
    if match:
        return os.dup(int(match[1]))
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


# --- the chunked model store (SOLUSDEV-322) --------------------------------------------------


def store_digest(manifest: Mapping[str, str]) -> str:
    """sha256 of the canonical manifest JSON (the API's ``Asset.sha256``)."""
    return hashlib.sha256(
        json.dumps(dict(manifest), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def store_model_file(manifest: Mapping[str, str]) -> str:
    """The one top-level URDF or USD entry a model manifest must carry."""
    candidates = [p for p in manifest if "/" not in p and p.lower().endswith(MODEL_SUFFIXES)]
    if len(candidates) != 1:
        raise ValueError("manifest must carry exactly one top-level .urdf or .usd* model file")
    return candidates[0]


def store_refusal(code: str, reason: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "reason": reason}


@dataclass(frozen=True)
class StoredModel:
    """A re-verified model, valid inside the ``with`` that produced it."""

    fd: int  # the model directory, reached O_NOFOLLOW step by step
    manifest: dict[str, str]
    model_file: str


class ModelStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def has(self, sha256: str) -> bool:
        try:
            with self.verified(sha256):
                return True
        except ValueError:
            return False

    @contextmanager
    def verified(self, sha256: str) -> Iterator[StoredModel]:
        """The promoted directory, re-verified now: manifest digest == name, every file's bytes
        match, nothing outside the manifest, no symlink anywhere. ``ValueError`` else."""
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("invalid model digest")
        try:
            fd = _walk_dirs(self.workspace, (*STORE_PARTS, sha256))
        except OSError as error:
            raise ValueError("model is not verified: push it with put_asset first") from error
        try:
            try:
                manifest = json.loads(read_under_fd(fd, MANIFEST_FILE))
            except ValueError as error:
                raise ValueError("model is not verified: manifest unreadable") from error
            if (
                not isinstance(manifest, dict)
                or store_digest(manifest) != sha256
                or not _store_matches(fd, manifest)
            ):
                raise ValueError("model is not verified: contents differ from the manifest")
            yield StoredModel(fd, manifest, store_model_file(manifest))
        finally:
            os.close(fd)

    @contextmanager
    def _store(self) -> Iterator[int]:
        """The ``models`` directory descriptor, every ancestor ``O_NOFOLLOW`` (a symlinked
        ancestor is ``ValueError``), missing ancestors made with ``mkdir(dir_fd)``."""
        try:
            fd = os.open(self.workspace, _DIR_FLAGS)
        except OSError as error:
            raise ValueError("workspace unavailable") from error
        try:
            for part in STORE_PARTS:
                nxt = _store_open_dir(part, fd)
                os.close(fd)
                fd = nxt
            yield fd
        finally:
            os.close(fd)

    def put_chunk(self, args: PutAsset) -> dict[str, Any]:
        if self.has(args.sha256):
            return self._ack(args, received=args.total, complete=True, already=True)
        try:
            with self._store() as store:
                return self._start(args, store) if args.index == 0 else self._append(args, store)
        except ValueError as error:
            return store_refusal("store_unsafe", str(error))

    def _start(self, args: PutAsset, store: int) -> dict[str, Any]:
        manifest = args.manifest
        if manifest is None:
            return store_refusal("manifest_required", "chunk 0 must carry the model manifest")
        if store_digest(manifest) != args.sha256:
            return store_refusal("manifest_digest_mismatch", "sha256 is not the manifest digest")
        try:
            store_model_file(manifest)
        except ValueError:
            return store_refusal("model_file_ambiguous", "exactly one top-level .urdf or .usd*")
        if args.path not in manifest:
            return store_refusal("path_not_in_manifest", "chunk path is not a manifest entry")
        if RESERVED_FILES & set(manifest):
            return store_refusal("path_reserved", "manifest uses a name the store reserves")
        if any(PurePosixPath(p).suffix.lower() not in ALLOWED_SUFFIXES for p in manifest):
            return store_refusal(
                "unsupported_file_type", "manifest entries must be model, mesh or texture files"
            )
        partial = f"{args.sha256}.partial"
        _store_discard(store, partial)
        _store_discard(store, args.sha256)  # an unverifiable leftover is never trusted
        os.mkdir(partial, 0o700, dir_fd=store)
        state = {"manifest": dict(manifest), "total": args.total, "next": 0, "bytes": 0}
        return self._write(args, store, state)

    def _append(self, args: PutAsset, store: int) -> dict[str, Any]:
        if args.manifest is not None:
            return store_refusal("manifest_unexpected", "only chunk 0 carries the manifest")
        state = _store_state(store, f"{args.sha256}.partial")
        if state is None or state["total"] != args.total or state["next"] != args.index:
            return store_refusal("chunk_out_of_order", "chunk sequence broken; restart at index 0")
        if args.path not in state["manifest"]:
            _store_discard(store, f"{args.sha256}.partial")
            return store_refusal("path_not_in_manifest", "chunk path is not a manifest entry")
        return self._write(args, store, state)

    def _write(self, args: PutAsset, store: int, state: dict[str, Any]) -> dict[str, Any]:
        partial = f"{args.sha256}.partial"
        data = base64.b64decode(args.data_b64, validate=True)
        state["bytes"] += len(data)
        if len(data) > MAX_CHUNK_BYTES or state["bytes"] > MAX_TOTAL_BYTES:
            _store_discard(store, partial)
            return store_refusal("asset_too_large", "model exceeds the store's size bound")
        fd = os.open(partial, _DIR_FLAGS, dir_fd=store)
        try:
            _store_append(fd, _parts(args.path), data)
            state["next"] = args.index + 1
            if state["next"] < state["total"]:
                _write_under_fd(fd, STATE_FILE, json.dumps(state, separators=(",", ":")).encode())
                return self._ack(args, received=state["next"], complete=False)
            if args.index:  # a one-chunk model never wrote a state file
                os.unlink(STATE_FILE, dir_fd=fd)
            canonical = json.dumps(state["manifest"], sort_keys=True, separators=(",", ":"))
            _write_under_fd(fd, MANIFEST_FILE, canonical.encode())
            verified = _store_matches(fd, state["manifest"])
        finally:
            os.close(fd)
        if not verified:
            _store_discard(store, partial)
            return store_refusal("asset_mismatch", "a file's bytes do not match the manifest")
        os.rename(partial, args.sha256, src_dir_fd=store, dst_dir_fd=store)
        return self._ack(args, received=args.total, complete=True, promoted=True)

    @staticmethod
    def _ack(
        args: PutAsset,
        *,
        received: int,
        complete: bool,
        promoted: bool = False,
        already: bool = False,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "sha256": args.sha256,
            "path": args.path,
            "index": args.index,
            "total": args.total,
            "received": received,
            "complete": complete,
            "promoted": promoted or already,
            "already": already,
        }


def _parts(rel: str) -> tuple[str, ...]:
    parts = tuple(rel.split("/"))
    if any(_SAFE_PART.fullmatch(p) is None or p in (".", "..") for p in parts):
        raise ValueError("path must be root-relative with plain name components")
    return parts


def _store_open_dir(name: str, dir_fd: int) -> int:
    """``name`` under ``dir_fd`` as a directory descriptor, ``O_NOFOLLOW``, made when absent."""
    try:
        with contextlib.suppress(FileExistsError):
            os.mkdir(name, 0o700, dir_fd=dir_fd)
        return os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
    except OSError as error:
        raise ValueError(f"model store: {name} is missing or not a plain directory") from error


def _store_discard(store: int, name: str) -> None:
    """Remove ``name`` under the store descriptor, whatever it is (tree, file or symlink)."""
    try:
        mode = os.lstat(name, dir_fd=store).st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode):
        shutil.rmtree(name, dir_fd=store)
    else:
        os.unlink(name, dir_fd=store)


def read_under_fd(root: int, rel: str) -> bytes:
    """Whole-file read of a regular file under ``root``, every step ``O_NOFOLLOW``, bounded."""
    parts = _parts(rel)
    parent = os.dup(root)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, _DIR_FLAGS, dir_fd=parent)
            os.close(parent)
            parent = nxt
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except OSError as error:
        raise ValueError("path unavailable or unsafe") from error
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            raise ValueError("not a bounded regular file")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1 << 16):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_under_fd(root: int, name: str, data: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600, dir_fd=root)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
    finally:
        os.close(fd)


def _store_matches(root: int, manifest: Mapping[str, str]) -> bool:
    """Every manifest file present with matching bytes, nothing else but the manifest file,
    and no symlink or special file anywhere under ``root``."""
    try:
        for rel, digest in manifest.items():
            if hashlib.sha256(read_under_fd(root, rel)).hexdigest() != digest:
                return False
    except ValueError:
        return False
    found = _store_files(root)
    return found is not None and found == set(manifest) | {MANIFEST_FILE}


def _store_files(root: int) -> set[str] | None:
    """Root-relative regular files under ``root``; ``None`` on any symlink or special entry."""
    found: set[str] = set()
    for dirpath, dirnames, filenames, dirfd in os.fwalk(".", dir_fd=root, follow_symlinks=False):
        rel_dir = Path(dirpath)
        if any(stat.S_ISLNK(os.lstat(name, dir_fd=dirfd).st_mode) for name in dirnames):
            return None
        for name in filenames:
            if not stat.S_ISREG(os.lstat(name, dir_fd=dirfd).st_mode):
                return None
            found.add((rel_dir / name).as_posix() if rel_dir.parts else name)
    return found


def _store_append(partial: int, parts: tuple[str, ...], data: bytes) -> None:
    """Append to ``parts`` under the partial descriptor, creating intermediate directories
    ``O_NOFOLLOW`` step by step; the leaf must be (or become) a regular file."""
    parent = os.dup(partial)
    try:
        for part in parts[:-1]:
            nxt = _store_open_dir(part, parent)
            os.close(parent)
            parent = nxt
        fd = os.open(
            parts[-1], os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
    finally:
        os.close(parent)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("partial entry is not a regular file")
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
    finally:
        os.close(fd)


def _store_state(store: int, partial: str) -> dict[str, Any] | None:
    try:
        fd = os.open(partial, _DIR_FLAGS, dir_fd=store)
    except OSError:
        return None
    try:
        state = json.loads(read_under_fd(fd, STATE_FILE))
    except ValueError:
        return None
    finally:
        os.close(fd)
    if not isinstance(state, dict) or not isinstance(state.get("manifest"), dict):
        return None
    return state
