"""The chunked model store: chunks land under `.solus/sim/models/<sha256>.partial/`, every
file is verified against the manifest, then ONE atomic rename promotes the directory to
`.solus/sim/models/<sha256>/`. Nothing unverified ever has that name."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from integrations.mcp.gazebo.solus.model_assets import (
    MANIFEST_FILE,
    SPAWN_PREFIX,
    STORE_PARTS,
    ModelAssets,
    manifest_digest,
    model_file_of,
)
from integrations.mcp.gazebo.solus.tool_args import PutAssetArgs

URDF = b'<robot name="arm"><link name="base"/></robot>\n'
MESH = bytes(range(256)) * 300  # 76 800 bytes: spans two 64 KiB chunks


def _hashes_of(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


def _chunk_plan(files: dict[str, bytes], size: int = 64 * 1024) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for name, data in files.items():
        for offset in range(0, len(data), size):
            out.append((name, data[offset : offset + size]))
    return out


def _push_all(
    store: ModelAssets, files: dict[str, bytes], *, upto: int | None = None
) -> list[dict[str, Any]]:
    manifest = _hashes_of(files)
    sha = manifest_digest(manifest)
    chunks = _chunk_plan(files)
    results = []
    for index, (path, data) in enumerate(chunks[:upto]):
        args = PutAssetArgs(
            sha256=sha,
            path=path,
            index=index,
            total=len(chunks),
            data_b64=base64.b64encode(data).decode(),
            manifest=manifest if index == 0 else None,
        )
        results.append(store.put_chunk(args))
    return results


def test_put_asset_chunks_verify_and_promote(tmp_path: Path) -> None:
    store = ModelAssets(tmp_path)
    files = {"arm.urdf": URDF, "meshes/link.stl": MESH}
    sha = manifest_digest(_hashes_of(files))
    results = _push_all(store, files)
    assert [r["complete"] for r in results] == [False, False, True]
    assert all(r["ok"] for r in results)
    assert results[-1]["promoted"] is True
    models = tmp_path / ".solus" / "sim" / "models"
    final = models / sha
    assert final.is_dir() and not (models / f"{sha}.partial").exists()
    assert (final / "arm.urdf").read_bytes() == URDF
    assert (final / "meshes" / "link.stl").read_bytes() == MESH
    assert store.has(sha)
    assert store.verified_dir(sha) == final
    assert model_file_of(json.loads((final / MANIFEST_FILE).read_text())) == "arm.urdf"
    # Idempotent: a second push of a verified model is acknowledged without writing.
    again = _push_all(store, files, upto=1)[0]
    assert again["ok"] and again["complete"] and again["promoted"] and again["already"]


def test_a_one_chunk_model_promotes(tmp_path: Path) -> None:
    """A URDF-only model is what the API wrapper pushes as `total=1`: one chunk must promote
    (no chunk-state file was ever written for it to remove)."""
    store = ModelAssets(tmp_path)
    files = {"arm.urdf": URDF}
    [result] = _push_all(store, files)
    assert result["ok"] is True and result["promoted"] is True, result
    sha = manifest_digest(_hashes_of(files))
    assert store.has(sha) and store.verified_dir(sha).is_dir()
    assert (store.verified_dir(sha) / "arm.urdf").read_bytes() == URDF


def test_put_asset_bad_hash_discards_partial(tmp_path: Path) -> None:
    store = ModelAssets(tmp_path)
    files = {"arm.urdf": URDF, "meshes/link.stl": MESH}
    manifest = _hashes_of(files)
    manifest["meshes/link.stl"] = "0" * 64  # the bytes will not match
    sha = manifest_digest(manifest)
    chunks = _chunk_plan(files)
    last: dict[str, Any] = {}
    for index, (path, data) in enumerate(chunks):
        last = store.put_chunk(
            PutAssetArgs(
                sha256=sha,
                path=path,
                index=index,
                total=len(chunks),
                data_b64=base64.b64encode(data).decode(),
                manifest=manifest if index == 0 else None,
            )
        )
    assert last["ok"] is False and last["code"] == "asset_mismatch"
    models = tmp_path / ".solus" / "sim" / "models"
    assert not (models / sha).exists() and not (models / f"{sha}.partial").exists()
    assert not store.has(sha)
    with pytest.raises(ValueError):
        store.verified_dir(sha)


def test_interrupted_put_asset_never_promotes_and_restarts_cleanly(tmp_path: Path) -> None:
    store = ModelAssets(tmp_path)
    files = {"arm.urdf": URDF, "meshes/link.stl": MESH}
    sha = manifest_digest(_hashes_of(files))
    partial = tmp_path / ".solus" / "sim" / "models" / f"{sha}.partial"
    first = _push_all(store, files, upto=2)  # the companion disconnects after chunk 1
    assert [r["complete"] for r in first] == [False, False]
    assert partial.is_dir() and not store.has(sha)
    with pytest.raises(ValueError, match="not verified"):
        store.verified_dir(sha)  # spawn refuses meanwhile
    # A replayed or out-of-order chunk is refused and leaves the partial alone.
    stale = store.put_chunk(
        PutAssetArgs(sha256=sha, path="meshes/link.stl", index=1, total=3, data_b64="AA==")
    )
    assert stale["ok"] is False and stale["code"] == "chunk_out_of_order"
    assert partial.is_dir()
    # Index 0 restarts: the old partial is discarded and the full sequence promotes.
    results = _push_all(store, files)
    assert results[-1]["promoted"] is True
    assert store.verified_dir(sha).is_dir() and not partial.exists()
    assert (store.verified_dir(sha) / "meshes" / "link.stl").read_bytes() == MESH


def test_index_zero_needs_a_manifest_matching_the_digest_and_one_model_file(
    tmp_path: Path,
) -> None:
    store = ModelAssets(tmp_path)
    manifest = _hashes_of({"arm.urdf": URDF})
    sha = manifest_digest(manifest)
    data = base64.b64encode(URDF).decode()
    no_manifest = store.put_chunk(
        PutAssetArgs(sha256=sha, path="arm.urdf", index=0, total=1, data_b64=data)
    )
    assert no_manifest["ok"] is False and no_manifest["code"] == "manifest_required"
    wrong_digest = store.put_chunk(
        PutAssetArgs(
            sha256="f" * 64, path="arm.urdf", index=0, total=1, data_b64=data, manifest=manifest
        )
    )
    assert wrong_digest["ok"] is False and wrong_digest["code"] == "manifest_digest_mismatch"
    two_models = {"a.urdf": "0" * 64, "b.sdf": "1" * 64}
    result = store.put_chunk(
        PutAssetArgs(
            sha256=manifest_digest(two_models),
            path="a.urdf",
            index=0,
            total=1,
            data_b64=data,
            manifest=two_models,
        )
    )
    assert result["ok"] is False and result["code"] == "model_file_ambiguous"
    foreign_path = store.put_chunk(
        PutAssetArgs(
            sha256=sha, path="other.bin", index=0, total=1, data_b64=data, manifest=manifest
        )
    )
    assert foreign_path["ok"] is False and foreign_path["code"] == "path_not_in_manifest"
    models = tmp_path / ".solus" / "sim" / "models"
    assert not models.exists() or not any(models.iterdir())


def test_verified_dir_rechecks_bytes_and_refuses_tampering_symlinks_and_extras(
    tmp_path: Path,
) -> None:
    store = ModelAssets(tmp_path)
    files = {"arm.urdf": URDF, "meshes/link.stl": MESH}
    sha = manifest_digest(_hashes_of(files))
    _push_all(store, files)
    final = store.verified_dir(sha)
    (final / "meshes" / "link.stl").write_bytes(MESH + b"x")
    with pytest.raises(ValueError, match="not verified"):
        store.verified_dir(sha)
    (final / "meshes" / "link.stl").write_bytes(MESH)
    assert store.verified_dir(sha) == final
    (final / "extra.so").write_bytes(b"\x7fELF")
    with pytest.raises(ValueError):
        store.verified_dir(sha)
    (final / "extra.so").unlink()
    os.symlink("/etc/passwd", final / "meshes" / "evil")
    with pytest.raises(ValueError):
        store.verified_dir(sha)


def test_model_file_of_accepts_exactly_one_top_level_urdf_or_sdf() -> None:
    assert model_file_of({"arm.urdf": "0" * 64, "meshes/a.stl": "1" * 64}) == "arm.urdf"
    assert model_file_of({"model.sdf": "0" * 64}) == "model.sdf"
    for bad in (
        {"meshes/a.stl": "0" * 64},
        {"sub/arm.urdf": "0" * 64},
        {"a.urdf": "0" * 64, "b.urdf": "1" * 64},
    ):
        with pytest.raises(ValueError):
            model_file_of(bad)


def test_spawn_files_beside_the_model_are_tolerated_and_reserved(tmp_path: Path) -> None:
    """`spawn` writes the wrapped SDF next to the meshes (relative <uri>s resolve against the
    model file's directory); only names under SPAWN_PREFIX are tolerated, and a manifest may
    not claim such a name."""
    store = ModelAssets(tmp_path)
    files = {"arm.urdf": URDF, "meshes/link.stl": MESH}
    sha = manifest_digest(_hashes_of(files))
    _push_all(store, files)
    final = store.verified_dir(sha)
    (final / f"{SPAWN_PREFIX}arm1.sdf").write_bytes(b"<sdf/>")
    assert store.verified_dir(sha) == final
    (final / "meshes" / f"{SPAWN_PREFIX}deep.sdf").write_bytes(b"<sdf/>")
    with pytest.raises(ValueError):
        store.verified_dir(sha)  # only top-level spawn files are Solus's
    (final / "meshes" / f"{SPAWN_PREFIX}deep.sdf").unlink()
    claimed = {f"{SPAWN_PREFIX}x.stl": "0" * 64, "arm.urdf": "1" * 64}
    result = store.put_chunk(
        PutAssetArgs(
            sha256=manifest_digest(claimed),
            path="arm.urdf",
            index=0,
            total=1,
            data_b64=base64.b64encode(URDF).decode(),
            manifest=claimed,
        )
    )
    assert result["ok"] is False and result["code"] == "path_reserved"


@pytest.mark.parametrize("depth", [1, 2, 3])
def test_store_refuses_symlinked_ancestors_and_writes_nothing_outside(
    tmp_path: Path, depth: int
) -> None:
    """The workspace is a cloned (untrusted) repo: it may ship `.solus`, `.solus/sim` or
    `.solus/sim/models` as a symlink pointing anywhere. Every ancestor is opened O_NOFOLLOW, so
    the store refuses, writes nothing at the link's target and never believes a verified tree
    planted there."""
    files = {"arm.urdf": URDF, "meshes/link.stl": MESH}
    sha = manifest_digest(_hashes_of(files))
    (tmp_path / "legit").mkdir()
    legit = ModelAssets(tmp_path / "legit")
    _push_all(legit, files)
    outside = tmp_path / "outside"
    plant = outside.joinpath(*STORE_PARTS[depth:])
    plant.mkdir(parents=True)
    shutil.copytree(legit.verified_dir(sha), plant / sha)
    before = sorted(outside.rglob("*"))
    workspace = tmp_path / "ws"
    link = workspace.joinpath(*STORE_PARTS[:depth])
    link.parent.mkdir(parents=True)
    os.symlink(outside, link)
    store = ModelAssets(workspace)
    assert not store.has(sha)
    with pytest.raises(ValueError, match="not verified"):
        store.verified_dir(sha)
    results = _push_all(store, files)
    assert all(r["ok"] is False and r["code"] == "store_unsafe" for r in results), results
    assert sorted(outside.rglob("*")) == before, "something was written through the symlink"
    assert link.is_symlink() and not any(
        p.exists() for p in [workspace / ".solus" / "sim" / "models" / f"{sha}.partial"]
    )


@pytest.mark.parametrize(
    "bad_entry", ["hook.so", "post.py", "README", "model.sdf.so", "lib.DYLIB", "run.sh"]
)
def test_put_asset_refuses_manifest_entries_outside_the_file_type_allowlist(
    tmp_path: Path, bad_entry: str
) -> None:
    """Every manifest path, not only the model file, must be a model/mesh/texture type."""
    store = ModelAssets(tmp_path)
    manifest = _hashes_of({"arm.urdf": URDF, f"meshes/{bad_entry}": MESH})
    result = store.put_chunk(
        PutAssetArgs(
            sha256=manifest_digest(manifest),
            path="arm.urdf",
            index=0,
            total=1,
            data_b64=base64.b64encode(URDF).decode(),
            manifest=manifest,
        )
    )
    assert result["ok"] is False and result["code"] == "unsupported_file_type"
    models = tmp_path / ".solus" / "sim" / "models"
    assert not models.exists() or not any(models.iterdir()), "a partial was created"


def test_put_asset_accepts_every_allowlisted_type_case_insensitively(tmp_path: Path) -> None:
    files = {
        "arm.urdf": URDF,
        "model.config": b"<model/>",
        "meshes/base.STL": MESH,
        "meshes/arm.dae": MESH,
        "meshes/hand.obj": MESH,
        "meshes/hand.mtl": b"newmtl x\n",
        "textures/skin.PNG": MESH,
        "textures/a.jpg": MESH,
        "textures/b.JPEG": MESH,
        "extra.xml": b"<x/>",
    }
    results = _push_all(ModelAssets(tmp_path), files)
    assert all(r["ok"] for r in results), results
    assert results[-1]["complete"] is True
