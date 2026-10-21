"""Verified upload previews; execution stays closed until exclusive tty handoff exists."""

from __future__ import annotations

import hashlib
import os
import stat
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, field_validator

from . import arduino_compile as compiler
from .arduino_install import (
    held_directory,
    read_bounded,
    verify_cli,
    verify_runtime,
)
from .arduino_manifest import CLI_SHA256, canonical_bytes
from .arduino_process import closed_environment, run_bounded, sandbox_argv
from .arduino_toolchain import ArduinoError, ArduinoRuntime, _display_digest, _fingerprint

_SYS_TTY = Path("/sys/class/tty")


def _o_path() -> int:
    """Linux's O_PATH. There is no fallback to a real open, which would invoke the
    serial driver's open/reset, so other platforms refuse."""
    if not hasattr(os, "O_PATH"):
        raise ArduinoError("device_unavailable")
    flag: int = getattr(os, "O_PATH")  # noqa: B009 - Linux-only attribute
    return flag


_PROC = Path("/proc")


def _sysfs_text(path: Path) -> str:
    with path.open() as source:
        value = source.read(256)
    if len(value) == 256:
        raise ValueError("resource_limit")
    return value.strip()


class UploadArgs(compiler.CompileArgs):
    build_id: str
    device_ref: str = Field(min_length=5, max_length=200)

    @field_validator("build_id")
    @classmethod
    def valid_build_id(cls, value: str) -> str:
        if str(uuid.UUID(value)) != value:
            raise ValueError("invalid_arguments")
        return value

    @field_validator("device_ref")
    @classmethod
    def valid_device(cls, value: str) -> str:
        if (
            not value.startswith("usb:")
            or not value.isprintable()
            or any(char in value for char in "/\\\x00")
        ):
            raise ValueError("invalid_arguments")
        return value


@dataclass(frozen=True)
class UsbTarget:
    device_ref: str
    path: str
    location: str
    serial: str | None
    vid: int
    pid: int

    @property
    def identity_basis(self) -> str:
        return "serial" if self.serial else "port_position"


def enumerate_usb() -> list[UsbTarget]:
    """Read Linux USB sysfs metadata only; never open or reset a serial port."""
    result = []
    for tty in _SYS_TTY.iterdir():
        if not tty.name.startswith(("ttyUSB", "ttyACM")):
            continue
        try:
            device = (tty / "device").resolve(strict=True)
            usb = next(
                parent
                for parent in (device, *device.parents)
                if (parent / "idVendor").is_file() and (parent / "idProduct").is_file()
            )
            vid = int(_sysfs_text(usb / "idVendor"), 16)
            pid = int(_sysfs_text(usb / "idProduct"), 16)
            serial_path = usb / "serial"
            serial = _sysfs_text(serial_path) if serial_path.is_file() else None
            if serial and (serial.startswith("port-") or not serial.isprintable()):
                serial = None
            ref = "usb:" + (serial or "port-" + usb.name)
            UploadArgs.valid_device(ref)
            result.append(UsbTarget(ref, "/dev/" + tty.name, usb.name, serial, vid, pid))
        except (OSError, ValueError, StopIteration):
            continue
    return result


def resolve_device(device_ref: str) -> UsbTarget:
    matches = [device for device in enumerate_usb() if device.device_ref == device_ref]
    if not matches:
        raise ArduinoError("device_unavailable")
    if len(matches) != 1:
        raise ArduinoError("device_ambiguous")
    device = matches[0]
    # Only the frozen Uno profile and its explicitly selected common bridge.
    # A bridge is not evidence of a board model; every other USB profile refuses.
    if (device.vid, device.pid) not in {(0x2341, 0x0043), (0x2A03, 0x0043), (0x1A86, 0x7523)}:
        raise ArduinoError("profile_unsupported")
    return device


def application_artifact(manifest: dict[str, Any], sketch: str) -> dict[str, Any]:
    expected = sketch.split("/")[-1] + ".ino.hex"
    matches = [
        entry
        for entry in manifest["artifacts"]
        if entry["path"] == expected and entry["kind"] == "hex"
    ]
    if len(matches) != 1:
        raise ArduinoError("integrity_mismatch")
    return dict(matches[0])


def upload_outcome(result: dict[str, Any]) -> dict[str, Any]:
    state = (
        "flashed"
        if result["ok"] and result["started"]
        else ("unknown" if result["started"] else "unchanged")
    )
    return {"device_state": state, **result}


def _device_stat(device: UsbTarget) -> tuple[int, int, int]:
    info = Path(device.path).lstat()
    if not stat.S_ISCHR(info.st_mode):
        raise ArduinoError("device_unavailable")
    return info.st_dev, info.st_ino, info.st_rdev


