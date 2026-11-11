"""The chunked store for Solus-generated models (SOLUSDEV-322 Q1).

`put_asset` chunks (≤ 72 KiB raw each) are appended in order under
``<workspace>/.solus/sim/models/<sha256>.partial/``; the last chunk triggers a verification of
every manifest file through fd-relative ``O_NOFOLLOW`` opens (:func:`worlds.confined_open`) and
ONE atomic rename promotes the directory to ``.solus/sim/models/<sha256>/``. That name therefore
exists only for a verified model; :meth:`ModelAssets.verified` re-verifies before every spawn
anyway (a verified tree may have been edited since). ``sha256`` is the digest of the canonical
manifest JSON, exactly as the API's ``Asset.sha256`` (isaac ``models.Asset``), so the directory
name binds the manifest and the manifest binds every file.

The workspace is the cloned (untrusted) repo, so it may ship ``.solus``, ``.solus/sim`` or
``.solus/sim/models`` as a symlink pointing anywhere. The store therefore never touches a path
string below the workspace: every ancestor is opened ``O_DIRECTORY | O_NOFOLLOW`` relative to its
parent (created with ``mkdir(dir_fd=…)`` when absent) and every mkdir, open, rename, unlink and
rmtree of ``<sha>`` / ``<sha>.partial`` is relative to that ``models`` descriptor.

A sequence interrupted by a companion disconnect leaves ``.partial/`` behind; it is never
promoted, out-of-order chunks are refused, and the next ``index 0`` discards it and starts over.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import shutil
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .tool_args import PutAssetArgs
from .worlds import confined_open, confined_write, model_dir, rel_parts

# Plain names (worlds.rel_parts refuses dotfiles); reserved, so a manifest may not use them.
MANIFEST_FILE: Final = "MANIFEST.solus.json"
STATE_FILE: Final = "CHUNKS.solus.json"
RESERVED_FILES: Final = frozenset({MANIFEST_FILE, STATE_FILE})
#: Top-level files `spawn` writes beside the model (wrapped SDF); tolerated by verification.
SPAWN_PREFIX: Final = "solus-spawn-"
#: The store's ancestors below the workspace, each opened one O_NOFOLLOW step at a time.
STORE_PARTS: Final = (".solus", "sim", "models")
MAX_CHUNK_BYTES: Final = 72 * 1024  # 96 KiB base64 decodes to at most 72 KiB
MAX_FILE_BYTES: Final = 20_000_000
MAX_TOTAL_BYTES: Final = 32_000_000
MODEL_SUFFIXES: Final = (".urdf", ".sdf")
#: Every manifest path must end in one of these (case-insensitive): model, mesh, texture or
#: model.config. Anything loadable as code (.so .py .sh ...) or extension-less is refused.
ALLOWED_SUFFIXES: Final = frozenset(
    {".urdf", ".sdf", ".xml", ".stl", ".dae", ".obj", ".mtl", ".png", ".jpg", ".jpeg", ".config"}
)
_DIR_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_NOT_VERIFIED: Final = "model is not verified: push it with put_asset first"


def manifest_digest(manifest: Mapping[str, str]) -> str:
    """sha256 of the canonical manifest JSON (the API's ``Asset.sha256``)."""
    return hashlib.sha256(
        json.dumps(dict(manifest), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def model_file_of(manifest: Mapping[str, str]) -> str:
    """The one top-level ``*.urdf`` / ``*.sdf`` entry a model manifest must carry."""
    candidates = [p for p in manifest if "/" not in p and p.endswith(MODEL_SUFFIXES)]
    if len(candidates) != 1:
        raise ValueError("manifest must carry exactly one top-level .urdf or .sdf model file")
    return candidates[0]


def unsupported_entry(manifest: Mapping[str, str]) -> str | None:
    """The first manifest path whose final suffix is outside ``ALLOWED_SUFFIXES``."""
    for path in manifest:
        if Path(path).suffix.lower() not in ALLOWED_SUFFIXES:
            return path
    return None


def asset_refusal(code: str, reason: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "reason": reason}


@dataclass(frozen=True)
class VerifiedModel:
    """A re-verified model, valid inside the ``with`` that produced it."""

    fd: int  # the model directory, reached O_NOFOLLOW step by step; reads/writes go through it
    path: Path  # <workspace>/.solus/sim/models/<sha256>: for the simulator's argv only
    manifest: dict[str, str]


class ModelAssets:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    # --- reads ---------------------------------------------------------------------------------

    def has(self, sha256: str) -> bool:
        try:
            self.verified_dir(sha256)
        except ValueError:
            return False
        return True

    def verified_dir(self, sha256: str) -> Path:
        with self.verified(sha256) as model:
            return model.path

    def manifest(self, sha256: str) -> dict[str, str]:
        with self.verified(sha256) as model:
            return model.manifest

    @contextlib.contextmanager
    def verified(self, sha256: str) -> Iterator[VerifiedModel]:
        """The promoted directory, re-verified now: manifest digest == name, every file's
        bytes match, no file outside the manifest, no symlink anywhere. ``ValueError`` else."""
        path = model_dir(self.workspace, sha256)
        try:
            with self._store(create=False) as store:
                fd = os.open(sha256, _DIR_FLAGS, dir_fd=store)
        except (OSError, ValueError) as error:
            raise ValueError(_NOT_VERIFIED) from error
        try:
            try:
                manifest = json.loads(confined_read_all(fd, MANIFEST_FILE))
            except ValueError as error:
                raise ValueError("model is not verified: manifest unreadable") from error
            if (
                not isinstance(manifest, dict)
                or manifest_digest(manifest) != sha256
                or not _tree_matches(fd, manifest)
            ):
                raise ValueError("model is not verified: contents differ from the manifest")
            yield VerifiedModel(fd, path, manifest)
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def _store(self, *, create: bool) -> Iterator[int]:
        """The ``models`` directory descriptor, every ancestor ``O_NOFOLLOW`` (a symlinked
        ancestor is ``ValueError``); ``create`` makes missing ancestors with ``mkdir(dir_fd)``."""
        try:
            fd = os.open(self.workspace, _DIR_FLAGS)
        except OSError as error:
            raise ValueError("workspace unavailable") from error
        try:
            for part in STORE_PARTS:
                nxt = _open_dir(part, fd, create=create)
                os.close(fd)
                fd = nxt
            yield fd
        finally:
            os.close(fd)

    # --- writes --------------------------------------------------------------------------------

    def put_chunk(self, args: PutAssetArgs) -> dict[str, Any]:
        if self.has(args.sha256):
            return self._ack(args, received=args.total, complete=True, already=True)
        try:
            with self._store(create=True) as store:
                if args.index == 0:
                    return self._start(args, store)
                return self._append(args, store)
        except ValueError as error:
            return asset_refusal("store_unsafe", str(error))

    def _start(self, args: PutAssetArgs, store: int) -> dict[str, Any]:
        if args.manifest is None:
            return asset_refusal("manifest_required", "chunk 0 must carry the model manifest")
        if manifest_digest(args.manifest) != args.sha256:
            return asset_refusal("manifest_digest_mismatch", "sha256 is not the manifest digest")
        try:
            model_file_of(args.manifest)
        except ValueError:
            return asset_refusal("model_file_ambiguous", "exactly one top-level .urdf or .sdf")
        if args.path not in args.manifest:
            return asset_refusal("path_not_in_manifest", "chunk path is not a manifest entry")
        if unsupported_entry(args.manifest) is not None:
            return asset_refusal(
                "unsupported_file_type", "manifest entries must be model, mesh or texture files"
            )
        if RESERVED_FILES & set(args.manifest) or any(
            p.startswith(SPAWN_PREFIX) for p in args.manifest
        ):
            return asset_refusal("path_reserved", "manifest uses a name the store reserves")
        partial = _partial_name(args.sha256)
        _discard(store, partial)
        _discard(
            store, args.sha256
        )  # an unverifiable leftover with the final name is never trusted
        os.mkdir(partial, 0o700, dir_fd=store)
        state = {"manifest": dict(args.manifest), "total": args.total, "next": 0, "bytes": 0}
        return self._write(args, store, state)

    def _append(self, args: PutAssetArgs, store: int) -> dict[str, Any]:
        if args.manifest is not None:
            return asset_refusal("manifest_unexpected", "only chunk 0 carries the manifest")
        state = _read_chunk_state(store, _partial_name(args.sha256))
        if state is None:
            return asset_refusal("chunk_out_of_order", "no transfer in progress; restart at 0")
        if state["total"] != args.total or state["next"] != args.index:
            return asset_refusal(
                "chunk_out_of_order",
                f"expected chunk {state['next']} of {state['total']}; restart at index 0",
            )
        if args.path not in state["manifest"]:
            _discard(store, _partial_name(args.sha256))
            return asset_refusal("path_not_in_manifest", "chunk path is not a manifest entry")
        return self._write(args, store, state)

    def _write(self, args: PutAssetArgs, store: int, state: dict[str, Any]) -> dict[str, Any]:
        partial = _partial_name(args.sha256)
        data = base64.b64decode(args.data_b64, validate=True)
        state["bytes"] += len(data)
        if len(data) > MAX_CHUNK_BYTES or state["bytes"] > MAX_TOTAL_BYTES:
            _discard(store, partial)
            return asset_refusal("asset_too_large", "model exceeds the store's size bound")
        fd = os.open(partial, _DIR_FLAGS, dir_fd=store)
        try:
            _append_chunk(fd, rel_parts(args.path), data)
            state["next"] = args.index + 1
            if state["next"] < state["total"]:
                confined_write(fd, STATE_FILE, json.dumps(state, separators=(",", ":")).encode())
                return self._ack(args, received=state["next"], complete=False)
            if args.index:  # a one-chunk model never wrote a state file
                os.unlink(STATE_FILE, dir_fd=fd)
            canonical = json.dumps(state["manifest"], sort_keys=True, separators=(",", ":"))
            confined_write(fd, MANIFEST_FILE, canonical.encode())
            verified = _tree_matches(fd, state["manifest"])
        finally:
            os.close(fd)
        if not verified:
            _discard(store, partial)
            return asset_refusal("asset_mismatch", "a file's bytes do not match the manifest")
        os.rename(partial, args.sha256, src_dir_fd=store, dst_dir_fd=store)
        return self._ack(args, received=args.total, complete=True, promoted=True)

    @staticmethod
    def _ack(
        args: PutAssetArgs,
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


# --- filesystem helpers (fd-relative, no symlink is ever followed) --------------------------


def _partial_name(sha256: str) -> str:
    return f"{sha256}.partial"


def _open_dir(name: str, dir_fd: int, *, create: bool) -> int:
    """``name`` under ``dir_fd`` as a directory descriptor, ``O_NOFOLLOW``: a symlink or a
    non-directory there is refused; ``create`` makes it when absent."""
    try:
        if create:
            with contextlib.suppress(FileExistsError):
                os.mkdir(name, 0o700, dir_fd=dir_fd)
        return os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
    except OSError as error:
        raise ValueError(f"model store: {name} is missing or not a plain directory") from error


def _discard(store: int, name: str) -> None:
    """Remove ``name`` under the store descriptor, whatever it is (tree, file or symlink)."""
    try:
        mode = os.lstat(name, dir_fd=store).st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode):
        shutil.rmtree(name, dir_fd=store)
    else:
        os.unlink(name, dir_fd=store)


def confined_read_all(root: Path | int, rel: str) -> bytes:
    """Whole-file read through :func:`worlds.confined_open`, bounded by ``MAX_FILE_BYTES``."""
    fd = confined_open(root, rel)
    try:
        if os.fstat(fd).st_size > MAX_FILE_BYTES:
            raise ValueError("file too large")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1 << 16):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _tree_matches(root: int, manifest: Mapping[str, str]) -> bool:
    """Every manifest file present with matching bytes, nothing else but the manifest file,
    and no symlink or special file anywhere under ``root``."""
    try:
        for rel, digest in manifest.items():
            if hashlib.sha256(confined_read_all(root, rel)).hexdigest() != digest:
                return False
    except ValueError:
        return False
    found = _tree_files(root)
    return found is not None and found == set(manifest) | {MANIFEST_FILE}


def _tree_files(root: int) -> set[str] | None:
    """Root-relative regular files under ``root``; ``None`` on any symlink or special entry."""
    found: set[str] = set()
    for dirpath, dirnames, filenames, dirfd in os.fwalk(".", dir_fd=root, follow_symlinks=False):
        rel_dir = Path(dirpath)
        if any(stat.S_ISLNK(os.lstat(name, dir_fd=dirfd).st_mode) for name in dirnames):
            return None
        for name in filenames:
            if not stat.S_ISREG(os.lstat(name, dir_fd=dirfd).st_mode):
                return None
            if not rel_dir.parts and name.startswith(SPAWN_PREFIX):
                continue
            found.add((rel_dir / name).as_posix() if rel_dir.parts else name)
    return found


def _append_chunk(partial: int, parts: tuple[str, ...], data: bytes) -> None:
    """Append to ``parts`` under the partial descriptor, creating intermediate directories
    ``O_NOFOLLOW`` step by step; the leaf must be (or become) a regular file."""
    parent = os.dup(partial)
    try:
        for part in parts[:-1]:
            nxt = _open_dir(part, parent, create=True)
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


def _read_chunk_state(store: int, partial: str) -> dict[str, Any] | None:
    try:
        fd = os.open(partial, _DIR_FLAGS, dir_fd=store)
    except OSError:
        return None
    try:
        state = json.loads(confined_read_all(fd, STATE_FILE))
    except ValueError:
        return None
    finally:
        os.close(fd)
    if not isinstance(state, dict) or not isinstance(state.get("manifest"), dict):
        return None
    return state
