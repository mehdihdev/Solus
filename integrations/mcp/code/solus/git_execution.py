"""Pinned, bounded Git subprocesses and ordinary-repository safety checks."""

import hashlib
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MAX_OUTPUT = 256 * 1024
COMMAND_TIMEOUT = 10.0
SSH_COMMAND = (
    "/usr/bin/ssh -F /dev/null -oBatchMode=yes -oStrictHostKeyChecking=yes "
    "-oProxyCommand=none -oClearAllForwardings=yes -oPermitLocalCommand=no "
    "-oIdentityAgent=none -oIdentitiesOnly=yes"
)


class GitOperationError(ValueError):
    """Stable refusal; never contains Git stderr, configuration or credentials."""


def fingerprint(raw: bytes) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    return ":".join(digest[i : i + 16] for i in range(0, 64, 16))


def git_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),
        "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_LITERAL_PATHSPECS": "1",
    }


def pinned_binary(name: str) -> str:
    for base in (Path("/usr/bin"), Path("/bin")):
        candidate = base / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            actual = candidate.resolve()
            if actual.parent in (Path("/usr/bin"), Path("/bin")):
                return str(actual)
    raise GitOperationError("runtime_unavailable")


def bounded_read(path: Path, maximum: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise GitOperationError("unsupported_repository")
            data = handle.read(maximum + 1)
            if len(data) > maximum:
                raise GitOperationError("repository_too_large")
            return data
    except FileNotFoundError:
        return b""
    except OSError as exc:
        raise GitOperationError("unsupported_repository") from exc


class Repository:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.directory = self.root / ".git"
        self.used = 0
        self.identity = self._identity()
        self.binary = pinned_binary("git")
        self.validate()
        self.oid_length = (
            64 if self.run(["rev-parse", "--show-object-format"]).strip() == b"sha256" else 40
        )

    def _identity(self) -> tuple[int, ...]:
        if self.root.is_symlink() or self.root.resolve() != self.root.absolute():
            raise GitOperationError("unsupported_repository")
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise GitOperationError("unsupported_repository")
        a, b = self.root.stat(), self.directory.stat()
        return a.st_dev, a.st_ino, b.st_dev, b.st_ino

    def validate(self) -> None:
        if self._identity() != self.identity:
            raise GitOperationError("repository_changed")
        for name in (
            "commondir",
            "objects/info/alternates",
            "objects/info/http-alternates",
            "modules",
            "info/grafts",
            "info/attributes",
            "shallow",
        ):
            if (self.directory / name).exists():
                raise GitOperationError("unsupported_repository")
        self._validate_layout()
        raw_config = bounded_read(self.directory / "config", 65536)
        if re.search(rb"(?im)^\s*\[\s*include(?:if)?(?:\s|\])", raw_config):
            raise GitOperationError("unsafe_config")
        config = self.run(["config", "--local", "--no-includes", "--null", "--list"])
        for item in config.split(b"\0"):
            if not item:
                continue
            raw_key, _, value = item.partition(b"\n")
            key = raw_key.decode("utf-8", errors="strict").lower()
            permitted = (
                key
                in {
                    "core.repositoryformatversion",
                    "core.filemode",
                    "core.bare",
                    "core.logallrefupdates",
                    "core.ignorecase",
                    "core.precomposeunicode",
                    "core.symlinks",
                    "user.name",
                    "user.email",
                    "extensions.objectformat",
                }
                or re.fullmatch(r"remote\.[a-z0-9_-]+\.(url|fetch)", key)
                or re.fullmatch(r"branch\..+\.(remote|merge|vscode-merge-base)", key)
                or (
                    key == "pull.rebase" and value in (b"false", b"true", b"merges", b"interactive")
                )
            )
            if not permitted or (key == "core.bare" and value != b"false"):
                raise GitOperationError("unsafe_config")
        if self.run(["rev-parse", "--show-toplevel"]).strip() != os.fsencode(self.root):
            raise GitOperationError("unsupported_repository")

        self._validate_inventory()

    def _validate_layout(self) -> None:
        # Never follow planted symlinks, including refs/objects/config; bounded walk.
        count = 0
        for current, dirs, files in os.walk(self.directory, followlinks=False):
            for name in dirs + files:
                count += 1
                path = Path(current) / name
                if count > 20000:
                    raise GitOperationError("repository_too_large")
                if (
                    path.is_symlink()
                    or (path.is_file() is False and path.is_dir() is False)
                    or name.startswith("sharedindex.")
                ):
                    raise GitOperationError("unsupported_repository")

    def _validate_inventory(self) -> None:
        if (self.root / ".gitmodules").exists():
            raise GitOperationError("unsupported_repository")
        raw = self.run(["ls-files", "--stage", "-z"])
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            metadata, separator, encoded_path = entry.partition(b"\t")
            if not separator or metadata.split(b" ")[0] in (b"120000", b"160000", b"040000"):
                raise GitOperationError("unsupported_repository")
            try:
                path = encoded_path.decode("utf-8")
            except UnicodeError as exc:
                raise GitOperationError("unsupported_repository") from exc
            parts = path.split("/")
            if any(
                part in ("", ".", "..", ".git", ".gitattributes", ".gitmodules") for part in parts
            ):
                raise GitOperationError("unsupported_repository")
            current = self.root
            for part in parts:
                if (current / ".gitattributes").exists() or (
                    current / ".gitattributes"
                ).is_symlink():
                    raise GitOperationError("unsupported_repository")
                current /= part
                if current.is_symlink():
                    raise GitOperationError("unsupported_repository")

    def symbolic_ref(self) -> str:
        ref = self.run(["symbolic-ref", "--quiet", "HEAD"]).strip().decode("utf-8")
        if not ref.startswith("refs/heads/"):
            raise GitOperationError("detached_head")
        return ref

    def state_identity(self) -> dict[str, object]:
        return {
            "repository": self.identity,
            "branch": self.symbolic_ref(),
            "config": fingerprint(bounded_read(self.directory / "config", 65536)),
        }

    def run(self, args: list[str], *, allow_failure: bool = False, network: bool = False) -> bytes:
        env = git_environment()
        if network:
            if pinned_binary("ssh") != "/usr/bin/ssh":
                raise GitOperationError("unsupported_transport")
            env["GIT_SSH_COMMAND"] = SSH_COMMAND
        argv = [
            self.binary,
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-c",
            "tag.gpgsign=false",
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "core.pager=cat",
            "-c",
            "core.editor=false",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.ssh.allow=always",
            *args,
        ]
        output = bytearray()
        try:
            with subprocess.Popen(  # noqa: S603 — pinned Git binary, closed environment, owned argv
                argv,
                cwd=self.root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            ) as process:
                output = self._capture(process)
                if process.returncode and not allow_failure:
                    raise GitOperationError("git_failed")
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitOperationError("git_failed") from exc
        return bytes(output)

    def _capture(self, process: subprocess.Popen[bytes]) -> bytearray:
        output = bytearray()
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + COMMAND_TIMEOUT
            try:
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise GitOperationError("command_timeout")
                    for key, _ in selector.select(0.1):
                        data = os.read(key.fd, 8192)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        self.used += len(data)
                        if self.used > MAX_OUTPUT:
                            raise GitOperationError("output_too_large")
                        output.extend(data)
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except BaseException:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
        return output

    def head(self) -> str:
        value = self.run(["rev-parse", "--verify", "HEAD"]).strip().decode()
        self.check_oid(value)
        return value

    def check_oid(self, value: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{" + str(self.oid_length) + "}", value):
            raise GitOperationError("invalid_object_id")

    def index_fingerprint(self) -> str:
        return fingerprint(bounded_read(self.directory / "index", 32 * 1024 * 1024))

    def mutation_ready(self) -> None:
        self.validate()
        if any(path.name != "solus-operation.lock" for path in self.directory.rglob("*.lock")):
            raise GitOperationError("repository_busy")
        for name in (
            "index.lock",
            "HEAD.lock",
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
            "rebase-merge",
            "rebase-apply",
            "sequencer",
            "info/sparse-checkout",
        ):
            if (self.directory / name).exists():
                raise GitOperationError("repository_busy")
        if not self.run(["symbolic-ref", "--quiet", "--short", "HEAD"], allow_failure=True).strip():
            raise GitOperationError("detached_head")
        if self.run(["ls-files", "--unmerged"]):
            raise GitOperationError("unmerged_index")

    @contextmanager
    def locked(self) -> Iterator[None]:
        if os.name != "posix":
            raise GitOperationError("platform_unavailable")
        import fcntl

        fd = os.open(
            self.directory / "solus-operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise GitOperationError("repository_busy")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise GitOperationError("repository_busy") from exc
            self.mutation_ready()
            yield
        finally:
            os.close(fd)