def _refuse_busy(device: UsbTarget) -> None:
    """Check readable process handles without opening the target; owned jobs also serialize."""
    for process in _PROC.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            for handle in (process / "fd").iterdir():
                try:
                    if os.readlink(handle).removesuffix(" (deleted)") == device.path:
                        if int(process.name) == os.getpid():
                            import fcntl

                            flags = fcntl.fcntl(int(handle.name), fcntl.F_GETFL)
                            if flags & _o_path():
                                continue
                        raise ArduinoError("device_busy")
                except FileNotFoundError:
                    continue
        except (PermissionError, FileNotFoundError):
            continue


def _command(
    runtime: ArduinoRuntime,
    job: Path,
    artifact: str,
    *,
    job_fd: int | None = None,
    packages_fd: int | None = None,
    device_fd: int | None = None,
    preview: bool = False,
) -> tuple[str, ...]:
    argv = (
        str(runtime.cli_path),
        "--config-file",
        str(job / "arduino-cli.json"),
        "--no-color",
        "upload",
        "--fqbn",
        "arduino:avr:uno",
        "--port",
        "/dev/solus-upload",
        "--protocol",
        "serial",
        "--input-file",
        str(job / "output" / artifact),
        "--verify",
    )
    return sandbox_argv(
        runtime.cli_path,
        job,
        argv,
        packages=runtime.root / "data/packages",
        writable_fd=job_fd,
        packages_fd=packages_fd,
        device_fd=device_fd,
        upload=True,
        preview=preview,
    )


def _manifest(
    runtime: ArduinoRuntime,
    snapshot: compiler.SketchSnapshot,
    toolchain: str,
    args: UploadArgs,
    deadline: float,
) -> dict[str, Any]:
    with held_directory(runtime.root / "builds" / args.build_id) as (build, _):
        manifest = compiler._existing_build(build, snapshot, toolchain, args.build_id, deadline)
    if manifest is None:
        raise ArduinoError("integrity_mismatch")
    application_artifact(manifest, args.sketch)
    return manifest


def _preview(
    root: Path,
    args: UploadArgs,
    runtime: ArduinoRuntime,
    snapshot: compiler.SketchSnapshot,
    manifest: dict[str, Any],
    device: UsbTarget,
) -> dict[str, Any]:
    artifact = application_artifact(manifest, args.sketch)
    job = runtime.root / "builds" / (".upload-" + args.build_id)
    values = [
        ("Workspace", str(root)),
        ("Sketch", args.sketch),
        ("Device", device.device_ref),
        ("Observed port", device.path),
        ("USB VID:PID", f"{device.vid:04x}:{device.pid:04x}"),
        (
            "USB identity basis",
            "USB serial"
            if device.serial
            else "Port-bound USB location; not a unique board identity",
        ),
        ("Selected board profile", args.fqbn),
        (
            "Observed board",
            "Unknown MCU behind USB bridge"
            if device.vid == 0x1A86
            else "USB identity compatible with selected profile",
        ),
        ("Prior firmware", "Unknown; no backup is available"),
        (
            "Upload availability",
            "Unavailable: uploader cannot retain exclusive serial ownership. "
            "Disconnect controllers and use Arduino IDE for a manually reviewed upload.",
        ),
        ("Consequence", "Replace existing firmware with this application; one attempt, no retry"),
        ("Build ID", args.build_id),
        ("Application artifact", artifact["path"]),
        ("Source SHA-256", _display_digest(snapshot.sha256)),
        ("CLI SHA-256", _display_digest(CLI_SHA256)),
        ("Toolchain SHA-256", _display_digest(manifest["toolchain_sha256"])),
        ("Manifest SHA-256", _display_digest(manifest["manifest_sha256"])),
        ("Artifact SHA-256", _display_digest(artifact["sha256"])),
    ]
    command = canonical_bytes(_command(runtime, job, artifact["path"], preview=True)).decode()
    values.extend(
        (f"Exact sandbox argv {index // 400 + 1}", command[index : index + 400])
        for index in range(0, len(command), 400)
    )
    if len(values) >= 40 or any(len(value) > 400 or not value.isprintable() for _, value in values):
        raise ArduinoError("preview_too_large")
    rows = [{"label": label, "before": None, "after": value} for label, value in values]
    fingerprint = _fingerprint(
        {
            "rows": rows,
            "device": asdict(device),
            "inode": _device_stat(device),
            "source": snapshot.identity,
        }
    )
    rows.append({"label": "Plan fingerprint", "before": None, "after": fingerprint})
    return {"ok": True, "dry_run": True, "preview": rows, "fingerprint": fingerprint}


