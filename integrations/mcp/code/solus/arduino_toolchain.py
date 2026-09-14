"""Pinned Arduino probing and reviewed preparation through the owned installer."""

from __future__ import annotations

import hashlib
import os
import platform
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from .arduino_manifest import (
    ARCHIVES,
    CLI_VERSION,
    SOURCE_SHA256,
    canonical_bytes,
    empty_library_index,
    frozen_package_index,
    manifest_sha256,
)
from .arduino_manifest import (
    CLI_SHA256 as CLI_SHA256,
)

_MAX_CLI_BYTES = 64 * 1024 * 1024


class ArduinoError(ValueError):
    """Sanitized boundary refusal; callers must map this to MCP isError."""


class ArduinoProbeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class ArduinoPrepareArgs(ArduinoProbeArgs):
    dry_run: bool = False


def _application_root() -> Path:
    # This source file is <application>/integrations/mcp/code/solus/<module>.
    # Never use cwd, caller workspace, PATH or virtual-environment variables.
    return Path(__file__).absolute().parents[4]


def _regular_digest(path: Path) -> str:
    """Read a bounded regular file via no-follow descriptors for every component."""
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:-1]:
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        child = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        os.close(descriptor)
        descriptor = child
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= _MAX_CLI_BYTES:
            raise ArduinoError("cli_unavailable")
        # The Linux descriptor path stays anchored to the opened inode. effective_ids
        # asks the kernel about this process (including ACLs), not only mode bits.
        if not before.st_mode & 0o111 or not os.access(
            f"/proc/self/fd/{descriptor}", os.X_OK, effective_ids=True
        ):
            raise ArduinoError("cli_unavailable")
        digest = hashlib.sha256()
        read_bytes = 0
        while chunk := os.read(descriptor, min(1024 * 1024, _MAX_CLI_BYTES + 1 - read_bytes)):
            read_bytes += len(chunk)
            if read_bytes > _MAX_CLI_BYTES:
                raise ArduinoError("cli_unavailable")
            digest.update(chunk)
        after = os.fstat(descriptor)

        def identity(item: os.stat_result) -> tuple[int, int, int, int, int]:
            return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)

        if identity(before) != identity(after) or read_bytes != before.st_size:
            raise ArduinoError("integrity_mismatch")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _display_digest(digest: str) -> str:
    """Keep public integrity identities intact through the central secret redactor."""
    return ":".join(digest[i : i + 16] for i in range(0, 64, 16))


def _fingerprint(value: object) -> str:
    return _display_digest(hashlib.sha256(canonical_bytes(value)).hexdigest())


