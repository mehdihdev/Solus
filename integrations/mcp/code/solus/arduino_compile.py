"""Compile a bounded sketch snapshot for one explicit target in an offline sandbox."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import stat
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator

from .arduino_install import (
    digest_file,
    held_descriptor,
    held_directory,
    open_directory,
    operation_lock,
    read_bounded,
    verify_cli,
    verify_runtime,
)
from .arduino_manifest import CLI_SHA256, canonical_bytes, empty_library_index, frozen_package_index
from .arduino_process import check_deadline, closed_environment, run_bounded, sandbox_argv
from .arduino_toolchain import (
    ArduinoError,
    ArduinoProbeArgs,
    ArduinoRuntime,
    _display_digest,
    _fingerprint,
)

MAX_SOURCE_ENTRIES = 1000
MAX_SOURCE_BYTES = 16 * 1024**2
MAX_SOURCE_FILE_BYTES = 2 * 1024**2
BUILD_NAMESPACE = uuid.UUID("5a72d758-54e5-4fc8-9891-deb2b377fcd3")


class CompileArgs(ArduinoProbeArgs):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    sketch: str = Field(min_length=1, max_length=512)
    fqbn: Literal["arduino:avr:uno"]
    dry_run: bool = False

    @field_validator("sketch")
    @classmethod
    def valid_sketch(cls, value: str) -> str:
        if (
            "\\" in value
            or not value.isprintable()
            or any(
                part in {"", ".", "..", ".git", ".hg", ".svn"} or part.startswith("-")
                for part in value.split("/")
            )
        ):
            raise ValueError("invalid_sketch")
        return value


@dataclass(frozen=True, slots=True)
class SketchSnapshot:
    files: Mapping[str, bytes]
    sha256: str
    identity: tuple[int, int, int, int]


def read_sketch(root: Path, sketch: str, *, deadline: float | None = None) -> SketchSnapshot:
    deadline = deadline if deadline is not None else time.monotonic() + 5
    try:
        CompileArgs.model_validate({"sketch": sketch, "fqbn": "arduino:avr:uno"})
        descriptor = open_directory(root.absolute() / sketch)
    except (OSError, ValidationError):
        raise ArduinoError("invalid_sketch") from None
    files: dict[str, bytes] = {}
    try:
        info = os.fstat(descriptor)
        _read_directory(descriptor, "", files, [0], deadline)
        after = os.fstat(descriptor)
        if (info.st_mtime_ns, info.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
            raise ArduinoError("stale_state")
    finally:
        os.close(descriptor)
    if sketch.split("/")[-1] + ".ino" not in files:
        raise ArduinoError("invalid_sketch")
    digest = hashlib.sha256(
        canonical_bytes(
            {path: hashlib.sha256(body).hexdigest() for path, body in sorted(files.items())}
        )
    ).hexdigest()
    return SketchSnapshot(
        MappingProxyType(files),
        digest,
        (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns),
    )


def _read_directory(
    descriptor: int, prefix: str, files: dict[str, bytes], count: list[int], deadline: float
) -> None:
    names = os.listdir(descriptor)
    if len(names) > MAX_SOURCE_ENTRIES:
        raise ArduinoError("resource_limit")
    for name in sorted(names):
        check_deadline(deadline)
        count[0] += 1
        if count[0] > MAX_SOURCE_ENTRIES:
            raise ArduinoError("resource_limit")
        if name.lower() in {"sketch.yaml", "sketch.yml"}:
            raise ArduinoError("profile_unsupported")
        if not name.isprintable() or name in {".git", ".hg", ".svn"} or "\\" in name:
            raise ArduinoError("invalid_sketch")
        path = prefix + name
        if len(path) > 512 or len(files) >= 1000:
            raise ArduinoError("resource_limit")
        info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=descriptor)
            try:
                _read_directory(child, path + "/", files, count, deadline)
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            files[path] = _read_source_file(descriptor, name, info)
            if sum(len(body) for body in files.values()) > MAX_SOURCE_BYTES:
                raise ArduinoError("resource_limit")
        else:
            raise ArduinoError("invalid_sketch")


def _read_source_file(directory: int, name: str, info: os.stat_result) -> bytes:
    if info.st_mode & 0o111 or Path(name).suffix.lower() in {
        ".sh",
        ".bat",
        ".cmd",
        ".ps1",
        ".py",
        ".exe",
        ".dll",
        ".so",
    }:
        raise ArduinoError("invalid_sketch")
    if info.st_size > MAX_SOURCE_FILE_BYTES:
        raise ArduinoError("resource_limit")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino) != (
            info.st_dev,
            info.st_ino,
        ):
            raise ArduinoError("stale_state")
        body = source.read(MAX_SOURCE_FILE_BYTES + 1)
        after = os.fstat(source.fileno())
        if len(body) > MAX_SOURCE_FILE_BYTES:
            raise ArduinoError("resource_limit")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(body) != before.st_size:
            raise ArduinoError("stale_state")
        return body


def _job_config(job: Path) -> dict[str, Any]:
    config = ArduinoRuntime().config()
    config["directories"] = {
        "data": str(job / "data"),
        "downloads": str(job / "downloads"),
        "user": str(job / "user"),
        "builtin": {"libraries": str(job / "libraries")},
    }
    config["build_cache"] = {"path": str(job / "cache")}
    return config


def _command(
    runtime: ArduinoRuntime,
    job: Path,
    sketch_name: str,
    *,
    job_fd: int | None = None,
    packages_fd: int | None = None,
    preview: bool = False,
) -> tuple[str, ...]:
    argv = (
        str(runtime.cli_path),
        "--config-file",
        str(job / "arduino-cli.json"),
        "--json",
        "--no-color",
        "compile",
        "--fqbn",
        "arduino:avr:uno",
        "--build-path",
        str(job / "build"),
        "--output-dir",
        str(job / "output"),
        str(job / "source" / sketch_name),
    )
    return sandbox_argv(
        runtime.cli_path,
        job,
        argv,
        packages=runtime.root / "data/packages",
        writable_fd=job_fd,
        packages_fd=packages_fd,
        preview=preview,
    )


def _build_id(root: Path, snapshot: SketchSnapshot, toolchain: str) -> str:
    info = root.stat()
    identity = canonical_bytes(
        {
            "workspace": [str(root), info.st_dev, info.st_ino],
            "source": snapshot.sha256,
            "fqbn": "arduino:avr:uno",
            "toolchain": toolchain,
        }
    ).decode()
    return str(uuid.uuid5(BUILD_NAMESPACE, identity))


def _preview(
    root: Path,
    args: CompileArgs,
    snapshot: SketchSnapshot,
    runtime: ArduinoRuntime,
    toolchain: str,
    build_id: str,
) -> dict[str, Any]:
    job = runtime.root / "builds" / (".pending-" + build_id)
    rows: list[dict[str, str | None]] = []

    def add(label: str, value: str) -> None:
        if len(value) > 400 or not value.isprintable():
            raise ArduinoError("preview_too_large")
        rows.append({"label": label, "before": None, "after": value})

    add("Workspace", str(root))
    add("Sketch", args.sketch)
    add("Source SHA-256", _display_digest(snapshot.sha256))
    add("FQBN", args.fqbn)
    add("CLI SHA-256", _display_digest(CLI_SHA256))
    add("Toolchain SHA-256", _display_digest(toolchain))
    add("Artifacts destination", str(runtime.root / "builds" / build_id))
    command = canonical_bytes(
        _command(runtime, job, args.sketch.split("/")[-1], preview=True)
    ).decode()
    for index in range(0, len(command), 400):
        add(f"Exact sandbox argv {index // 400 + 1}", command[index : index + 400])
    add(
        "Source snapshot",
        f"{len(snapshot.files)} files; {sum(map(len, snapshot.files.values()))} bytes",
    )
    fingerprint = _fingerprint({"rows": rows, "identity": snapshot.identity, "build_id": build_id})
    add("Plan fingerprint", fingerprint)
    if len(rows) > 40:
        raise ArduinoError("preview_too_large")
    return {"ok": True, "dry_run": True, "preview": rows, "fingerprint": fingerprint}


def _prepare_job(
    job: Path, canonical_job: Path, sketch_name: str, snapshot: SketchSnapshot
) -> None:
    for name in (
        "data/packages",
        "downloads",
        "user",
        "libraries",
        "home",
        "tmp",
        "cache",
        "build",
        "output",
    ):
        (job / name).mkdir(mode=0o700, parents=True, exist_ok=True)
    source = job / "source" / sketch_name
    source.mkdir(mode=0o700, parents=True)
    for path, body in snapshot.files.items():
        target = source / path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(body)
    (job / "arduino-cli.json").write_bytes(canonical_bytes(_job_config(canonical_job)))
    (job / "data/package_index.json").write_bytes(frozen_package_index())
    (job / "data/library_index.json").write_bytes(empty_library_index())
    if read_sketch(job / "source", sketch_name).sha256 != snapshot.sha256:
        raise ArduinoError("stale_state")


def _artifact_manifest(
    output: Path, snapshot: SketchSnapshot, toolchain: str, build_id: str, deadline: float
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    total = 0
    for path in sorted(output.iterdir()):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ArduinoError("integrity_mismatch")
        kind = path.suffix[1:]
        if kind not in {"hex", "elf", "bin"}:
            continue
        total += info.st_size
        if len(artifacts) >= 8 or total > 32 * 1024**2:
            raise ArduinoError("resource_limit")
        artifacts.append(
            {
                "path": path.name,
                "size_bytes": info.st_size,
                "sha256": digest_file(path, info.st_size, deadline),
                "kind": kind,
            }
        )
    if not artifacts or not any(a["kind"] == "hex" for a in artifacts):
        raise ArduinoError("integrity_mismatch")
    result: dict[str, Any] = {
        "schema_version": 1,
        "build_id": build_id,
        "source_sha256": snapshot.sha256,
        "fqbn": "arduino:avr:uno",
        "cli_sha256": CLI_SHA256,
        "toolchain_sha256": toolchain,
        "artifacts": artifacts,
    }
    result["manifest_sha256"] = hashlib.sha256(canonical_bytes(result)).hexdigest()
    return result


def _existing_build(
    final: Path, snapshot: SketchSnapshot, toolchain: str, build_id: str, deadline: float
) -> dict[str, Any] | None:
    try:
        final.lstat()
    except FileNotFoundError:
        return None
    try:
        stored = json.loads(read_bounded(final / "manifest.json", 16 * 1024))
        actual = _artifact_manifest(final, snapshot, toolchain, build_id, deadline)
        if stored != actual or {p.name for p in final.iterdir()} != {"manifest.json"} | {
            entry["path"] for entry in actual["artifacts"]
        }:
            raise ArduinoError("integrity_mismatch")
        return actual
    except (OSError, ValueError):
        raise ArduinoError("integrity_mismatch") from None


def arduino_compile(root: Path, *, sketch: str, fqbn: str, dry_run: bool = False) -> dict[str, Any]:
    deadline = time.monotonic() + 120
    try:
        args = CompileArgs.model_validate({"sketch": sketch, "fqbn": fqbn, "dry_run": dry_run})
    except ValidationError:
        raise ArduinoError("invalid_arguments") from None
    root = root.absolute()
    runtime = ArduinoRuntime()
    probe = runtime.probe()
    if "platform" in probe and not probe["platform"]["supported"]:
        raise ArduinoError("platform_unavailable")
    if not probe["cli"]["available"]:
        raise ArduinoError("cli_unavailable")
    toolchain = verify_runtime(runtime.root, runtime.config(), deadline=deadline)
    snapshot = read_sketch(root, args.sketch, deadline=deadline)
    build_id = _build_id(root, snapshot, toolchain)
    plan = _preview(root, args, snapshot, runtime, toolchain, build_id)
    if args.dry_run:
        return plan
    with operation_lock(runtime.root.parent):
        with held_directory(runtime.root) as (runtime_anchor, _):
            return _compile_locked(
                root, args, runtime, runtime_anchor, snapshot, toolchain, build_id, deadline
            )


def _compile_locked(
    root: Path,
    args: CompileArgs,
    runtime: ArduinoRuntime,
    runtime_anchor: Path,
    snapshot: SketchSnapshot,
    toolchain: str,
    build_id: str,
    deadline: float,
) -> dict[str, Any]:
    if verify_runtime(runtime_anchor, runtime.config(), deadline=deadline) != toolchain:
        raise ArduinoError("stale_state")
    current = read_sketch(root, args.sketch, deadline=deadline)
    if current.sha256 != snapshot.sha256 or current.identity != snapshot.identity:
        raise ArduinoError("stale_state")
    with held_directory(runtime_anchor / "data/packages") as (_, packages_fd):
        verify_runtime(runtime_anchor, runtime.config(), deadline=deadline)
        observed = (runtime_anchor / "data/packages").lstat()
        pinned = os.fstat(packages_fd)
        if (observed.st_dev, observed.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise ArduinoError("stale_state")
        with held_directory(runtime_anchor / "builds") as (builds, builds_fd):
            final = builds / build_id
            existing = _existing_build(final, snapshot, toolchain, build_id, deadline)
            if existing is not None:
                return with_artifact_summary(
                    {
                        "ok": True,
                        "exit_code": 0,
                        "stdout_tail": "",
                        "stderr_tail": "",
                        "stdout_truncated": False,
                        "stderr_truncated": False,
                        "changed": False,
                        "started": False,
                    },
                    existing,
                )
            name = ".pending-" + build_id
            try:
                os.mkdir(name, mode=0o700, dir_fd=builds_fd)
                job_fd = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=builds_fd
                )
            except OSError:
                raise ArduinoError("operation_busy") from None
            with held_descriptor(job_fd) as (job, _):
                try:
                    canonical_job = runtime.root / "builds" / name
                    _prepare_job(job, canonical_job, args.sketch.split("/")[-1], snapshot)
                    check_deadline(deadline)
                    verify_cli(runtime.cli_path)
                    result = run_bounded(
                        _command(
                            runtime,
                            canonical_job,
                            args.sketch.split("/")[-1],
                            job_fd=job_fd,
                            packages_fd=packages_fd,
                        ),
                        cwd=job,
                        env=closed_environment(canonical_job),
                        deadline=deadline,
                        expect_json_success=True,
                    )
                    if not result["ok"]:
                        return result
                    return _publish_result(
                        root,
                        args,
                        runtime,
                        runtime_anchor,
                        job,
                        final,
                        snapshot,
                        toolchain,
                        build_id,
                        deadline,
                        result,
                    )
                finally:
                    _cleanup_job(name, builds_fd, job_fd)


def _publish_result(
    root: Path,
    args: CompileArgs,
    runtime: ArduinoRuntime,
    runtime_anchor: Path,
    job: Path,
    final: Path,
    snapshot: SketchSnapshot,
    toolchain: str,
    build_id: str,
    deadline: float,
    result: dict[str, Any],
) -> dict[str, Any]:
    try:
        verify_cli(runtime.cli_path)
        manifest = _artifact_manifest(job / "output", snapshot, toolchain, build_id, deadline)
        verify_runtime(runtime_anchor, runtime.config(), deadline=deadline)
        current = read_sketch(root, args.sketch, deadline=deadline)
        if current.sha256 != snapshot.sha256 or current.identity != snapshot.identity:
            raise ArduinoError("stale_state")
        response = with_artifact_summary(result, manifest)
        # Publish only verified artifacts. Build intermediates remain private in the job.
        publish = job / "publish"
        publish.mkdir(mode=0o700)
        for artifact in manifest["artifacts"]:
            os.rename(job / "output" / artifact["path"], publish / artifact["path"])
        (publish / "manifest.json").write_bytes(canonical_bytes(manifest))
        check_deadline(deadline)
        _publish_noreplace(publish, final)
        return response
    except (OSError, ValueError):
        return {**result, "ok": False, "reason": "compilation_unverified"}


def _cleanup_job(name: str, parent_fd: int, job_fd: int) -> None:
    """Clear this held inode; a swapped real directory is never traversed or erased."""
    try:
        for child in os.listdir(job_fd):
            info = os.stat(child, dir_fd=job_fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                if not shutil.rmtree.avoids_symlink_attacks:
                    return
                shutil.rmtree(child, dir_fd=job_fd)
            else:
                os.unlink(child, dir_fd=job_fd)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        original = os.fstat(job_fd)
        if (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino):
            # rmdir cannot delete data if another directory is swapped in at this point.
            os.rmdir(name, dir_fd=parent_fd)
    except OSError:
        pass


def _publish_noreplace(source: Path, target: Path) -> None:
    """Linux atomic directory publication never replaces an existing target."""
    library = ctypes.CDLL(None, use_errno=True)
    rename = library.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    source_fd, target_fd = open_directory(source.parent), open_directory(target.parent)
    try:
        if rename(source_fd, os.fsencode(source.name), target_fd, os.fsencode(target.name), 1) != 0:
            raise ArduinoError("stale_state")
    finally:
        os.close(source_fd)
        os.close(target_fd)


def with_artifact_summary(result: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Public identities precede logs; canonical raw hashes remain in the disk manifest."""
    summary = {
        "build_id": manifest["build_id"],
        "fqbn": manifest["fqbn"],
        "source_fingerprint": _display_digest(manifest["source_sha256"]),
        "toolchain_fingerprint": _display_digest(manifest["toolchain_sha256"]),
        "manifest_fingerprint": _display_digest(manifest["manifest_sha256"]),
        "artifacts": [
            {
                "path": item["path"],
                "size_bytes": item["size_bytes"],
                "kind": item["kind"],
                "fingerprint": _display_digest(item["sha256"]),
            }
            for item in manifest["artifacts"]
        ],
    }
    encoded = json.dumps(summary, ensure_ascii=True).replace("<", "\\u003c")
    if len(encoded) >= 3000:
        raise ArduinoError("resource_limit")
    return {"artifact_summary": summary, **result, "artifact_manifest": manifest}