def arduino_upload(
    root: Path, *, sketch: str, fqbn: str, build_id: str, device_ref: str, dry_run: bool = False
) -> dict[str, Any]:
    """Preview the immutable build and target; refuse execution without serial ownership."""
    try:
        args = UploadArgs.model_validate(
            {
                "sketch": sketch,
                "fqbn": fqbn,
                "build_id": build_id,
                "device_ref": device_ref,
                "dry_run": dry_run,
            }
        )
    except ValidationError:
        raise ArduinoError("invalid_arguments") from None
    # O_PATH pins a node, not the serial driver's ownership. avrdude reopens its
    # port, so releasing TIOCEXCL for it would reopen the controller race. Keep
    # execution closed until an uploader can consume an already-exclusive FD.
    if not args.dry_run:
        raise ArduinoError("device_ownership_unavailable")
    deadline = time.monotonic() + 120
    root = root.absolute()
    runtime = ArduinoRuntime()
    verify_cli(runtime.cli_path)
    toolchain = verify_runtime(runtime.root, runtime.config(), deadline=deadline)
    snapshot = compiler.read_sketch(root, sketch, deadline=deadline)
    if compiler._build_id(root, snapshot, toolchain) != args.build_id:
        raise ArduinoError("stale_state")
    manifest = _manifest(runtime, snapshot, toolchain, args, deadline)
    device = resolve_device(args.device_ref)
    _refuse_busy(device)
    return _preview(root, args, runtime, snapshot, manifest, device)


def _execute(
    root: Path,
    runtime: ArduinoRuntime,
    args: UploadArgs,
    device: UsbTarget,
    device_inode: tuple[int, int, int],
    snapshot: compiler.SketchSnapshot,
    manifest: dict[str, Any],
    deadline: float,
) -> dict[str, Any]:
    with held_directory(runtime.root / "data/packages") as (_, packages_fd):
        verify_runtime(runtime.root, runtime.config(), deadline=deadline)
        observed = (runtime.root / "data/packages").lstat()
        pinned = os.fstat(packages_fd)
        if (observed.st_dev, observed.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise ArduinoError("stale_state")
        with held_directory(runtime.root / "builds") as (builds, builds_fd):
            name = ".upload-" + args.build_id
            os.mkdir(name, mode=0o700, dir_fd=builds_fd)
            with held_directory(builds / name) as (job, job_fd):
                try:
                    canonical_job = runtime.root / "builds" / name
                    compiler._prepare_job(job, canonical_job, args.sketch.split("/")[-1], snapshot)
                    artifact = application_artifact(manifest, args.sketch)
                    body = read_bounded(builds / args.build_id / artifact["path"], 32 * 1024**2)
                    if (
                        len(body) != artifact["size_bytes"]
                        or hashlib.sha256(body).hexdigest() != artifact["sha256"]
                    ):
                        raise ArduinoError("integrity_mismatch")
                    (job / "output" / artifact["path"]).write_bytes(body)
                    if compiler.read_sketch(root, args.sketch, deadline=deadline) != snapshot:
                        raise ArduinoError("stale_state")
                    if (
                        verify_runtime(runtime.root, runtime.config(), deadline=deadline)
                        != manifest["toolchain_sha256"]
                    ):
                        raise ArduinoError("stale_state")
                    return _run_upload(
                        runtime,
                        device,
                        device_inode,
                        canonical_job,
                        job_fd,
                        packages_fd,
                        artifact["path"],
                        deadline,
                    )
                finally:
                    compiler._cleanup_job(name, builds_fd, job_fd)


def _run_upload(
    runtime: ArduinoRuntime,
    device: UsbTarget,
    device_inode: tuple[int, int, int],
    job: Path,
    job_fd: int,
    packages_fd: int,
    artifact: str,
    deadline: float,
) -> dict[str, Any]:
    before = _device_stat(device)
    if before != device_inode:
        raise ArduinoError("stale_state")
    # O_PATH holds the inode without invoking the serial driver's open/reset operation.
    descriptor = os.open(device.path, _o_path() | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        pinned = os.fstat(descriptor)
        if (pinned.st_dev, pinned.st_ino, pinned.st_rdev) != before or not stat.S_ISCHR(
            pinned.st_mode
        ):
            raise ArduinoError("stale_state")
        if resolve_device(device.device_ref) != device or _device_stat(device) != before:
            raise ArduinoError("stale_state")
        _refuse_busy(device)
        return upload_outcome(
            run_bounded(
                _command(
                    runtime,
                    job,
                    artifact,
                    job_fd=job_fd,
                    packages_fd=packages_fd,
                    device_fd=descriptor,
                ),
                cwd=job,
                env=closed_environment(job),
                deadline=deadline,
            )
        )
    finally:
        os.close(descriptor)