@dataclass(frozen=True, slots=True)
class ArduinoRuntime:
    """Trusted application-relative paths; no caller-selected runtime root."""

    @property
    def root(self) -> Path:
        return _application_root() / ".venv" / "arduino"

    @property
    def cli_path(self) -> Path:
        return _application_root() / ".venv" / "bin" / "arduino-cli"

    def probe(self) -> dict[str, Any]:
        system, architecture = platform.system(), platform.machine()
        supported = system == "Linux" and architecture in {"aarch64", "arm64"}
        observed: str | None = None
        reason: str | None = None
        if not supported:
            reason = f"Arduino toolchain not available on {system}/{architecture}"
        else:
            try:
                observed = _regular_digest(self.cli_path)
                if observed != CLI_SHA256:
                    reason = "integrity_mismatch"
            except (OSError, ArduinoError):
                reason = "cli_unavailable"
        ready_digest = None
        if reason is None:
            from .arduino_install import verify_runtime

            try:
                ready_digest = verify_runtime(
                    self.root, self.config(), deadline=time.monotonic() + 15
                )
            except ArduinoError:
                pass
        return {
            "ok": True,
            "platform": {"os": system, "architecture": architecture, "supported": supported},
            "cli": {
                "available": reason is None,
                "version": CLI_VERSION,
                "sha256": observed,
                "reason": reason,
            },
            "toolchain": {
                "ready": ready_digest is not None,
                "manifest_sha256": ready_digest,
                "missing_dependencies": []
                if ready_digest
                else [archive.id for archive in ARCHIVES],
            },
        }

    def config(self) -> dict[str, Any]:
        """Pure fixed configuration for the future gated installer."""
        root = self.root
        return {
            "directories": {
                "data": str(root / "data"),
                "downloads": str(root / "downloads"),
                "user": str(root / "user"),
                "builtin": {"libraries": str(root / "libraries")},
            },
            "build_cache": {"path": str(root / "cache")},
            "updater": {"enable_notification": False},
            "metrics": {"enabled": False},
            "board_manager": {"additional_urls": [], "enable_unsafe_install": False},
            "library": {"enable_unsafe_install": False},
            "network": {"cloud_api": {"skip_board_detection_calls": True}, "proxy": ""},
        }

    def prepare_argv(self) -> tuple[str, ...]:
        return (
            str(self.cli_path),
            "--config-file",
            str(self.root / "arduino-cli.json"),
            "--json",
            "--no-color",
            "core",
            "install",
            "arduino:avr@1.8.8",
            "--no-overwrite",
            "--skip-post-install",
            "--skip-pre-uninstall",
        )

    def prepare(self, *, dry_run: bool = False) -> dict[str, Any]:
        from .arduino_install import finalize_runtime, install_runtime, operation_lock

        deadline = time.monotonic() + 600
        try:
            args = ArduinoPrepareArgs.model_validate({"dry_run": dry_run})
        except ValidationError:
            raise ArduinoError("invalid_arguments") from None
        state = self.probe()
        recovery = self._preparable(state)
        plan = self._finalize_plan(state, recovery) if recovery else self._prepare_plan(state)
        if args.dry_run:
            return plan
        with operation_lock(self.root.parent):
            current = self.probe()
            current_recovery = self._preparable(current)
            current_plan = (
                self._finalize_plan(current, current_recovery)
                if current_recovery
                else self._prepare_plan(current)
            )
            if current_plan["fingerprint"] != plan["fingerprint"]:
                raise ArduinoError("stale_state")
            if current_recovery:
                return finalize_runtime(
                    self.root,
                    self.cli_path,
                    self.config(),
                    identity=current_recovery,
                    deadline=deadline,
                )
            if current["toolchain"]["ready"]:
                return {
                    "ok": True,
                    "changed": False,
                    "manifest_sha256": manifest_sha256(),
                    "dependencies": [
                        {"id": a.id, "version": a.version, "sha256": a.sha256} for a in ARCHIVES
                    ],
                }
            return install_runtime(
                self.root, self.cli_path, self.config(), self.prepare_argv(), deadline=deadline
            )

    def _preparable(self, state: dict[str, Any]) -> tuple[int, int] | None:
        if not state["platform"]["supported"]:
            raise ArduinoError("platform_unavailable")
        if not state["cli"]["available"]:
            raise ArduinoError("cli_unavailable")
        try:
            self.root.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            raise ArduinoError("toolchain_unavailable") from None
        if not state["toolchain"]["ready"]:
            from .arduino_install import recoverable_runtime

            return recoverable_runtime(self.root, self.config(), deadline=time.monotonic() + 15)
        return None

    def _finalize_plan(self, state: dict[str, Any], identity: tuple[int, int]) -> dict[str, Any]:
        receipt = canonical_bytes({"schema_version": 1, "manifest_sha256": manifest_sha256()})
        values = [
            ("Action", "Publish verified readiness receipt"),
            ("Execution", "No command, download or extraction"),
            ("Installation destination", str(self.root)),
            ("Verified root identity", f"device={identity[0]}; inode={identity[1]}"),
            ("Receipt destination", str(self.root / "ready.json")),
            ("Exclusive staging destination", str(self.root / "ready.pending")),
            (
                "Receipt content",
                '{"manifest_sha256":"'
                + _display_digest(manifest_sha256())
                + '","schema_version":1}; SHA-256 stored as unseparated hexadecimal',
            ),
            ("Receipt SHA-256", _display_digest(hashlib.sha256(receipt).hexdigest())),
            ("CLI version and SHA-256", f"{CLI_VERSION}: {_display_digest(CLI_SHA256)}"),
        ]
        values.extend(
            (a.id, f"{a.size_bytes} bytes; SHA-256 {_display_digest(a.sha256)}") for a in ARCHIVES
        )
        rows = [{"label": label, "before": None, "after": value} for label, value in values]
        fingerprint = _fingerprint({"preview": rows, "state": state, "manifest": manifest_sha256()})
        rows.append({"label": "Plan fingerprint", "before": None, "after": fingerprint})
        if len(rows) > 40 or any(
            len(value) > 400 or not value.isprintable() for label, value in values
        ):
            raise ArduinoError("preview_too_large")
        return {"ok": True, "dry_run": True, "preview": rows, "fingerprint": fingerprint}

    def _prepare_plan(self, state: dict[str, Any]) -> dict[str, Any]:
        rows: list[dict[str, str | None]] = []

        def add(label: str, value: str) -> None:
            if len(label) > 400 or len(value) > 400 or not value.isprintable():
                raise ArduinoError("preview_too_large")
            rows.append({"label": label, "before": None, "after": value})

        add("Installation destination", str(self.root))
        add("CLI version and SHA-256", f"{CLI_VERSION}: {_display_digest(CLI_SHA256)}")
        add("Source index SHA-256", _display_digest(SOURCE_SHA256))
        add(
            "Package index",
            "unsigned curated derivative: "
            + _display_digest(hashlib.sha256(frozen_package_index()).hexdigest()),
        )
        add(
            "Empty library index SHA-256",
            _display_digest(hashlib.sha256(empty_library_index()).hexdigest()),
        )
        for archive in ARCHIVES:
            add(
                archive.id, f"{archive.size_bytes} bytes; SHA-256 {_display_digest(archive.sha256)}"
            )
            add(f"{archive.id} source", archive.url)
        from .arduino_process import sandbox_argv

        argv = canonical_bytes(
            sandbox_argv(self.cli_path, self.root, self.prepare_argv(), preview=True)
        ).decode()
        for index in range(0, len(argv), 400):
            add(f"Exact sandbox argv {index // 400 + 1}", argv[index : index + 400])
        # Complete fixed config split at top-level boundaries without truncating fields.
        for key, value in self.config().items():
            if key == "directories":
                for directory, destination in value.items():
                    add(f"directories.{directory}", canonical_bytes(destination).decode())
            else:
                add(key, canonical_bytes(value).decode())
        add(
            "Isolated environment",
            canonical_bytes(
                {
                    "HOME": str(self.root / "home"),
                    "TMPDIR": str(self.root / "tmp"),
                    "PATH": "/usr/bin:/bin",
                    "LANG": "C",
                    "LC_ALL": "C",
                }
            ).decode(),
        )
        fingerprint = _fingerprint({"preview": rows, "state": state, "manifest": manifest_sha256()})
        add("Plan fingerprint", fingerprint)
        if len(rows) > 40:
            raise ArduinoError("preview_too_large")
        return {"ok": True, "dry_run": True, "preview": rows, "fingerprint": fingerprint}


def arduino_probe() -> dict[str, Any]:
    return ArduinoRuntime().probe()


def arduino_prepare(*, dry_run: bool = False) -> dict[str, Any]:
    return ArduinoRuntime().prepare(dry_run=dry_run)
