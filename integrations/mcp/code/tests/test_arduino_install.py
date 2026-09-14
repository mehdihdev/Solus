"""Pinned archive validation and fail-closed installation receipts."""

import hashlib
import io
import tarfile
import time
from pathlib import Path

import pytest

from code_paths import overlay_module  # isort: skip

install = overlay_module("arduino_install")
manifest = overlay_module("arduino_manifest")


def archive_fixture(tmp_path, entries):
    path = tmp_path / "fixture.tar"
    with tarfile.open(path, "w") as output:
        for name, body, kind, target in entries:
            info = tarfile.TarInfo(name)
            info.mode = 0o755 if name.endswith("compiler") else 0o644
            if kind == "file":
                info.size = len(body)
                output.addfile(info, io.BytesIO(body))
            else:
                info.type = tarfile.SYMTYPE
                info.linkname = target
                output.addfile(info)
    record = manifest.Archive(
        "fixture",
        "tool",
        "1",
        "aarch64-linux-gnu",
        "https://downloads.arduino.cc/fixture.tar",
        path.name,
        path.stat().st_size,
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    return path, record


def test_archive_contents_derive_from_verified_bytes(tmp_path):
    path, record = archive_fixture(tmp_path, [("tool/bin/compiler", b"compiler", "file", "")])
    entries = install.archive_contents(path, record, deadline=time.monotonic() + 5)
    assert entries["bin/compiler"].sha256 == hashlib.sha256(b"compiler").hexdigest()
    path.write_bytes(b"replaced")
    with pytest.raises(install.ArduinoError, match="integrity_mismatch"):
        install.archive_contents(path, record, deadline=time.monotonic() + 5)


@pytest.mark.parametrize(
    "name,kind,target",
    [
        ("tool/../../outside", "file", ""),
        ("/absolute", "file", ""),
        ("tool/link", "link", "../../outside"),
        ("tool/link", "link", "contained"),
    ],
)
def test_unreviewed_archive_paths_and_links_refuse(tmp_path, name, kind, target):
    path, record = archive_fixture(tmp_path, [(name, b"x", kind, target)])
    with pytest.raises(install.ArduinoError):
        install.archive_contents(path, record, deadline=time.monotonic() + 5)


def test_lock_is_exclusive_and_refuses_symlink(tmp_path):
    with install.operation_lock(tmp_path):
        with pytest.raises(install.ArduinoError, match="operation_busy"):
            with install.operation_lock(tmp_path):
                pytest.fail("second writer acquired lock")
    (tmp_path / "arduino.operation.lock").unlink()
    (tmp_path / "arduino.operation.lock").symlink_to(tmp_path / "other")
    with pytest.raises(install.ArduinoError):
        with install.operation_lock(tmp_path):
            pytest.fail("symlink lock accepted")


def test_fake_receipt_does_not_establish_readiness(tmp_path):
    (tmp_path / "ready.json").write_text('{"schema_version":1,"manifest_sha256":"fake"}')
    with pytest.raises(install.ArduinoError):
        install.verify_runtime(tmp_path, {}, deadline=time.monotonic() + 5)


@pytest.fixture
def simulated_install(tmp_path, monkeypatch):
    path, record = archive_fixture(tmp_path, [("tool/bin/compiler", b"compiler", "file", "")])
    monkeypatch.setattr(install, "ARCHIVES", (record,))
    monkeypatch.setattr(install, "verify_cli", lambda path: None)
    monkeypatch.setattr(
        install,
        "download_archive",
        lambda target, archive, **kw: target.write_bytes(path.read_bytes()),
    )
    monkeypatch.setattr(install, "sandbox_argv", lambda cli, root, argv, **kw: argv)
    root = tmp_path / "runtime"
    config = {"fixture": True}

    def initialize(argv, *, cwd, env, deadline):
        import uuid

        assert env["HOME"] == str(root / "home")
        assert env["TMPDIR"] == str(root / "tmp")

        assert (cwd / "data/package_index.json").read_bytes() == manifest.frozen_package_index()
        assert (cwd / "data/library_index.json").read_bytes() == manifest.empty_library_index()
        assert (cwd / "downloads/packages" / record.filename).read_bytes() == path.read_bytes()
        (cwd / "data/tmp").mkdir()
        target = install.destination(cwd, record) / "bin/compiler"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"compiler")
        target.chmod(0o755)
        (cwd / "data/inventory.yaml").write_text(
            f"installation:\n    id: {uuid.uuid4()}\n    secret: {uuid.uuid4()}\n"
        )
        return {"ok": True, "exit_code": 0}

    monkeypatch.setattr(install, "run_bounded", initialize)
    return root, config, record


def test_simulated_install_verifies_before_ready_and_detects_tampering(simulated_install):
    root, config, record = simulated_install
    result = install.install_runtime(
        root, Path("/fixed/cli"), config, ("owned",), deadline=time.monotonic() + 5
    )
    assert result["changed"] and result["ok"]
    assert (
        install.verify_runtime(root, config, deadline=time.monotonic() + 5)
        == manifest.manifest_sha256()
    )
    (install.destination(root, record) / "bin/compiler").write_bytes(b"tampered")
    with pytest.raises(install.ArduinoError, match="toolchain_unavailable"):
        install.verify_runtime(root, config, deadline=time.monotonic() + 5)


def test_failed_install_never_publishes_readiness(simulated_install, monkeypatch):
    root, config, _ = simulated_install
    monkeypatch.setattr(install, "run_bounded", lambda *a, **kw: {"ok": False, "exit_code": 1})
    with pytest.raises(install.ArduinoError, match="installation_failed"):
        install.install_runtime(
            root, Path("/fixed/cli"), config, ("owned",), deadline=time.monotonic() + 5
        )
    assert not (root / "ready.json").exists()
    before = sorted(str(p) for p in root.rglob("*"))
    with pytest.raises(install.ArduinoError, match="toolchain_unavailable"):
        install.install_runtime(
            root, Path("/fixed/cli"), config, ("owned",), deadline=time.monotonic() + 5
        )
    assert before == sorted(str(p) for p in root.rglob("*"))


