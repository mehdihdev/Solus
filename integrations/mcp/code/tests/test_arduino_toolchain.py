"""Filesystem-only Arduino foundation: no installation or device side effects."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from code_paths import overlay_module  # isort: skip

manifest = overlay_module("arduino_manifest")
toolchain = overlay_module("arduino_toolchain")


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(toolchain, "_application_root", lambda: tmp_path)
    monkeypatch.setattr(toolchain.platform, "system", lambda: "Linux")
    monkeypatch.setattr(toolchain.platform, "machine", lambda: "aarch64")
    binary = tmp_path / ".venv/bin/arduino-cli"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"reviewed fixture executable")
    binary.chmod(0o755)
    monkeypatch.setattr(toolchain, "CLI_SHA256", hashlib.sha256(binary.read_bytes()).hexdigest())

    def refuse_install(*args, **kwargs):
        raise toolchain.ArduinoError("toolchain_unavailable")

    monkeypatch.setattr(overlay_module("arduino_install"), "install_runtime", refuse_install)
    return toolchain.ArduinoRuntime(), binary


def test_exact_archive_closure_and_frozen_index():
    records = manifest.ARCHIVES
    assert len(records) == 9
    assert sum(item.size_bytes for item in records) == 58_254_542
    assert len({item.id for item in records}) == 9
    index = json.loads(manifest.frozen_package_index())
    assert [p["name"] for p in index["packages"]] == ["arduino", "builtin"]
    assert sum(len(p["tools"]) for p in index["packages"]) == 8
    assert index["packages"][0]["platforms"][0]["version"] == "1.8.8"
    assert all(len(t["systems"]) == 1 for p in index["packages"] for t in p["tools"])
    assert json.loads(manifest.empty_library_index()) == {"libraries": []}
    assert manifest.frozen_package_index() == manifest.frozen_package_index()
    with pytest.raises(ValueError, match="integrity_mismatch"):
        manifest.validate_archive_closure(records + (records[0],))
    with pytest.raises(ValueError, match="integrity_mismatch"):
        manifest.validate_archive_closure(records[:-1])


def test_probe_and_preview_are_read_only_and_complete(runtime):
    instance, binary = runtime
    before = sorted(str(p) for p in binary.parents[2].rglob("*"))
    probe = instance.probe()
    assert probe["cli"]["available"]
    assert not probe["toolchain"]["ready"]
    assert probe["toolchain"]["manifest_sha256"] is None
    plan = instance.prepare(dry_run=True)
    assert plan["ok"] and plan["dry_run"]
    assert len(plan["fingerprint"].split(":")) == 4
    assert len(plan["preview"]) <= 40
    for row in plan["preview"]:
        assert set(row) == {"label", "before", "after"}
        assert all(value is None or len(value) <= 400 for value in row.values())
    displayed = json.dumps(plan["preview"])
    for archive in manifest.ARCHIVES:
        assert ":".join(archive.sha256[i : i + 16] for i in range(0, 64, 16)) in displayed
        assert str(archive.size_bytes) in displayed
        assert archive.url in displayed and archive.version in displayed
    assert "--skip-post-install" in displayed and "--skip-pre-uninstall" in displayed
    assert "--no-overwrite" in displayed
    assert "unsigned curated derivative" in displayed
    assert before == sorted(str(p) for p in binary.parents[2].rglob("*"))
    with pytest.raises(toolchain.ArduinoError, match="toolchain_unavailable"):
        instance.prepare()


@pytest.mark.parametrize("kind", ["missing", "changed", "symlink", "directory", "oversized"])
def test_untrusted_cli_never_available(runtime, kind):
    instance, binary = runtime
    binary.unlink()
    if kind == "changed":
        binary.write_bytes(b"different")
    elif kind == "symlink":
        binary.symlink_to("/bin/true")
    elif kind == "directory":
        binary.mkdir()
    elif kind == "oversized":
        with binary.open("wb") as output:
            output.truncate(64 * 1024 * 1024 + 1)
    assert not instance.probe()["cli"]["available"]
    with pytest.raises(toolchain.ArduinoError):
        instance.prepare(dry_run=True)


def test_symlinked_parent_is_refused(runtime):
    instance, binary = runtime
    binary.unlink()
    binary.parent.rmdir()
    binary.parent.symlink_to("/usr/bin", target_is_directory=True)
    assert not instance.probe()["cli"]["available"]


def test_unknown_runtime_is_not_ready_or_overwritten(runtime):
    instance, binary = runtime
    root = binary.parents[1] / "arduino"
    root.mkdir()
    (root / "ready.json").write_text('{"ready":true}')
    assert not instance.probe()["toolchain"]["ready"]
    with pytest.raises(toolchain.ArduinoError, match="toolchain_unavailable"):
        instance.prepare(dry_run=True)


def test_platform_unavailable_is_neutral(runtime, monkeypatch):
    instance, _ = runtime
    monkeypatch.setattr(toolchain.platform, "system", lambda: "Windows")
    result = instance.probe()
    assert not result["platform"]["supported"]
    assert result["cli"]["reason"] == "Arduino toolchain not available on Windows/aarch64"
    with pytest.raises(toolchain.ArduinoError, match="platform_unavailable"):
        instance.prepare(dry_run=True)


def test_strict_arguments_and_no_workspace_override():
    with pytest.raises(ValidationError):
        toolchain.ArduinoProbeArgs.model_validate({"workspace": "/tmp"})
    for value in ["true", 1, None]:
        with pytest.raises(ValidationError):
            toolchain.ArduinoPrepareArgs.model_validate({"dry_run": value})
    with pytest.raises(toolchain.ArduinoError, match="invalid_arguments"):
        toolchain.arduino_prepare(dry_run="true")


def test_environment_cannot_redirect_runtime(runtime, tmp_path, monkeypatch):
    instance, binary = runtime
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "attacker"))
    monkeypatch.setenv("ARDUINO_DIRECTORIES_DATA", "/tmp/attacker")
    monkeypatch.setenv("PATH", "/tmp/attacker")
    assert instance.cli_path == binary
    config = instance.config()
    assert config["directories"]["data"] == str(binary.parents[1] / "arduino/data")
    assert config["board_manager"]["additional_urls"] == []
    assert config["network"]["cloud_api"]["skip_board_detection_calls"]
    assert config["updater"]["enable_notification"] is False
    assert config["metrics"]["enabled"] is False


def test_oversized_preview_refuses_without_truncation(runtime, monkeypatch):
    instance, binary = runtime
    monkeypatch.setattr(toolchain.ArduinoRuntime, "prepare_argv", lambda self: ("x" * 20_000,))
    with pytest.raises(toolchain.ArduinoError, match="preview_too_large"):
        instance.prepare(dry_run=True)
    assert not (binary.parents[1] / "arduino").exists()


def test_same_verified_state_has_same_fingerprint(runtime):
    instance, _ = runtime
    assert instance.prepare(dry_run=True) == instance.prepare(dry_run=True)


def test_manifest_records_are_immutable():
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        manifest.ARCHIVES[0].url = "https://example.invalid/replacement"


def test_matching_cli_without_execute_permission_is_unavailable(runtime):
    instance, binary = runtime
    binary.chmod(0o644)
    assert not instance.probe()["cli"]["available"]
    with pytest.raises(toolchain.ArduinoError, match="cli_unavailable"):
        instance.prepare(dry_run=True)


def test_preview_has_no_unbroken_sha256(runtime):
    import re

    instance, _ = runtime
    preview = json.dumps(instance.prepare(dry_run=True)["preview"])
    assert not re.search(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", preview)


def test_missing_receipt_prepare_has_explicit_no_install_plan(runtime, monkeypatch):
    instance, _ = runtime
    installer = overlay_module("arduino_install")
    instance.root.mkdir()
    identity = (instance.root.stat().st_dev, instance.root.stat().st_ino)
    monkeypatch.setattr(installer, "recoverable_runtime", lambda *a, **kw: identity)
    calls = []
    monkeypatch.setattr(
        installer,
        "finalize_runtime",
        lambda *a, **kw: (
            calls.append(kw) or {"ok": True, "changed": True, "action": "finalize_ready"}
        ),
    )
    plan = instance.prepare(dry_run=True)
    displayed = json.dumps(plan["preview"])
    assert "Publish verified readiness receipt" in displayed
    assert "No command, download or extraction" in displayed
    assert "ready.json" in displayed
    assert not calls and not (instance.root / "ready.json").exists()
    assert instance.prepare()["action"] == "finalize_ready"
    assert calls[0]["identity"] == identity
