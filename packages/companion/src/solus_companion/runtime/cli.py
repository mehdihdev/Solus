"""`solus-companion runtime detect|status|provision|install-managed` —
mcp-fork-runtime.md §6. The only provisioning entry point.

stdout carries JSON Lines and nothing else (no argparse help/usage text ever
reaches it); human logs go to stderr. Exit codes: 0 ok · 1 partial · 2 failed ·
3 usage · 130 cancelled."""

import argparse
import logging
import os
import platform as platform_module
import signal
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import BinaryIO, Literal, NoReturn

from solus_companion.runtime.detect import Detector, HostView, assess, best_candidate
from solus_companion.runtime.errors import MESSAGES, Cancelled, ErrorCode, RuntimeSetupError
from solus_companion.runtime.forks import ForkInfo, python_forks
from solus_companion.runtime.managed import (
    Fetcher,
    ManagedInstaller,
    ManagedManifest,
    load_manifest,
    managed_interpreter,
    platform_key,
    urllib_fetch,
)
from solus_companion.runtime.ownership import OwnerOnly, owner_only_for
from solus_companion.runtime.probe import PROBE_SCRIPT
from solus_companion.runtime.proc import Runner, run_capped
from solus_companion.runtime.protocol import (
    DoneLine,
    Emitter,
    ErrorLine,
    ForkResultLine,
    StatusLine,
    clip,
)
from solus_companion.runtime.provision import BaseInterpreter, EnvBuilder
from solus_companion.runtime.roots import envs_root, python_root
from solus_companion.runtime.trust import evaluate_trust

__all__ = ["PROBE_SCRIPT", "CliDeps", "cancel_on_signals", "main"]

logger = logging.getLogger("solus.companion.runtime")

EXIT_OK, EXIT_PARTIAL, EXIT_FAILED, EXIT_USAGE, EXIT_CANCELLED = 0, 1, 2, 3, 130
INTEGRATIONS_ROOT_ENV = "SOLUS_COMPANION_INTEGRATIONS_ROOT"


class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="solus-companion runtime", add_help=False)
    common = _Parser(add_help=False)
    common.add_argument("--envs-root")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    for name in ("detect", "status", "install-managed"):
        sub.add_parser(name, parents=[common], add_help=False)
    provision = sub.add_parser("provision", parents=[common], add_help=False)
    which = provision.add_mutually_exclusive_group(required=True)
    which.add_argument("--fork", action="append")
    which.add_argument("--all", action="store_true")
    base = provision.add_mutually_exclusive_group()
    base.add_argument("--python")
    base.add_argument("--managed", action="store_true")
    return parser


def _default_integrations_root(env: dict[str, str]) -> Path | None:  # pragma: no cover
    configured = env.get(INTEGRATIONS_ROOT_ENV, "")
    if configured:
        return Path(configured)
    from solus_companion.config import default_integrations_root

    return default_integrations_root()


@dataclass(frozen=True)
class CliDeps:
    runner: Runner
    policy: OwnerOnly
    host: HostView
    fetcher: Fetcher
    manifest: Callable[[], ManagedManifest]
    integrations_root: Path | None
    asset_key: str | None

    @classmethod
    def current(cls) -> "CliDeps":  # pragma: no cover — wiring only, exercised end to end
        host = HostView.current()
        return cls(
            runner=run_capped,
            policy=owner_only_for(host.platform),
            host=host,
            fetcher=urllib_fetch,
            manifest=load_manifest,
            integrations_root=_default_integrations_root(dict(host.env)),
            asset_key=platform_key(host.platform, platform_module.machine()),
        )


def _raise_cancelled(signum: int, frame: FrameType | None) -> None:
    raise Cancelled()


@contextmanager
def cancel_on_signals() -> Iterator[None]:
    """SIGINT/SIGTERM (and CTRL_BREAK's SIGBREAK on Windows) raise `Cancelled`
    in the main thread; the in-flight child is killed by `run_capped` and the
    temp env removed by the builder's `finally`."""
    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):  # pragma: no cover — Windows only
        signals.append(signal.SIGBREAK)
    previous = {sig: signal.signal(sig, _raise_cancelled) for sig in signals}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _absolute(value: str, flag: str) -> Path:
    if not os.path.isabs(value):
        raise UsageError(f"{flag} must be an absolute path")
    return Path(value)