def test_runtime_builds_symlink_is_not_ready(simulated_install, tmp_path):
    root, config, record = simulated_install
    install.install_runtime(
        root, Path("/fixed/cli"), config, ("owned",), deadline=time.monotonic() + 5
    )
    (root / "builds").rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "builds").symlink_to(outside, target_is_directory=True)
    with pytest.raises(install.ArduinoError, match="toolchain_unavailable"):
        install.verify_runtime(root, config, deadline=time.monotonic() + 5)
    assert not list(outside.iterdir())


def test_installed_metadata_pins_cli_generated_index_origin_and_rejects_extras(tmp_path):
    import json

    expected = install._installed_metadata()
    assert (
        expected["packages"][0]["url"]
        == "https://downloads.arduino.cc/packages/package_index.tar.bz2"
    )
    path = tmp_path / "installed.json"
    path.write_text(json.dumps(expected))
    install._same_json(path, expected)
    modified = json.loads(json.dumps(expected))
    modified["packages"][0]["unreviewed_field"] = "extra"
    path.write_text(json.dumps(modified))
    with pytest.raises(install.ArduinoError, match="integrity_mismatch"):
        install._same_json(path, expected)


def test_cli_data_temporary_directory_must_remain_empty(simulated_install):
    root, config, _ = simulated_install
    install.install_runtime(
        root, Path("/fixed/cli"), config, ("owned",), deadline=time.monotonic() + 5
    )
    assert not list((root / "data/tmp").iterdir())
    (root / "data/tmp/unexpected.txt").write_text("unreviewed")
    with pytest.raises(install.ArduinoError, match="toolchain_unavailable"):
        install.verify_runtime(root, config, deadline=time.monotonic() + 5)


def test_exact_metadata_comparison_rejects_boolean_integer_substitution(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text('{"schema_version":true,"enabled":0}')
    with pytest.raises(install.ArduinoError, match="integrity_mismatch"):
        install._same_json(path, {"schema_version": 1, "enabled": False})


def test_installed_tool_metadata_accepts_only_order_variance(tmp_path):
    import copy
    import itertools
    import json

    expected = install._installed_metadata()
    path = tmp_path / "installed.json"
    tools = expected["packages"][0]["tools"]
    for ordering in itertools.permutations(tools):
        actual = copy.deepcopy(expected)
        actual["packages"][0]["tools"] = list(ordering)
        path.write_text(json.dumps(actual))
        install._verify_installed_metadata(path)
    for mutation in ("duplicate", "changed", "extra", "type"):
        actual = copy.deepcopy(expected)
        selected = actual["packages"][0]["tools"]
        if mutation == "duplicate":
            selected[0] = selected[1]
        elif mutation == "changed":
            selected[0]["version"] = "unreviewed"
        elif mutation == "extra":
            selected[0]["unreviewed"] = True
        else:
            actual["IsTrusted"] = 0
        path.write_text(json.dumps(actual))
        with pytest.raises(install.ArduinoError, match="integrity_mismatch"):
            install._verify_installed_metadata(path)


def test_complete_missing_receipt_can_be_finalized_without_installing(
    simulated_install, monkeypatch
):
    root, config, _ = simulated_install
    install.install_runtime(
        root, Path("/fixed/cli"), config, ("owned",), deadline=time.monotonic() + 5
    )
    (root / "ready.json").unlink()

    def forbidden(*args, **kwargs):
        pytest.fail("Recovery must not download or launch a process")

    monkeypatch.setattr(install, "download_archive", forbidden)
    monkeypatch.setattr(install, "run_bounded", forbidden)
    identity = install.recoverable_runtime(root, config, deadline=time.monotonic() + 5)
    assert not (root / "ready.json").exists()
    result = install.finalize_runtime(
        root, Path("/fixed/cli"), config, identity=identity, deadline=time.monotonic() + 5
    )
    assert result["ok"] and result["changed"] and result["action"] == "finalize_ready"
    assert result["dependencies"] == [
        {"id": archive.id, "version": archive.version, "sha256": archive.sha256}
        for archive in install.ARCHIVES
    ]
    assert install.verify_runtime(root, config, deadline=time.monotonic() + 5)


@pytest.mark.parametrize("obstacle", ["ready_symlink", "pending_symlink", "partial", "replaced"])
def test_receipt_recovery_refuses_unknown_or_changed_state(simulated_install, obstacle, tmp_path):
    root, config, record = simulated_install
    install.install_runtime(
        root, Path("/fixed/cli"), config, ("owned",), deadline=time.monotonic() + 5
    )
    (root / "ready.json").unlink()
    identity = install.recoverable_runtime(root, config, deadline=time.monotonic() + 5)
    if obstacle == "ready_symlink":
        (root / "ready.json").symlink_to(tmp_path / "missing")
    elif obstacle == "pending_symlink":
        (root / "ready.pending").symlink_to(tmp_path / "missing")
    elif obstacle == "partial":
        (install.destination(root, record) / "bin/compiler").unlink()
    else:
        root.rename(tmp_path / "prior-runtime")
        root.mkdir()
    with pytest.raises(install.ArduinoError):
        install.finalize_runtime(
            root, Path("/fixed/cli"), config, identity=identity, deadline=time.monotonic() + 5
        )
    assert not (root / "ready.json").is_file()
    if obstacle == "replaced":
        assert not list(root.iterdir())
