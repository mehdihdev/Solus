"""Confirmed deployment to pre-enrolled Linux targets; never performs enrollment.

The desktop deployment adapter resolves project-owned targets/trusted offline zipapp
artifacts and provides the central approval, scope revalidation and authenticated
bridge-handshake callbacks. Neither SSH stdout nor credentials enter a result.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from solus_api.hardware.companion_deployment import DeploymentOutcome, DeploymentTargetSnapshot

from solus_api.contracts.action_gate import DiffRow, ToolConfirmationEvent

from livebench.deploy.flash import Approval
from livebench.deploy.fs import ExecFn, SshFilesystem

_HELPER = "/usr/local/libexec/solus-companion-deploy.py"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z")
MAX_BUNDLE_BYTES = 32 * 1024 * 1024


async def _run(argv: list[str]) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        return await asyncio.wait_for(process.wait(), 55), ""
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise


@dataclass(frozen=True)
class CompanionTarget:
    id: uuid.UUID
    version: int
    host: str
    user: str
    companion_instance_id: str

    def __post_init__(self) -> None:
        if (
            not _HOST.fullmatch(self.host)
            or ".." in self.host
            or not _NAME.fullmatch(self.user)
            or not _NAME.fullmatch(self.companion_instance_id)
            or self.version < 1
            or not isinstance(self.id, uuid.UUID)
        ):
            raise ValueError("invalid provisioned deployment target")


@dataclass(frozen=True)
class CompanionPlan:
    id: uuid.UUID
    target: CompanionTarget
    bundle: bytes
    sha256: str
    host_keys_sha256: str


@dataclass(frozen=True)
class CompanionResult:
    status: Literal["succeeded", "failed", "refused"]
    remote_state: Literal["unchanged", "running", "rolled_back", "unknown"]
    artifact_sha256: str
    error_code: str | None = None


Revalidate = Callable[[CompanionTarget, str], Awaitable[bool]]
Handshake = Callable[[str, str], Awaitable[bool]]


class CompanionDeployer:
    def __init__(self, *, known_hosts: Path, execute: ExecFn = _run):
        if not known_hosts.is_absolute() or not known_hosts.is_file():
            raise ValueError("provisioned absolute known-hosts file required")
        self.known_hosts, self.execute = known_hosts, execute
        self._host_keys = known_hosts.read_bytes()
        if not 0 < len(self._host_keys) <= 1024 * 1024:
            raise ValueError("invalid known-hosts file size")

    def prepare(self, target: CompanionTarget, bundle: bytes) -> CompanionPlan:
        if not isinstance(bundle, bytes) or not 0 < len(bundle) <= MAX_BUNDLE_BYTES:
            raise ValueError("invalid offline bundle size")
        return CompanionPlan(
            uuid.uuid4(),
            target,
            bundle,
            hashlib.sha256(bundle).hexdigest(),
            hashlib.sha256(self._host_keys).hexdigest(),
        )

    @staticmethod
    def preview(plan: CompanionPlan) -> ToolConfirmationEvent:
        return ToolConfirmationEvent(
            confirmation_id=str(plan.id),
            tool="hardware.deploy_companion",
            args={"plan_id": str(plan.id)},
            summary="Install and restart the provisioned onboard companion",
            preview=[
                DiffRow(
                    label="target", before=None, after=f"{plan.target.user}@{plan.target.host}"
                ),
                DiffRow(label="bundle SHA256", before=None, after=plan.sha256),
                DiffRow(
                    label="operation",
                    before=None,
                    after="preflight → install → restart → authenticated handshake",
                ),
            ],
        )

    async def _execute(self, argv: list[str]) -> tuple[int, str]:
        with TemporaryDirectory(prefix="solus-host-keys-") as directory:
            pinned = Path(directory) / "known_hosts"
            pinned.write_bytes(self._host_keys)
            return await self._execute_pinned(argv, pinned)

    async def _execute_pinned(self, argv: list[str], pinned: Path) -> tuple[int, str]:
        # Disable user SSH config and pin host-key authority for BOTH ssh and scp.
        options = [
            "-F",
            "/dev/null",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={pinned}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ClearAllForwardings=yes",
        ]
        return await asyncio.wait_for(self.execute([argv[0], *options, *argv[1:]]), 60)

    async def _stage(self, plan: CompanionPlan, phase: str) -> bool:
        code, _ = await self._execute(
            [
                "/usr/bin/ssh",
                "-T",
                "-o",
                "BatchMode=yes",
                "--",
                f"{plan.target.user}@{plan.target.host}",
                "/usr/bin/python3",
                _HELPER,
                phase,
                str(plan.id),
                plan.sha256,
            ]
        )
        return code == 0

    async def apply(
        self,
        plan: CompanionPlan,
        *,
        approval: Approval,
        revalidate: Revalidate,
        handshake: Handshake | None = None,
        prepare_handshake: Callable[[], Handshake] | None = None,
    ) -> CompanionResult:
        if not await approval(self.preview(plan)):
            return CompanionResult("refused", "unchanged", plan.sha256, "approval_refused")
        if not self._unchanged(plan) or not await revalidate(plan.target, plan.sha256):
            return CompanionResult("refused", "unchanged", plan.sha256, "plan_changed")
        if (handshake is None) == (prepare_handshake is None):
            raise ValueError("exactly one handshake capability required")
        factory = prepare_handshake or (lambda: cast(Handshake, handshake))
        return await self._deploy(plan, revalidate, factory)

    def _unchanged(self, plan: CompanionPlan) -> bool:
        try:
            return (
                hashlib.sha256(plan.bundle).hexdigest() == plan.sha256
                and hashlib.sha256(self.known_hosts.read_bytes()).hexdigest()
                == plan.host_keys_sha256
            )
        except OSError:
            return False

    async def _best_stage(self, plan: CompanionPlan, phase: str) -> bool:
        try:
            return await self._stage(plan, phase)
        except (OSError, RuntimeError, TimeoutError):
            return False

    async def _upload(self, plan: CompanionPlan) -> None:
        with TemporaryDirectory(prefix="solus-companion-") as directory:
            path = Path(directory) / "bundle.pyz"
            path.write_bytes(plan.bundle)
            fs = SshFilesystem(
                host=plan.target.host,
                user=plan.target.user,
                scp_binary="/usr/bin/scp",
                execute=self._execute,
            )
            await fs.push(path, f".solus/companion-deploy/staging/{plan.id}/bundle.pyz")

    async def _restore(
        self, plan: CompanionPlan, installed: bool
    ) -> Literal["unchanged", "rolled_back", "unknown"]:
        if not installed:
            return "unchanged"
        return "rolled_back" if await self._best_stage(plan, "rollback") else "unknown"

    async def _cancel(self, plan: CompanionPlan, installed: bool) -> None:
        if await self._restore(plan, installed) != "unknown":
            await self._best_stage(plan, "cleanup")

    async def _finish(
        self, plan: CompanionPlan, result: CompanionResult, staged: bool
    ) -> CompanionResult:
        if result.remote_state == "unknown":
            return result  # Retain lease + rollback journal for explicit recovery.
        if staged and not await self._best_stage(plan, "cleanup"):
            return CompanionResult("failed", result.remote_state, plan.sha256, "cleanup_failed")
        return result

    async def recover(
        self, plan: CompanionPlan, *, approval: Approval, revalidate: Revalidate
    ) -> CompanionResult:
        """Explicitly retry restoration of this retained operation, never redeploy."""
        event = ToolConfirmationEvent(
            confirmation_id=str(uuid.uuid4()),
            tool="hardware.deploy_companion",
            args={"plan_id": str(plan.id), "recovery": True},
            summary="Restore the prior onboard companion release and clear its deployment lease",
            preview=[
                *self.preview(plan).preview[:2],
                DiffRow(label="operation", before=None, after="restore prior release → cleanup"),
            ],
        )
        if (
            not await approval(event)
            or not self._unchanged(plan)
            or not await revalidate(plan.target, plan.sha256)
        ):
            return CompanionResult("refused", "unknown", plan.sha256, "recovery_refused")
        restored = await self._best_stage(plan, "rollback")
        result = CompanionResult(
            "succeeded" if restored else "failed",
            "rolled_back" if restored else "unknown",
            plan.sha256,
            None if restored else "recovery_failed",
        )
        return await self._finish(plan, result, staged=True)

    async def _deploy(
        self,
        plan: CompanionPlan,
        revalidate: Revalidate,
        prepare_handshake: Callable[[], Handshake | None],
    ) -> CompanionResult:
        phase = "preflight"
        staged = installed = False
        try:
            if not await self._stage(plan, phase):
                await self._best_stage(plan, "cleanup")
                return CompanionResult("failed", "unchanged", plan.sha256, "preflight_failed")
            staged = True
            phase = "upload"
            await self._upload(plan)
            phase = "revalidation"
            if not await revalidate(plan.target, plan.sha256):
                raise RuntimeError()
            installed = True  # A failed install may have switched the release.
            for phase in ("install", "start"):
                verifier = prepare_handshake() if phase == "start" else None
                if not await self._stage(plan, phase):
                    raise RuntimeError()
            phase = "handshake"
            assert verifier is not None
            if not await asyncio.wait_for(
                verifier(plan.target.companion_instance_id, plan.sha256), 30
            ):
                raise RuntimeError()
            result = CompanionResult("succeeded", "running", plan.sha256)
        except asyncio.CancelledError:
            await self._cancel(plan, installed)
            raise
        except (OSError, RuntimeError, TimeoutError):
            state = await self._restore(plan, installed)
            result = CompanionResult("failed", state, plan.sha256, phase + "_failed")
            if phase == "preflight":
                # The target may have acquired the lease before SSH lost its reply.
                # Cleanup validates this exact operation and cannot release another.
                await self._best_stage(plan, "cleanup")
        return await self._finish(plan, result, staged)


class LocalCompanionDeploymentProvider:
    """Operator-installed, scoped adapter; never discovered or enabled automatically."""

    def __init__(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        runner: CompanionDeployer,
        targets: Mapping[uuid.UUID, CompanionTarget],
        allowed_artifacts: Mapping[uuid.UUID, str],
        handshake_factory: Callable[[str], Handshake],
    ):
        self.project_id, self.user_id = project_id, user_id
        self.runner, self.targets = runner, targets
        self.allowed_artifacts, self.handshake_factory = allowed_artifacts, handshake_factory

    async def resolve_target(self, target_id: uuid.UUID) -> DeploymentTargetSnapshot:
        from solus_api.hardware.companion_deployment import DeploymentTargetSnapshot

        target = self.targets[target_id]
        return DeploymentTargetSnapshot(
            id=target.id,
            version=target.version,
            host=target.host,
            user=target.user,
            companion_instance_id=target.companion_instance_id,
            host_keys_sha256=hashlib.sha256(self.runner._host_keys).hexdigest(),
        )

    def bundle_allowed(self, artifact_id: uuid.UUID, sha256: str) -> bool:
        return self.allowed_artifacts.get(artifact_id) == sha256

    async def validate(self, target: DeploymentTargetSnapshot) -> bool:
        try:
            return (
                await self.resolve_target(target.id) == target
                and hashlib.sha256(self.runner.known_hosts.read_bytes()).hexdigest()
                == target.host_keys_sha256
            )
        except (KeyError, OSError):
            return False

    async def execute(
        self,
        plan_id: uuid.UUID,
        artifact_id: uuid.UUID,
        target: DeploymentTargetSnapshot,
        bundle: bytes,
        sha256: str,
    ) -> DeploymentOutcome:
        from solus_api.hardware.companion_deployment import DeploymentOutcome

        plan = CompanionPlan(
            plan_id, self.targets[target.id], bundle, sha256, target.host_keys_sha256
        )

        async def central_invoke(event: ToolConfirmationEvent) -> bool:
            # This adapter is reachable only from the confirmation-required tool's
            # invoke. It accepts no user-supplied approval flag or callback.
            return event.args == {"plan_id": str(plan_id)}

        async def revalidate(_target: CompanionTarget, digest: str) -> bool:
            return await self.validate(target) and self.bundle_allowed(artifact_id, digest)

        result = await self.runner.apply(
            plan,
            approval=central_invoke,
            revalidate=revalidate,
            prepare_handshake=lambda: self.handshake_factory(sha256),
        )
        return DeploymentOutcome(
            status=result.status,
            remote_state=result.remote_state,
            artifact_sha256=result.artifact_sha256,
            error_code=result.error_code,
        )
