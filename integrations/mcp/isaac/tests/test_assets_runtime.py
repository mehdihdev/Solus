import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.assets import verify_assets
from integrations.mcp.isaac.solus.runtime import child_environment, validate_frame


def test_assets_verify_complete_closure(tmp_path):
    (tmp_path / "a.urdf").write_bytes(b"robot")
    manifest = {"a.urdf": hashlib.sha256(b"robot").hexdigest()}
    assert verify_assets(tmp_path, manifest)
    (tmp_path / "a.urdf").write_bytes(b"changed")
    with pytest.raises(ValueError):
        verify_assets(tmp_path, manifest)


@pytest.mark.parametrize(
    "name", ["../escape", "/etc/passwd", "https://evil.test/file", "a/../../b"]
)
def test_assets_refuse_escape(tmp_path, name):
    with pytest.raises(ValueError):
        verify_assets(tmp_path, {name: "a" * 64})


def test_assets_refuse_symlink(tmp_path):
    (tmp_path / "real").write_bytes(b"robot")
    (tmp_path / "a.urdf").symlink_to(tmp_path / "real")
    with pytest.raises(ValueError):
        verify_assets(tmp_path, {"a.urdf": hashlib.sha256(b"robot").hexdigest()})


def test_environment_is_closed(tmp_path, monkeypatch):
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
def test_strict_frame(data):
    with pytest.raises(ValueError):
        validate_frame(data)


def test_valid_frame():
    assert (
        validate_frame(
            json.dumps(
                {"operation": "status", "sequence": 1, "generation": "abc", "arguments": {}}
            ).encode()
        )["operation"]
        == "status"
    )


def test_private_asset_copy_is_verified(tmp_path):
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


def test_asset_hash_stream_rejects_growth_immediately(tmp_path, monkeypatch):
    (tmp_path / "a.urdf").write_bytes(b"x")
    calls = []

    def growing_read(fd, count):
        calls.append(fd)
        return b"x" * 65536 if len(calls) < 400 else b""

    monkeypatch.setattr("integrations.mcp.isaac.solus.assets.os.read", growing_read)
    with pytest.raises(ValueError):
        verify_assets(tmp_path, {"a.urdf": hashlib.sha256(b"x").hexdigest()})
    assert len(calls) == 1
