"""Upload consent binds a real USB identity and the exact immutable application build."""

import os
import sys
import time
import uuid

import pytest
from pydantic import ValidationError

from code_paths import overlay_module  # isort: skip

upload = overlay_module("arduino_upload")


@pytest.mark.parametrize(
    "extra",
    [
        {"device_ref": "/dev/ttyUSB0"},
        {"build_id": "../bad"},
        {"dry_run": "true"},
        {"fqbn": "arduino:avr:mega"},
        {"port": "ttyUSB0"},
    ],
)
def test_closed_upload_arguments(extra):
    with pytest.raises(ValidationError):
        upload.UploadArgs.model_validate(
            {
                "sketch": "Sensor",
                "fqbn": "arduino:avr:uno",
                "build_id": str(uuid.uuid4()),
                "device_ref": "usb:port-1-2",
                **extra,
            }
        )


def test_only_exact_application_hex_is_selected():
    good = {"path": "Sensor.ino.hex", "kind": "hex"}
    boot = {"path": "Sensor.ino.with_bootloader.hex", "kind": "hex"}
    assert upload.application_artifact({"artifacts": [boot, good]}, "Sensor") == good
    for entries in ([boot], [good, good], [{"path": "other.hex", "kind": "hex"}]):
        with pytest.raises(upload.ArduinoError, match="integrity_mismatch"):
            upload.application_artifact({"artifacts": entries}, "Sensor")


def test_usb_resolution_refuses_missing_ambiguous_and_incompatible(monkeypatch):
    good = upload.UsbTarget("usb:port-1-2", "/dev/ttyUSB0", "1-2", None, 0x1A86, 0x7523)
    monkeypatch.setattr(upload, "enumerate_usb", lambda: [good])
    assert upload.resolve_device(good.device_ref) == good
    assert good.identity_basis == "port_position"
    with pytest.raises(upload.ArduinoError, match="device_unavailable"):
        upload.resolve_device("usb:missing")
    monkeypatch.setattr(upload, "enumerate_usb", lambda: [good, good])
    with pytest.raises(upload.ArduinoError, match="device_ambiguous"):
        upload.resolve_device(good.device_ref)
    driver = upload.UsbTarget("usb:board", "/dev/ttyACM0", "1-3", "board", 0x0483, 0x5740)
    monkeypatch.setattr(upload, "enumerate_usb", lambda: [driver])
    with pytest.raises(upload.ArduinoError, match="profile_unsupported"):
        upload.resolve_device(driver.device_ref)


@pytest.mark.parametrize(
    "result,state",
    [
        ({"ok": False, "started": False}, "unchanged"),
        ({"ok": False, "started": True, "timed_out": True}, "unknown"),
        ({"ok": True, "started": True}, "flashed"),
    ],
)
def test_device_outcome_preserves_uncertain_started_upload(result, state):
    assert upload.upload_outcome(result)["device_state"] == state


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    runtime_module = overlay_module("arduino_toolchain")
    monkeypatch.setattr(runtime_module, "_application_root", lambda: tmp_path)
    runtime = runtime_module.ArduinoRuntime()
    (tmp_path / "Sensor").mkdir()
    (tmp_path / "Sensor/Sensor.ino").write_text("void setup() {}\nvoid loop() {}\n")
    (runtime.root / "data/packages").mkdir(parents=True)
    snapshot = upload.compiler.read_sketch(tmp_path, "Sensor")
    build_id = upload.compiler._build_id(tmp_path, snapshot, "a" * 64)
    build = runtime.root / "builds" / build_id
    build.mkdir(parents=True)
    (build / "Sensor.ino.hex").write_bytes(b":00000001FF\n")
    manifest = upload.compiler._artifact_manifest(
        build, snapshot, "a" * 64, build_id, time.monotonic() + 5
    )
    (build / "manifest.json").write_bytes(upload.canonical_bytes(manifest))
    device = upload.UsbTarget("usb:port-1-2", "/dev/null", "1-2", None, 0x1A86, 0x7523)
    monkeypatch.setattr(upload, "enumerate_usb", lambda: [device])
    monkeypatch.setattr(upload, "_refuse_busy", lambda target: None)
    monkeypatch.setattr(upload, "verify_cli", lambda path: None)
    monkeypatch.setattr(upload, "verify_runtime", lambda *args, **kwargs: "a" * 64)
    monkeypatch.setattr(upload, "_command", lambda *args, **kwargs: ("owned-upload",))
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        assert (kwargs["cwd"] / "output/Sensor.ino.hex").read_bytes() == b":00000001FF\n"
        return {"ok": True, "started": True, "exit_code": 0}

    monkeypatch.setattr(upload, "run_bounded", run)
    args = {
        "sketch": "Sensor",
        "fqbn": "arduino:avr:uno",
        "build_id": build_id,
        "device_ref": device.device_ref,
    }
    return tmp_path, runtime, args, calls