@dataclass
class Tally:
    ok: int = 0
    failed: int = 0
    skipped: int = 0

    def add(self, outcome: Literal["ok", "failed", "skipped"]) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)

    def done(self, outcome: Literal["ok", "partial", "failed", "cancelled"]) -> DoneLine:
        return DoneLine(outcome=outcome, ok=self.ok, failed=self.failed, skipped=self.skipped)


class RuntimeCommands:
    def __init__(self, deps: CliDeps, emitter: Emitter, envs: Path) -> None:
        self._deps = deps
        self._out = emitter
        self._envs = envs
        self._platform = deps.host.platform

    def _fail(self, code: ErrorCode, tally: "Tally | None" = None) -> int:
        self._out.emit(ErrorLine(error_code=code, message=MESSAGES[code]))
        self._out.emit((tally or Tally()).done("failed"))
        return EXIT_FAILED

    def fail_without_forks_tree(self) -> int:
        return self._fail("internal")

    def _detector(self) -> Detector:
        return Detector(self._deps.runner, self._deps.host, managed_root=python_root(self._envs))

    def detect(self) -> int:
        candidates = self._detector().detect()
        for candidate in candidates:
            self._out.emit(candidate.to_line())
        ok = sum(c.verdict.supported for c in candidates)
        if ok == 0:
            return self._fail("python_not_found", Tally(skipped=len(candidates)))
        done = DoneLine(outcome="ok", ok=ok, failed=0, skipped=len(candidates) - ok)
        self._out.emit(done)
        return EXIT_OK

    def status(self) -> int:
        root = self._deps.integrations_root
        if root is None:
            return self._fail("internal")
        counts = {"ready": 0, "needs_setup": 0, "unsupported_platform": 0}
        for fork in python_forks(root, self._platform):
            line = self._status_line(fork)
            counts[line.state] += 1
            self._out.emit(line)
        self._out.emit(DoneLine(
            outcome="ok", ok=counts["ready"], failed=counts["needs_setup"],
            skipped=counts["unsupported_platform"],
        ))  # fmt: skip
        return EXIT_OK

    def _status_line(self, fork: ForkInfo) -> StatusLine:
        if fork.unavailable is not None:
            return StatusLine(fork=fork.name, state="unsupported_platform", detail=None,
                              base_version=None, managed=False)  # fmt: skip
        trust = evaluate_trust(
            fork.name, fork.lock, self._envs, platform=self._platform, policy=self._deps.policy
        )
        if trust.stamp is None or not trust.ready:
            return StatusLine(fork=fork.name, state="needs_setup", detail=trust.detail,
                              base_version=None, managed=False)  # fmt: skip
        return StatusLine(fork=fork.name, state="ready", detail=None,
                          base_version=trust.stamp.base.version,
                          managed=trust.stamp.base.managed)  # fmt: skip

    def select_forks(self, names: list[str] | None) -> list[ForkInfo]:
        root = self._deps.integrations_root
        available = python_forks(root, self._platform) if root is not None else []
        if names is None:
            return available
        by_name = {fork.name: fork for fork in available}
        unknown = sorted(set(names) - set(by_name))
        if unknown:
            raise UsageError(f"unknown fork(s): {', '.join(n[:40] for n in unknown)}")
        return [by_name[name] for name in sorted(set(names))]

    def _base(self, python: Path | None, managed: bool) -> BaseInterpreter:
        if managed:
            release = python_root(self._envs) / self._deps.manifest().release
            path = managed_interpreter(release, self._platform)
            if not path.is_file():
                raise RuntimeSetupError("managed_not_installed")
            candidate = assess(str(path), "managed", self._deps.runner, self._deps.host)
        elif python is not None:
            candidate = assess(str(python), "path", self._deps.runner, self._deps.host)
        else:
            best = best_candidate(self._detector().detect())
            if best is None:
                raise RuntimeSetupError("python_not_found")
            candidate = best
        verdict = candidate.verdict
        if not verdict.supported or verdict.version is None:
            raise RuntimeSetupError(verdict.reason or "python_probe_failed")
        return BaseInterpreter(
            path=candidate.path, version=verdict.version, managed=candidate.source == "managed"
        )

    def provision(self, forks: list[ForkInfo], python: Path | None, managed: bool) -> int:
        tally = Tally()
        first_error: ErrorCode | None = None
        current: str | None = None
        try:
            base = self._base(python, managed)
            self._deps.policy.ensure(self._envs)
            builder = EnvBuilder(
                envs_root=self._envs, runner=self._deps.runner, policy=self._deps.policy,
                emit=self._out.emit, platform=self._platform, env_source=self._deps.host.env,
            )  # fmt: skip
            for fork in forks:
                current = fork.name
                outcome = builder.build(fork, base)
                current = None
                tally.add(outcome.outcome)
                first_error = first_error or outcome.error_code
                self._out.emit(ForkResultLine(
                    fork=outcome.fork, outcome=outcome.outcome,
                    error_code=outcome.error_code, message=outcome.message,
                ))  # fmt: skip
        except RuntimeSetupError as failure:
            return self._fail(failure.code, tally)
        except Cancelled:
            return self._cancelled(current, tally)
        return self._finish(tally, first_error)

    def _cancelled(self, fork: str | None, tally: "Tally") -> int:
        if fork is not None:
            tally.add("failed")
            self._out.emit(ForkResultLine(fork=fork, outcome="failed", error_code="cancelled",
                                          message=MESSAGES["cancelled"]))  # fmt: skip
        self._out.emit(tally.done("cancelled"))
        return EXIT_CANCELLED

    def _finish(self, tally: "Tally", first_error: ErrorCode | None) -> int:
        if tally.failed == 0:
            self._out.emit(tally.done("ok"))
            return EXIT_OK
        if tally.ok > 0:
            self._out.emit(tally.done("partial"))
            return EXIT_PARTIAL
        return self._fail(first_error or "internal", tally)

    def install_managed(self) -> int:
        installer = ManagedInstaller(
            python_root=python_root(self._envs), manifest=self._deps.manifest(),
            fetcher=self._deps.fetcher, policy=self._deps.policy, emit=self._out.emit,
            platform=self._platform, asset_key=self._deps.asset_key,
        )  # fmt: skip
        try:
            installer.install()
        except RuntimeSetupError as failure:
            self._out.emit(ErrorLine(error_code=failure.code, message=clip(failure.message)))
            self._out.emit(DoneLine(outcome="failed", ok=0, failed=1, skipped=0))
            return EXIT_FAILED
        except Cancelled:
            self._out.emit(DoneLine(outcome="cancelled", ok=0, failed=0, skipped=0))
            return EXIT_CANCELLED
        self._out.emit(DoneLine(outcome="ok", ok=1, failed=0, skipped=0))
        return EXIT_OK


