import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.assets import ModelStore, store_digest, verify_assets
from integrations.mcp.isaac.solus.runtime import child_environment, validate_frame


def test_assets_verify_complete_closure(tmp_path: Path) -> None:
    (tmp_path / "a.urdf").write_bytes(b"robot")
    manifest = {"a.urdf": hashlib.sha256(b"robot").hexdigest()}
    assert verify_assets(tmp_path, manifest)
    (tmp_path / "a.urdf").write_bytes(b"changed")
    with pytest.raises(ValueError):
        verify_assets(tmp_path, manifest)


@pytest.mark.parametrize(
    "name", ["../escape", "/etc/passwd", "https://evil.test/file", "a/../../b"]
)
def test_assets_refuse_escape(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        verify_assets(tmp_path, {name: "a" * 64})


def test_assets_refuse_symlink(tmp_path: Path) -> None:
    (tmp_path / "real").write_bytes(b"robot")
    (tmp_path / "a.urdf").symlink_to(tmp_path / "real")
    with pytest.raises(ValueError):
        verify_assets(tmp_path, {"a.urdf": hashlib.sha256(b"robot").hexdigest()})


def test_environment_is_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PYTHONEXE",
        "PYTHONPATH",
        "LD_PRELOAD",
        "AWS_SECRET_ACCESS_KEY",
        "HTTP_PROXY",
        "OMNI_KIT_ACCEPT_EULA",
    ):
        monkeypatch.setenv(name, "poison")
    env = child_environment(tmp_path)
    assert set(env) == {"HOME", "PATH", "LANG", "TMPDIR"}
    assert "poison" not in env.values()


@pytest.mark.parametrize(
    "data",
    [
        b"[]",
        b'{"operation":"exec","sequence":1}',
        b"x" * 131073,
        b'{"operation":"status","sequence":true}',
        b'{"operation":"status","sequence":1,"script":"evil"}',
    ],
)
def test_strict_frame(data: bytes) -> None:
    with pytest.raises(ValueError):
        validate_frame(data)


def test_valid_frame() -> None:
    assert (
        validate_frame(
            json.dumps(
                {"operation": "status", "sequence": 1, "generation": "abc", "arguments": {}}
            ).encode()
        )["operation"]
        == "status"
    )


def test_private_asset_copy_is_verified(tmp_path: Path) -> None:
    from integrations.mcp.isaac.solus.assets import copy_verified_assets

    source = tmp_path / "source"
    source.mkdir()
    (source / "a.urdf").write_bytes(b"robot")
    manifest = {"a.urdf": hashlib.sha256(b"robot").hexdigest()}
    destination = tmp_path / "private"
    copy_verified_assets(source, manifest, destination)
    assert (destination / "a.urdf").read_bytes() == b"robot"
    with pytest.raises(FileExistsError):
        copy_verified_assets(source, manifest, destination)


def test_asset_hash_stream_rejects_growth_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.urdf").write_bytes(b"x")
    calls: list[int] = []

    def growing_read(fd: int, count: int) -> bytes:
        calls.append(fd)
        return b"x" * 65536 if len(calls) < 400 else b""

    monkeypatch.setattr("integrations.mcp.isaac.solus.assets.os.read", growing_read)
    with pytest.raises(ValueError):
        verify_assets(tmp_path, {"a.urdf": hashlib.sha256(b"x").hexdigest()})
    assert len(calls) == 1


# --- SOLUSDEV-322 P4-T1: the chunked model store (gazebo's model_assets.py shape) -------------

URDF = b'<robot name="arm"><link name="base"/></robot>\n'
MESH = bytes(range(256)) * 300  # 76 800 bytes: spans two 64 KiB chunks


