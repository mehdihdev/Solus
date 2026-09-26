"""Inactive QA helper: policy, durable audit, and one-shot HTTP decisions."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from scripts.qa_approver import QAApprover


def card(**changes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "confirmation_id": str(uuid4()),
        "tool": "flash_device",
        "args": {
            "target": "usb:fixture-bare-mcu",
            "artifact": "probe.hex",
            "sha256": "a" * 64,
            "size": 42,
        },
        "summary": "Erase existing firmware and write the probe",
        "preview": [],
    }
    result.update(changes)
    return result


async def trusted(project: str, event: dict[str, Any]) -> bool:
    return True


def helper(tmp_path: Path, client: httpx.AsyncClient, **changes: Any) -> QAApprover:
    options: dict[str, Any] = dict(
        app_env="dev",
        usb_serial="fixture-bare-mcu",
        client=client,
        audit_path=tmp_path / "QA_APPROVALS_SOLUSDEV-262.md",
        verify_stored_action=trusted,
    )
    options.update(changes)
    return QAApprover(**options)


@pytest.mark.parametrize("env", ["production", "test", "staging", "DEV", "", None])
async def test_dev_only(tmp_path: Path, env: str | None) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            helper(tmp_path, client, app_env=env)


@pytest.mark.parametrize("serial", ["", " ", "usb:fixture", "a,b", "a/b", None])
async def test_exact_one_serial_required(tmp_path: Path, serial: str | None) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            helper(tmp_path, client, usb_serial=serial)


@pytest.mark.parametrize(
    "change",
    [
        {"tool": "move_joint"},
        {"tool": "onshape.update_feature"},
        {"tool": "unknown"},
        {"confirmation_id": "not-a-uuid"},
        {"args": {**card()["args"], "target": "usb:fixture-driver"}},
        {"args": {"target": "usb:fixture-driver"}},
        {"args": {"target": "/dev/ttyACM0"}},
        {"args": {}},
        {"args": {**card()["args"], "command": "move"}},
        {"args": {**card()["args"], "size": True}},
        {"args": {**card()["args"], "size": 0}},
        {"args": {**card()["args"], "sha256": "not-a-digest"}},
        {"args": {**card()["args"], "artifact": ""}},
    ],
)
async def test_disallowed_left_pending_and_recorded(tmp_path: Path, change: dict[str, Any]) -> None:
    def no_http(request: httpx.Request) -> httpx.Response:
        pytest.fail("Policy refusal must leave gate pending")

    async with httpx.AsyncClient(transport=httpx.MockTransport(no_http)) as client:
        approver = helper(tmp_path, client)
        assert await approver.approve(str(uuid4()), card(**change)) is False
    assert "left_unapproved" in approver.audit_path.read_text()


async def test_durable_before_post_and_never_repeat(tmp_path: Path) -> None:
    calls = []
    audit = tmp_path / "QA_APPROVALS_SOLUSDEV-262.md"
    event = card()
    audit.write_text("# Fixture approval journal\n")

    def respond(request: httpx.Request) -> httpx.Response:
        assert event["confirmation_id"] in audit.read_text()
        assert "approval_attempt" in audit.read_text()
        assert request.content == b'{"decision":"approve"}'
        calls.append(request)
        return httpx.Response(200, json={"data": {"ok": True}})

    async with httpx.AsyncClient(
        base_url="http://localhost", transport=httpx.MockTransport(respond)
    ) as client:
        approver = helper(tmp_path, client)
        project = str(uuid4())
        assert await approver.approve(project, event)
        assert not await approver.approve(project, event)
        assert not await helper(tmp_path, client).approve(project, event)
    assert len(calls) == 1


@pytest.mark.parametrize("outcome", ["refused", "timeout", "http_error"])
async def test_uncertain_or_refused_is_not_success_or_retried(tmp_path: Path, outcome: str) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if outcome == "timeout":
            raise httpx.ReadTimeout("unknown outcome")
        return httpx.Response(503 if outcome == "http_error" else 200, json={"data": {"ok": False}})

    async with httpx.AsyncClient(
        base_url="http://localhost", transport=httpx.MockTransport(respond)
    ) as client:
        approver = helper(tmp_path, client)
        event, project = card(), str(uuid4())
        assert not await approver.approve(project, event)
        assert not await approver.approve(project, event)
    assert len(calls) == 1


async def test_unregistered_or_unbound_action_is_not_approved(tmp_path: Path) -> None:
    async def untrusted(project: str, event: dict[str, Any]) -> bool:
        return False

    async with httpx.AsyncClient() as client:
        approver = helper(tmp_path, client, verify_stored_action=untrusted)
        assert not await approver.approve(str(uuid4()), card())


async def test_audit_failure_prevents_http(tmp_path: Path) -> None:
    async with httpx.AsyncClient() as client:
        approver = helper(tmp_path, client, audit_path=tmp_path / "missing" / "log.md")
        with pytest.raises(OSError):
            await approver.approve(str(uuid4()), card())


@pytest.mark.parametrize(
    "args",
    [
        {**card()["args"], "size": 32 * 1024 * 1024 + 1},
        {**card()["args"], "target": ["usb:fixture-bare-mcu", "usb:fixture-driver"]},
        {**card()["args"], "other_target": "usb:fixture-driver"},
    ],
)
async def test_ambiguous_or_oversized_card_stays_pending(
    tmp_path: Path, args: dict[str, Any]
) -> None:
    async with httpx.AsyncClient() as client:
        approver = helper(tmp_path, client)
        assert not await approver.approve(str(uuid4()), card(args=args))
        assert "left_unapproved" in approver.audit_path.read_text()


async def test_attestor_failure_is_recorded_without_deciding(tmp_path: Path) -> None:
    async def broken(project: str, event: dict[str, Any]) -> bool:
        raise RuntimeError("fixture registry unavailable")

    async with httpx.AsyncClient() as client:
        approver = helper(tmp_path, client, verify_stored_action=broken)
        assert not await approver.approve(str(uuid4()), card())
        assert "attestation_failed" in approver.audit_path.read_text()


async def test_malformed_journal_fails_closed(tmp_path: Path) -> None:
    async with httpx.AsyncClient() as client:
        approver = helper(tmp_path, client)
        approver.audit_path.write_text("- {broken\n")
        with pytest.raises(ValueError):
            await approver.approve(str(uuid4()), card())


async def test_omitted_args_is_logged_and_left_pending(tmp_path: Path) -> None:
    event = card()
    del event["args"]
    async with httpx.AsyncClient() as client:
        approver = helper(tmp_path, client)
        assert not await approver.approve(str(uuid4()), event)
        assert "left_unapproved" in approver.audit_path.read_text()


@pytest.mark.parametrize("alias", ["hex", "upper", "braced"])
@pytest.mark.parametrize("alias_first", [False, True])
async def test_uuid_alias_cannot_repeat_uncertain_decision(
    tmp_path: Path,
    alias: str,
    alias_first: bool,
) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("unknown outcome")

    async with httpx.AsyncClient(
        base_url="http://localhost", transport=httpx.MockTransport(respond)
    ) as client:
        approver = helper(tmp_path, client)
        event, project = card(), str(uuid4())
        original = event["confirmation_id"]
        alternate = {
            "hex": original.replace("-", ""),
            "upper": original.upper(),
            "braced": "{" + original + "}",
        }[alias]
        event["confirmation_id"] = alternate if alias_first else original
        assert not await approver.approve(project, event)
        event["confirmation_id"] = original if alias_first else alternate
        assert not await helper(tmp_path, client).approve(project, event)
    assert len(calls) == 1