def test_execution_refuses_before_device_inspection_or_launch(prepared, monkeypatch):
    root, _, args, calls = prepared
    monkeypatch.setattr(upload, "resolve_device", lambda ref: pytest.fail("device inspected"))
    with pytest.raises(upload.ArduinoError, match="device_ownership_unavailable"):
        upload.arduino_upload(root, **args)
    assert calls == []


def test_preview_is_write_free_and_reports_execution_unavailable(prepared):
    root, runtime, args, calls = prepared
    before = sorted(str(p) for p in root.rglob("*"))
    plan = upload.arduino_upload(root, **args, dry_run=True)
    assert sorted(str(p) for p in root.rglob("*")) == before
    assert calls == []
    text = str(plan["preview"])
    assert "Unknown; no backup" in text and "not a unique board identity" in text
    assert "exclusive serial ownership" in text
    assert not list((runtime.root / "builds").glob(".upload-*"))


@pytest.mark.parametrize("change", ["source", "artifact", "manifest", "symlink", "foreign"])
def test_stale_or_foreign_artifact_never_launches(prepared, change):
    root, runtime, args, calls = prepared
    build = runtime.root / "builds" / args["build_id"]
    if change == "source":
        (root / "Sensor/Sensor.ino").write_text("changed")
    elif change == "foreign":
        args["build_id"] = str(uuid.uuid4())
    elif change == "symlink":
        (build / "Sensor.ino.hex").unlink()
        (build / "Sensor.ino.hex").symlink_to(root / "Sensor/Sensor.ino")
    else:
        (build / ("manifest.json" if change == "manifest" else "Sensor.ino.hex")).write_text(
            "changed"
        )
    with pytest.raises(upload.ArduinoError):
        upload.arduino_upload(root, **args, dry_run=True)
    assert calls == []


def internal_execute(prepared):
    """Exercise retained staging helper, never the fail-closed public tool."""
    root, runtime, args, _ = prepared
    parsed = upload.UploadArgs.model_validate(args)
    snapshot = upload.compiler.read_sketch(root, args["sketch"])
    deadline = time.monotonic() + 5
    manifest = upload._manifest(runtime, snapshot, "a" * 64, parsed, deadline)
    device = upload.resolve_device(args["device_ref"])
    return upload._execute(
        root, runtime, parsed, device, upload._device_stat(device), snapshot, manifest, deadline
    )


def test_internal_started_timeout_is_unknown_and_not_retried(prepared, monkeypatch):
    root, runtime, args, calls = prepared

    def timeout(*arguments, **kwargs):
        calls.append(arguments)
        return {"ok": False, "started": True, "timed_out": True, "stderr_tail": "timeout"}

    monkeypatch.setattr(upload, "run_bounded", timeout)
    result = internal_execute(prepared)
    assert result["device_state"] == "unknown" and result["stderr_tail"] == "timeout"
    assert len(calls) == 1
    assert not list((runtime.root / "builds").glob(".upload-*"))


def test_internal_source_changes_while_preparing_job_never_launches(prepared, monkeypatch):
    root, _, args, calls = prepared
    original = upload.compiler._prepare_job

    def mutate(*arguments):
        original(*arguments)
        (root / "Sensor/Sensor.ino").write_text("changed during job setup")

    monkeypatch.setattr(upload.compiler, "_prepare_job", mutate)
    with pytest.raises(upload.ArduinoError, match="stale_state"):
        internal_execute(prepared)
    assert calls == []


def test_internal_port_inode_replaced_after_preview_never_launches(prepared, monkeypatch):
    root, _, args, calls = prepared
    original = upload.compiler._prepare_job

    def mutate(*arguments):
        original(*arguments)
        monkeypatch.setattr(upload, "_device_stat", lambda device: (100, 200, 300))

    monkeypatch.setattr(upload.compiler, "_prepare_job", mutate)
    with pytest.raises(upload.ArduinoError, match="stale_state"):
        internal_execute(prepared)
    assert calls == []