def _resolve_envs(args: argparse.Namespace, host: HostView) -> Path:
    if args.envs_root is not None:
        return _absolute(args.envs_root, "--envs-root")
    try:
        return envs_root(host.platform, host.env, host.home)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


def _dispatch(args: argparse.Namespace, deps: CliDeps, emitter: Emitter) -> int:
    commands = RuntimeCommands(deps, emitter, _resolve_envs(args, deps.host))
    if args.command == "detect":
        return commands.detect()
    if args.command == "status":
        return commands.status()
    if args.command == "install-managed":
        with cancel_on_signals():
            return commands.install_managed()
    # provision: every usage check happens BEFORE anything is emitted or written.
    python = _absolute(args.python, "--python") if args.python is not None else None
    if deps.integrations_root is None:
        # No forks tree: never report "ok" for a run that could build nothing.
        return commands.fail_without_forks_tree()
    forks = commands.select_forks(None if args.all else args.fork)
    with cancel_on_signals():
        return commands.provision(forks, python, args.managed)


def main(
    argv: Sequence[str], *, deps: CliDeps | None = None, stdout: BinaryIO | None = None
) -> int:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    emitter = Emitter(stdout if stdout is not None else sys.stdout.buffer)
    try:
        args = build_parser().parse_args(list(argv))
        return _dispatch(args, deps or CliDeps.current(), emitter)
    except UsageError as exc:
        logger.error("usage error: %s", exc)
        return EXIT_USAGE
