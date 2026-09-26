"""Provisioned-target helper, installed by an administrator at the pinned path.

Prerequisites: private ~/.solus/companion-deploy with provisioned.json {format:1},
releases/<sha256>.pyz, current.pyz symlink and a pre-enrolled user service named
solus-companion.service executing current.pyz. Offline zipapps must include their
runtime dependencies. This helper neither enrolls credentials nor installs units.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_SERVICE = "solus-companion.service"
_CAP = 32 * 1024 * 1024


def _systemctl(argv: list[str]) -> None:
    subprocess.run(  # noqa: S603 — argv built only from fixed systemctl stages below
        argv, check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def _private_dir(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("unsafe deployment directory")


def _read(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit or info.st_uid != os.getuid():
            raise ValueError("invalid deployment file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("deployment file too large")
    return data


def _write_new(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


class RemoteDeployment:
    def __init__(self, root: Path, systemctl: Callable[[list[str]], None] = _systemctl):
        self.root, self.systemctl = root, systemctl

    def _current(self) -> str:
        path = self.root / "current.pyz"
        if not path.is_symlink():
            raise ValueError("provisioned current release required")
        resolved = path.resolve(strict=True)
        if resolved.parent != (self.root / "releases").resolve() or not _SHA.fullmatch(
            resolved.stem
        ):
            raise ValueError("invalid release pointer")
        if hashlib.sha256(_read(resolved, _CAP)).hexdigest() != resolved.stem:
            raise ValueError("installed release digest changed")
        return resolved.stem

    def _switch(self, digest: str, stage: Path) -> None:
        temporary = stage / "next.pyz"
        temporary.symlink_to(self.root / "releases" / f"{digest}.pyz")
        temporary.replace(self.root / "current.pyz")

    def run(self, phase: str, operation: str, digest: str) -> None:
        if (
            phase not in {"preflight", "install", "start", "rollback", "cleanup"}
            or str(uuid.UUID(operation)) != operation
            or not _SHA.fullmatch(digest)
        ):
            raise ValueError("invalid deployment arguments")
        _private_dir(self.root)
        if json.loads(_read(self.root / "provisioned.json", 1024)) != {"format": 1}:
            raise ValueError("target not provisioned")
        releases = self.root / "releases"
        _private_dir(releases)
        staging = self.root / "staging"
        staging.mkdir(mode=0o700, exist_ok=True)
        _private_dir(staging)
        stage = staging / operation
        active = self.root / "active"
        if phase == "preflight":
            self._preflight(active, stage, operation)
            return
        if _read(active, 64).decode() != operation:
            raise ValueError("another deployment owns target")
        _private_dir(stage)
        if phase == "install":
            self._install(stage, digest)
        elif phase == "start":
            if self._current() != digest:
                raise ValueError("release changed before start")
            self.systemctl(["/usr/bin/systemctl", "--user", "restart", _SERVICE])
        elif phase == "rollback":
            self._rollback(stage, digest)
        else:
            for name in ("bundle.pyz", "previous", "next.pyz"):
                (stage / name).unlink(missing_ok=True)
            stage.rmdir()
            active.unlink()

    def _rollback(self, stage: Path, digest: str) -> None:
        previous = _read(stage / "previous", 64).decode()
        if not _SHA.fullmatch(previous) or self._current() not in {digest, previous}:
            raise ValueError("release changed before rollback")
        self._switch(previous, stage)
        self.systemctl(["/usr/bin/systemctl", "--user", "restart", _SERVICE])

    def _preflight(self, active: Path, stage: Path, operation: str) -> None:
        previous = self._current()
        self.systemctl(["/usr/bin/systemctl", "--user", "is-active", _SERVICE])
        _write_new(active, operation.encode())
        created = False
        try:
            stage.mkdir(mode=0o700)
            created = True
            _write_new(stage / "previous", previous.encode())
        except BaseException:
            if created:
                (stage / "previous").unlink(missing_ok=True)
                stage.rmdir()
            active.unlink()
            raise

    def _install(self, stage: Path, digest: str) -> None:
        bundle = _read(stage / "bundle.pyz", _CAP)
        if not bundle or hashlib.sha256(bundle).hexdigest() != digest:
            raise ValueError("bundle digest changed")
        if _read(stage / "previous", 64).decode() != self._current():
            raise ValueError("release changed after preflight")
        release = self.root / "releases" / f"{digest}.pyz"
        if release.exists():
            if hashlib.sha256(_read(release, _CAP)).hexdigest() != digest:
                raise ValueError("release digest changed")
        else:
            _write_new(release, bundle)
        self._switch(digest, stage)


def main() -> int:
    try:
        if len(sys.argv) != 4:
            return 2
        root = Path.home() / ".solus" / "companion-deploy"
        _private_dir(root.parent)
        RemoteDeployment(root).run(*sys.argv[1:])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 1  # Never disclose target config, credential paths or subprocess output.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