def test_complete_upload_command_is_offline_verified_and_only_one_device(tmp_path):
    runtime = upload.ArduinoRuntime()
    argv = upload._command(runtime, tmp_path, "Sensor.ino.hex", preview=True)
    assert "--unshare-all" in argv and "--share-net" not in argv
    assert argv.count("--dev-bind") == 1
    assert argv[argv.index("--dev-bind") + 1 : argv.index("--dev-bind") + 3] == (
        "/proc/self/fd/<held-device-fd>",
        "/dev/solus-upload",
    )
    assert "--verify" in argv and "--input-file" in argv
    assert "--protocol" in argv and "--fqbn" in argv
    assert "board" not in argv and "--upload" not in argv
    assert "--ro-bind-fd" in argv


def test_device_descriptor_is_not_granted_to_compile(tmp_path):
    process = overlay_module("arduino_process")
    descriptor = os.open("/dev/null", os.O_PATH | os.O_NOFOLLOW)
    try:
        with pytest.raises(upload.ArduinoError, match="invalid_arguments"):
            process.sandbox_argv(
                tmp_path / "cli", tmp_path, ("owned",), device_fd=descriptor, preview=True
            )
        argv = [
            str(process.BWRAP),
            "--dev-bind",
            f"/proc/self/fd/{descriptor}",
            "/dev/solus-upload",
        ]
        assert process._sandbox_descriptors(argv) == ((descriptor,), [])
        with pytest.raises(upload.ArduinoError):
            process._sandbox_descriptors(
                [str(process.BWRAP), "--dev-bind", "/dev/null", "/dev/solus-upload"]
            )
    finally:
        os.close(descriptor)


def test_bounded_output_uses_existing_progress_without_invented_percent(tmp_path):
    process = overlay_module("arduino_process")
    progress = overlay_module("progress")
    events = []
    token = progress.OUTPUT_CALLBACK.set(lambda stream, text: events.append((stream, text)))
    try:
        result = process.run_bounded(
            [sys.executable, "-c", "print('verification output')"],
            cwd=tmp_path,
            env=process.closed_environment(tmp_path),
            deadline=time.monotonic() + 5,
        )
    finally:
        progress.OUTPUT_CALLBACK.reset(token)
    assert result["ok"] and events == [("stdout", "verification output\n")]


@pytest.mark.parametrize(
    "serial,basis,ref",
    [
        (None, "port_position", "usb:port-1-2"),
        ("board-id", "serial", "usb:board-id"),
        ("port-forged", "port_position", "usb:port-1-2"),
    ],
)
def test_sysfs_enumeration_reads_identity_without_opening_tty(
    tmp_path, monkeypatch, serial, basis, ref
):
    tty = tmp_path / "tty/ttyUSB0"
    tty.mkdir(parents=True)
    usb = tmp_path / "usb/1-2"
    interface = usb / "1-2:1.0"
    interface.mkdir(parents=True)
    (usb / "idVendor").write_text("1a86\n")
    (usb / "idProduct").write_text("7523\n")
    if serial is not None:
        (usb / "serial").write_text(serial)
    (tty / "device").symlink_to(interface)
    (tmp_path / "tty/ttyS0").mkdir()
    (tmp_path / "tty/ttyACM1").mkdir()
    monkeypatch.setattr(upload, "_SYS_TTY", tmp_path / "tty")
    found = upload.enumerate_usb()
    assert len(found) == 1 and found[0].device_ref == ref
    assert found[0].identity_basis == basis and found[0].path == "/dev/ttyUSB0"
    (usb / "serial").write_text("x" * 1000)
    assert upload.enumerate_usb() == []


def test_busy_process_is_refused_without_opening_device(tmp_path, monkeypatch):
    handles = tmp_path / "123/fd"
    handles.mkdir(parents=True)
    (handles / "7").symlink_to("/dev/ttyUSB0")
    monkeypatch.setattr(upload, "_PROC", tmp_path)
    device = upload.UsbTarget("usb:id", "/dev/ttyUSB0", "1-2", "id", 0x1A86, 0x7523)
    with pytest.raises(upload.ArduinoError, match="device_busy"):
        upload._refuse_busy(device)