def _hashes(files: Mapping[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


def _chunks(files: Mapping[str, bytes], size: int = 64 * 1024) -> list[tuple[str, bytes]]:
    return [
        (name, data[offset : offset + size])
        for name, data in files.items()
        for offset in range(0, len(data), size)
    ]


def push_all(
    store: ModelStore, files: Mapping[str, bytes], *, upto: int | None = None
) -> list[dict[str, Any]]:
    import base64

    from integrations.mcp.isaac.solus.models import PutAsset

    manifest = _hashes(files)
    sha = store_digest(manifest)
    chunks = _chunks(files)
    return [
        store.put_chunk(
            PutAsset(
                sha256=sha,
                path=path,
                index=index,
                total=len(chunks),
                data_b64=base64.b64encode(data).decode(),
                manifest=manifest if index == 0 else None,
            )
        )
        for index, (path, data) in enumerate(chunks[:upto])
    ]


def test_put_asset_chunks_verify_and_promote_under_sim_models(tmp_path: Path) -> None:
    from integrations.mcp.isaac.solus.assets import MANIFEST_FILE

    store = ModelStore(tmp_path)
    files = {"arm.urdf": URDF, "meshes/link.stl": MESH}
    sha = store_digest(_hashes(files))
    results = push_all(store, files)
    assert [r["complete"] for r in results] == [False, False, True]
    assert all(r["ok"] for r in results) and results[-1]["promoted"] is True
    final = tmp_path / ".solus" / "sim" / "models" / sha
    assert final.is_dir() and not (final.parent / f"{sha}.partial").exists()
    assert (final / "arm.urdf").read_bytes() == URDF
    assert (final / "meshes" / "link.stl").read_bytes() == MESH
    assert json.loads((final / MANIFEST_FILE).read_text()) == _hashes(files)
    assert store.has(sha)
    with store.verified(sha) as model:
        assert model.manifest == _hashes(files) and model.model_file == "arm.urdf"
    again = push_all(store, files, upto=1)[0]
    assert again["ok"] and again["already"] is True and again["complete"] is True


def test_put_asset_bad_hash_discards_partial_and_out_of_order_restarts(tmp_path: Path) -> None:

    store = ModelStore(tmp_path)
    files = {"arm.urdf": URDF, "meshes/link.stl": MESH}
    manifest = _hashes(files)
    manifest["meshes/link.stl"] = "0" * 64
    sha = store_digest(manifest)
    results = []
    for index, (path, data) in enumerate(_chunks(files)):
        import base64

        from integrations.mcp.isaac.solus.models import PutAsset

        results.append(
            store.put_chunk(
                PutAsset(
                    sha256=sha,
                    path=path,
                    index=index,
                    total=3,
                    data_b64=base64.b64encode(data).decode(),
                    manifest=manifest if index == 0 else None,
                )
            )
        )
    assert results[-1] == {"ok": False, "code": "asset_mismatch", "reason": results[-1]["reason"]}
    models = tmp_path / ".solus" / "sim" / "models"
    assert not (models / sha).exists() and not (models / f"{sha}.partial").exists()
    assert not store.has(sha)
    # Interrupted: chunk 1 without chunk 0 is refused; index 0 starts over cleanly.
    good = _hashes(files)
    gsha = store_digest(good)
    import base64

    from integrations.mcp.isaac.solus.models import PutAsset

    stray = store.put_chunk(
        PutAsset(sha256=gsha, path="arm.urdf", index=1, total=3, data_b64="", manifest=None)
    )
    assert stray["code"] == "chunk_out_of_order"
    push_all(store, files, upto=2)
    assert (models / f"{gsha}.partial").is_dir() and not store.has(gsha)
    assert push_all(store, files)[-1]["promoted"] is True


@pytest.mark.parametrize(
    "manifest, code",
    [
        ({"arm.urdf": "a" * 64, "helper.py": "b" * 64}, "unsupported_file_type"),
        ({"arm.urdf": "a" * 64, "lib.so": "b" * 64}, "unsupported_file_type"),
        ({"meshes/link.stl": "a" * 64}, "model_file_ambiguous"),
        ({"arm.urdf": "a" * 64, "robot.usd": "b" * 64}, "model_file_ambiguous"),
        ({"arm.urdf": "a" * 64, "MANIFEST.solus.json": "b" * 64}, "path_reserved"),
    ],
)
def test_store_refuses_code_ambiguous_models_and_reserved_names(
    tmp_path: Path, manifest: dict[str, str], code: str
) -> None:
    import base64

    from integrations.mcp.isaac.solus.models import PutAsset

    first = next(iter(manifest))
    result = ModelStore(tmp_path).put_chunk(
        PutAsset(
            sha256=store_digest(manifest),
            path=first,
            index=0,
            total=1,
            data_b64=base64.b64encode(b"x").decode(),
            manifest=manifest,
        )
    )
    assert result["ok"] is False and result["code"] == code
    assert not (tmp_path / ".solus").exists() or not any(
        (tmp_path / ".solus" / "sim" / "models").iterdir()
    )


def test_usd_models_are_storable_and_the_model_file_is_found(tmp_path: Path) -> None:

    store = ModelStore(tmp_path)
    files = {"robot.usda": b"#usda 1.0\n", "textures/skin.png": b"\x89PNG"}
    assert push_all(store, files)[-1]["promoted"] is True
    with store.verified(store_digest(_hashes(files))) as model:
        assert model.model_file == "robot.usda"


def test_store_rejects_tampered_tree_and_symlinked_ancestor(tmp_path: Path) -> None:

    store = ModelStore(tmp_path)
    files = {"arm.urdf": URDF}
    sha = store_digest(_hashes(files))
    push_all(store, files)
    final = tmp_path / ".solus" / "sim" / "models" / sha
    (final / "extra.stl").write_bytes(b"x")
    assert not store.has(sha)
    (final / "extra.stl").unlink()
    assert store.has(sha)
    (final / "arm.urdf").write_bytes(b"changed")
    assert not store.has(sha)
    other = tmp_path / "other"
    other.mkdir()
    (other / ".solus").symlink_to(tmp_path / ".solus", target_is_directory=True)
    assert not ModelStore(other).has(sha)
    assert push_all(ModelStore(other), files)[-1]["code"] == "store_unsafe"


def test_model_asset_directory_reads_sim_models_first_then_isaac_models(tmp_path: Path) -> None:
    from integrations.mcp.isaac.solus.assets import model_asset_directory

    legacy = tmp_path / ".solus" / "isaac" / "models" / ("b" * 64)
    legacy.mkdir(parents=True)
    (legacy / "robot.urdf").write_bytes(URDF)
    with model_asset_directory(tmp_path, "b" * 64) as root:
        assert (root / "robot.urdf").read_bytes() == URDF
    files = {"arm.urdf": URDF}
    sha = store_digest(_hashes(files))
    push_all(ModelStore(tmp_path), files)
    with model_asset_directory(tmp_path, sha) as root:
        assert (root / "arm.urdf").read_bytes() == URDF
    with pytest.raises(ValueError, match="sim/models"):
        with model_asset_directory(tmp_path, "c" * 64):
            pytest.fail("missing model opened")
