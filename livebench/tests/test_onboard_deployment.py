"""Provisioned onboard deployment fixtures; no SSH or live hardware is contacted."""

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from livebench.deploy.companion import CompanionDeployer, CompanionTarget


def target() -> CompanionTarget:
    return CompanionTarget(uuid.uuid4(), 1, "robot.local", "robot", "fixture-companion")


class Fixture:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail = ""
        self.allowed = True
        self.joined = True

    async def execute(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(argv)
        if self.fail and self.fail in argv:
            return 1, "private remote configuration must not escape"
        return 0, ""

    async def approve(self, _event: object) -> bool:
        return self.allowed

    async def revalidate(self, _target: CompanionTarget, _digest: str) -> bool:
        return self.allowed

    async def handshake(self, instance: str, digest: str) -> bool:
        assert instance == "fixture-companion" and len(digest) == 64
        return self.joined


def deployer(tmp_path: Path, fixture: Fixture) -> CompanionDeployer:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fixture host pin")
    return CompanionDeployer(known_hosts=known_hosts, execute=fixture.execute)


async def test_review_install_start_handshake_share_the_real_runner(tmp_path: Path) -> None:
    fixture = Fixture()
    runner = deployer(tmp_path, fixture)
    plan = runner.prepare(target(), b"trusted offline companion zipapp")
    assert plan.sha256 == hashlib.sha256(plan.bundle).hexdigest()
    assert fixture.calls == []
    result = await runner.apply(
        plan, approval=fixture.approve, revalidate=fixture.revalidate, handshake=fixture.handshake
    )
    assert result.status == "succeeded" and result.remote_state == "running"
    stages = [argv[-3] for argv in fixture.calls if argv[0] == "/usr/bin/ssh"]
    assert stages == ["preflight", "install", "start", "cleanup"]
    assert sum(argv[0] == "/usr/bin/scp" for argv in fixture.calls) == 1
    assert all("StrictHostKeyChecking=yes" in argv for argv in fixture.calls)


async def test_denied_review_does_not_contact_target(tmp_path: Path) -> None:
    fixture = Fixture()
    fixture.allowed = False
    runner = deployer(tmp_path, fixture)
    result = await runner.apply(
        runner.prepare(target(), b"bundle"),
        approval=fixture.approve,
        revalidate=fixture.revalidate,
        handshake=fixture.handshake,
    )
    assert result.status == "refused" and fixture.calls == []


@pytest.mark.parametrize("phase", ["preflight", "install", "start"])
async def test_stage_failure_is_honest_and_does_not_leak_output(tmp_path: Path, phase: str) -> None:
    fixture = Fixture()
    fixture.fail = phase
    runner = deployer(tmp_path, fixture)
    result = await runner.apply(
        runner.prepare(target(), b"bundle"),
        approval=fixture.approve,
        revalidate=fixture.revalidate,
        handshake=fixture.handshake,
    )
    assert result.status == "failed" and result.error_code == phase + "_failed"
    assert "private" not in repr(result)
    if phase != "preflight":
        assert any("cleanup" in argv for argv in fixture.calls)


async def test_failed_handshake_rolls_back_and_cleans_staging(tmp_path: Path) -> None:
    fixture = Fixture()
    fixture.joined = False
    runner = deployer(tmp_path, fixture)
    result = await runner.apply(
        runner.prepare(target(), b"bundle"),
        approval=fixture.approve,
        revalidate=fixture.revalidate,
        handshake=fixture.handshake,
    )
    assert result.error_code == "handshake_failed"
    assert result.remote_state == "rolled_back"
    assert [argv[-3] for argv in fixture.calls if argv[0] == "/usr/bin/ssh"][-2:] == [
        "rollback",
        "cleanup",
    ]


@pytest.mark.parametrize("host", ["-oProxyCommand=evil", "robot;id", "robot\nother", "../evil"])
def test_target_rejects_shell_and_option_injection(host: str) -> None:
    with pytest.raises(ValueError):
        CompanionTarget(uuid.uuid4(), 1, host, "robot", "instance")


async def test_target_revocation_after_review_refuses_without_io(tmp_path: Path) -> None:
    fixture = Fixture()
    runner = deployer(tmp_path, fixture)

    async def revoked(_target: CompanionTarget, _digest: str) -> bool:
        return False

    result = await runner.apply(
        runner.prepare(target(), b"bundle"),
        approval=fixture.approve,
        revalidate=revoked,
        handshake=fixture.handshake,
    )
    assert result.error_code == "plan_changed" and fixture.calls == []


def test_remote_helper_installs_exact_bytes_and_rolls_back(tmp_path: Path) -> None:
    from livebench.deploy.companion_remote import RemoteDeployment

    root = tmp_path / "companion-deploy"
    root.mkdir(mode=0o700)
    (root / "provisioned.json").write_text(json.dumps({"format": 1}))
    releases = root / "releases"
    releases.mkdir(mode=0o700)
    old = releases / (hashlib.sha256(b"previous").hexdigest() + ".pyz")
    old.write_bytes(b"previous")
    (root / "current.pyz").symlink_to(old)
    commands: list[list[str]] = []

    def systemctl(argv: list[str]) -> None:
        commands.append(argv)

    helper = RemoteDeployment(root, systemctl)
    op = str(uuid.uuid4())
    bundle = b"offline bundle"
    digest = hashlib.sha256(bundle).hexdigest()
    helper.run("preflight", op, digest)
    (root / "staging" / op / "bundle.pyz").write_bytes(bundle)
    helper.run("install", op, digest)
    assert (root / "current.pyz").read_bytes() == bundle
    helper.run("start", op, digest)
    helper.run("rollback", op, digest)
    assert (root / "current.pyz").read_bytes() == b"previous"
    helper.run("cleanup", op, digest)
    assert not (root / "staging" / op).exists()
    assert all(argv[0] == "/usr/bin/systemctl" for argv in commands)


def test_remote_helper_refuses_unprovisioned_target(tmp_path: Path) -> None:
    from livebench.deploy.companion_remote import RemoteDeployment

    with pytest.raises((ValueError, OSError)):
        RemoteDeployment(tmp_path, lambda _: None).run("preflight", str(uuid.uuid4()), "a" * 64)


def test_changed_known_hosts_is_stale_before_upload(tmp_path: Path) -> None:
    import asyncio

    fixture = Fixture()
    runner = deployer(tmp_path, fixture)
    plan = runner.prepare(target(), b"bundle")
    runner.known_hosts.write_text("changed host key authority")
    result = asyncio.run(
        runner.apply(
            plan,
            approval=fixture.approve,
            revalidate=fixture.revalidate,
            handshake=fixture.handshake,
        )
    )
    assert result.error_code == "plan_changed" and fixture.calls == []


@pytest.mark.parametrize("failure", ["digest", "symlink", "other_operation"])
def test_remote_helper_refuses_changed_bundle_and_competing_operation(
    tmp_path: Path, failure: str
) -> None:
    from livebench.deploy.companion_remote import RemoteDeployment

    root = tmp_path / "deploy"
    root.mkdir(mode=0o700)
    (root / "provisioned.json").write_text('{"format":1}')
    (root / "releases").mkdir(mode=0o700)
    old = root / "releases" / (hashlib.sha256(b"old").hexdigest() + ".pyz")
    old.write_bytes(b"old")
    (root / "current.pyz").symlink_to(old)
    helper = RemoteDeployment(root, lambda _: None)
    operation = str(uuid.uuid4())
    digest = hashlib.sha256(b"reviewed").hexdigest()
    helper.run("preflight", operation, digest)
    bundle = root / "staging" / operation / "bundle.pyz"
    if failure == "symlink":
        bundle.symlink_to(old)
    else:
        bundle.write_bytes(b"changed")
    with pytest.raises((OSError, ValueError)):
        if failure == "other_operation":
            helper.run("preflight", str(uuid.uuid4()), digest)
        else:
            helper.run("install", operation, digest)
    assert (root / "current.pyz").read_bytes() == b"old"
    helper.run("rollback", operation, digest)
    assert (root / "current.pyz").read_bytes() == b"old"
    helper.run("cleanup", operation, digest)


async def test_recovery_refuses_changed_host_key_authority(tmp_path: Path) -> None:
    fixture = Fixture()
    runner = deployer(tmp_path, fixture)
    plan = runner.prepare(target(), b"bundle")
    runner.known_hosts.write_text("replaced authority")
    result = await runner.recover(plan, approval=fixture.approve, revalidate=fixture.revalidate)
    assert result.error_code == "recovery_refused" and fixture.calls == []


async def test_cleanup_failure_is_not_claimed_success(tmp_path: Path) -> None:
    fixture = Fixture()
    fixture.fail = "cleanup"
    runner = deployer(tmp_path, fixture)
    result = await runner.apply(
        runner.prepare(target(), b"bundle"),
        approval=fixture.approve,
        revalidate=fixture.revalidate,
        handshake=fixture.handshake,
    )
    assert result.status == "failed" and result.remote_state == "running"
    assert result.error_code == "cleanup_failed"


async def test_handshake_cancellation_rolls_back_and_cleans(tmp_path: Path) -> None:
    import asyncio

    fixture = Fixture()
    runner = deployer(tmp_path, fixture)

    async def cancelled(_instance: str, _digest: str) -> bool:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await runner.apply(
            runner.prepare(target(), b"bundle"),
            approval=fixture.approve,
            revalidate=fixture.revalidate,
            handshake=cancelled,
        )
    assert any("rollback" in call for call in fixture.calls)
    assert any("cleanup" in call for call in fixture.calls)


async def test_remote_timeout_is_bounded_and_output_free(tmp_path: Path) -> None:
    fixture = Fixture()
    runner = deployer(tmp_path, fixture)

    async def timeout(_argv: list[str]) -> tuple[int, str]:
        raise TimeoutError("private remote output")

    runner.execute = timeout
    result = await runner.apply(
        runner.prepare(target(), b"bundle"),
        approval=fixture.approve,
        revalidate=fixture.revalidate,
        handshake=fixture.handshake,
    )
    assert result.error_code == "preflight_failed" and "private" not in repr(result)


@pytest.mark.parametrize("hostname", ["pi-fixture.local", "jetson-fixture.local"])
@pytest.mark.parametrize("lost_preflight", [False, True])
async def test_runner_and_installer_interoperate_on_provisioned_machine_twins(
    tmp_path: Path, hostname: str, lost_preflight: bool
) -> None:
    from livebench.deploy.companion_remote import RemoteDeployment

    root = tmp_path / ".solus" / "companion-deploy"
    root.mkdir(mode=0o700, parents=True)
    (root / "provisioned.json").write_text('{"format":1}')
    (root / "releases").mkdir(mode=0o700)
    previous = root / "releases" / (hashlib.sha256(b"old companion").hexdigest() + ".pyz")
    previous.write_bytes(b"old companion")
    (root / "current.pyz").symlink_to(previous)
    fixture = Fixture()
    helper = RemoteDeployment(root, lambda _: None)
    runner = deployer(tmp_path, fixture)
    new_bundle = b"fixture offline companion revision"

    async def transport(argv: list[str]) -> tuple[int, str]:
        fixture.calls.append(argv)
        if argv[0] == "/usr/bin/ssh":
            helper.run(*argv[-3:])
            if lost_preflight and "preflight" in argv:
                raise TimeoutError
        else:
            assert argv[0] == "/usr/bin/scp"
            remote = argv[-1].split(":", 1)[1]
            (tmp_path / remote).write_bytes(Path(argv[-2]).read_bytes())
        return 0, ""

    async def authenticated_handshake(instance: str, digest: str) -> bool:
        assert instance == "fixture-companion"
        installed = (root / "current.pyz").read_bytes()
        return installed == new_bundle and hashlib.sha256(installed).hexdigest() == digest

    runner.execute = transport
    machine = CompanionTarget(uuid.uuid4(), 1, hostname, "robot", "fixture-companion")
    result = await runner.apply(
        runner.prepare(machine, new_bundle),
        approval=fixture.approve,
        revalidate=fixture.revalidate,
        handshake=authenticated_handshake,
    )
    assert result.status == ("failed" if lost_preflight else "succeeded")
    assert (root / "current.pyz").read_bytes() == (
        b"old companion" if lost_preflight else new_bundle
    )
    assert list((root / "staging").iterdir()) == []
    assert not (root / "active").exists()


async def test_preflight_lost_reply_attempts_exact_operation_cleanup(tmp_path: Path) -> None:
    fixture = Fixture()
    runner = deployer(tmp_path, fixture)

    async def lost_reply(argv: list[str]) -> tuple[int, str]:
        fixture.calls.append(argv)
        if "preflight" in argv:
            raise TimeoutError
        return 0, ""

    runner.execute = lost_reply
    plan = runner.prepare(target(), b"bundle")
    result = await runner.apply(
        plan, approval=fixture.approve, revalidate=fixture.revalidate, handshake=fixture.handshake
    )
    assert result.error_code == "preflight_failed"
    assert fixture.calls[-1][-3:] == ["cleanup", str(plan.id), plan.sha256]


async def test_failed_rollback_retains_recovery_journal_and_lease(tmp_path: Path) -> None:
    fixture = Fixture()
    fixture.fail = "rollback"
    fixture.joined = False
    runner = deployer(tmp_path, fixture)
    result = await runner.apply(
        runner.prepare(target(), b"bundle"),
        approval=fixture.approve,
        revalidate=fixture.revalidate,
        handshake=fixture.handshake,
    )
    assert result.remote_state == "unknown"
    assert not any("cleanup" in call for call in fixture.calls)


@pytest.mark.parametrize("allowed", [False, True])
async def test_explicit_recovery_requires_review_before_restore(
    tmp_path: Path, allowed: bool
) -> None:
    fixture = Fixture()
    fixture.allowed = allowed
    runner = deployer(tmp_path, fixture)
    result = await runner.recover(
        runner.prepare(target(), b"bundle"), approval=fixture.approve, revalidate=fixture.revalidate
    )
    if allowed:
        assert result.remote_state == "rolled_back"
        assert [call[-3] for call in fixture.calls] == ["rollback", "cleanup"]
    else:
        assert result.error_code == "recovery_refused" and fixture.calls == []
