"""Real central confirmation for explicitly provisioned local deployment fixtures."""

import hashlib
import uuid
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from solus_api.agent.runtime import build_sol_registry
from solus_api.hardware.companion_deployment import PrepareCompanionDeployment


def test_deployment_requires_complete_central_confirmation_and_explicit_factory():
    registry = build_sol_registry(MagicMock(), uuid4(), companion_deployment_service=MagicMock())
    descriptor = next(t for t in registry.list() if t.name == "hardware.deploy_companion")
    assert descriptor.requires_confirmation
    assert "hardware.deploy_companion" not in {
        t.name for t in build_sol_registry(MagicMock(), uuid4()).list()
    }


def test_prepare_accepts_only_scoped_identifiers():
    body = {"target_id": str(uuid4()), "artifact_id": str(uuid4())}
    assert PrepareCompanionDeployment.model_validate(body)
    for key in ("host", "command", "path", "approval"):
        with pytest.raises(ValidationError):
            PrepareCompanionDeployment.model_validate(body | {key: "untrusted"})


async def setup(client, headers, db, app, tmp_path):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from conftest import me
    from livebench.deploy.companion import (
        CompanionDeployer,
        CompanionTarget,
        LocalCompanionDeploymentProvider,
    )
    from livebench.deploy.companion_remote import RemoteDeployment
    from solus_api.hardware.companion_deployment import (
        CompanionDeploymentService,
        FreshCompanionHandshake,
    )
    from solus_api.models import Domain, GraphEntity, SolusSection
    from solus_api.services.artifacts import create_artifact
    from solus_api.services.solus_config import add_artifact_entry
    from test_hardware_router import _hw_project

    project, team = await _hw_project(client, headers)
    user = await me(client, headers)
    pid, uid = uuid.UUID(project), uuid.UUID(user["id"])
    target = GraphEntity(
        project_id=pid,
        kind="hardware_brain",
        name="Provisioned fixture",
        domain=Domain.RUNTIME,
        origin="system",
        attrs={"brain_kind": "onboard"},
    )
    db.add(target)
    await db.flush()
    bundle = b"trusted synthetic offline companion bundle"
    artifact = await create_artifact(
        db,
        app.state.artifact_store,
        project_id=pid,
        created_by=uid,
        data=bundle,
        media_type="application/octet-stream",
        source_tool="companion.bundle",
        tool_call_id=None,
    )
    await add_artifact_entry(
        db,
        pid,
        SolusSection.DOCS,
        artifact_id=artifact.id,
        name="Offline companion bundle",
        created_by=uid,
    )
    root = tmp_path / ".solus" / "companion-deploy"
    root.mkdir(mode=0o700, parents=True)
    (root / "provisioned.json").write_text('{"format":1}')
    (root / "releases").mkdir(mode=0o700)
    old = root / "releases" / (hashlib.sha256(b"previous").hexdigest() + ".pyz")
    old.write_bytes(b"previous")
    (root / "current.pyz").symlink_to(old)
    helper = RemoteDeployment(root, lambda _: None)
    calls = []
    registry = MagicMock()
    registry.get.return_value = SimpleNamespace(session_id="old")
    handshake_control = {"connect": True}

    def reconnect(session_id):
        registry.get.return_value = SimpleNamespace(
            session_id=session_id,
            scope=(uid, uuid.UUID(team), pid),
            may_write=True,
            companion_instance_id="fixture-companion",
            connected_at=datetime.now(UTC),
            token_exp=datetime.now(UTC) + timedelta(seconds=60),
        )

    async def execute(argv):
        from pathlib import Path

        calls.append(argv)
        if argv[0] == "/usr/bin/ssh":
            helper.run(*argv[-3:])
            if "start" in argv and handshake_control["connect"]:
                reconnect("after-start")
        else:
            remote = argv[-1].split(":", 1)[1]
            (tmp_path / remote).write_bytes(Path(argv[-2]).read_bytes())
            reconnect("during-upload")
        return 0, ""

    host_keys = tmp_path / "known_hosts"
    host_keys.write_text("fixture host pin")
    runner = CompanionDeployer(known_hosts=host_keys, execute=execute)
    targets = {
        target.id: CompanionTarget(target.id, 1, "robot.local", "robot", "fixture-companion")
    }
    allowed = {artifact.id: hashlib.sha256(bundle).hexdigest()}

    def factory(session, project_id, user_id, store):
        provider = LocalCompanionDeploymentProvider(
            project_id=project_id,
            user_id=user_id,
            runner=runner,
            targets=targets if (project_id, user_id) == (pid, uid) else {},
            allowed_artifacts=allowed if (project_id, user_id) == (pid, uid) else {},
            handshake_factory=lambda sha256: FreshCompanionHandshake(
                registry,
                user_id=uid,
                team_id=uuid.UUID(team),
                project_id=pid,
                expected_sha256=sha256,
                timeout_seconds=0.01,
            ),
        )
        return CompanionDeploymentService(session, project_id, user_id, store, provider)

    app.state.companion_deployment_service_factory = factory
    await db.commit()
    return {
        "project": pid,
        "team": uuid.UUID(team),
        "user": uid,
        "target": target.id,
        "artifact": artifact.id,
        "targets": targets,
        "allowed": allowed,
        "calls": calls,
        "factory": factory,
        "root": root,
        "handshake_control": handshake_control,
    }


def url(f):
    return f"/api/v1/projects/{f['project']}/hardware/companion-deployments/prepare"


def body(f):
    return {"target_id": str(f["target"]), "artifact_id": str(f["artifact"])}


@pytest.mark.parametrize("decision", ["approve", "reject", "changed", "stale_session"])
async def test_actual_confirmation_decide_runs_real_installer_only_after_approval(
    client, alice_headers, db, app, tmp_path, engine, decision
):
    from solus_api.agent.confirmations import request_confirmation
    from solus_api.agent.tools.shapes import ToolCall
    from solus_api.models import ToolConfirmation
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    f = await setup(client, alice_headers, db, app, tmp_path)
    response = await client.post(url(f), headers=alice_headers, json=body(f))
    assert response.status_code == 201, response.text
    plan = response.json()["data"]["plan_id"]
    service = f["factory"](db, f["project"], f["user"], app.state.artifact_store)
    registry = build_sol_registry(
        async_sessionmaker(engine, expire_on_commit=False),
        f["project"],
        user_id=f["user"],
        companion_deployment_service=service,
    )
    parked = await request_confirmation(
        db,
        registry,
        ToolCall(tool="hardware.deploy_companion", args={"plan_id": plan}),
        project_id=f["project"],
        team_id=f["team"],
        user_id=f["user"],
    )
    assert parked is not None and parked.confirmation_id
    await db.commit()
    confirmation = await db.scalar(
        select(ToolConfirmation).where(ToolConfirmation.project_id == f["project"])
    )
    assert confirmation and any(row["label"] == "Bundle SHA256" for row in confirmation.preview)
    assert f["calls"] == []
    if decision == "changed":
        f["allowed"].clear()
    if decision == "stale_session":
        f["handshake_control"]["connect"] = False
    response = await client.post(
        f"/api/v1/projects/{f['project']}/sol/confirmations/{confirmation.id}",
        headers=alice_headers,
        json={"decision": "reject" if decision == "reject" else "approve"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["ok"] == (decision == "approve"), response.text
    assert bool(f["calls"]) == (decision in ("approve", "stale_session"))
    if decision == "stale_session":
        assert (await service.plan(uuid.UUID(plan))).attrs["outcome"][
            "remote_state"
        ] == "rolled_back"
    if decision == "approve":
        assert (await service.plan(uuid.UUID(plan))).attrs["status"] == "succeeded"
        assert (f["root"] / "current.pyz").read_bytes() != b"previous"
        with pytest.raises(Exception, match="already been attempted"):
            await service.checked(uuid.UUID(plan))


@pytest.mark.parametrize(
    "access,status", [("anonymous", 401), ("foreign", 404), ("unavailable", 503)]
)
async def test_prepare_auth_isolation_and_unavailable_default(
    client, alice_headers, bob_headers, db, app, tmp_path, access, status
):
    f = await setup(client, alice_headers, db, app, tmp_path)
    if access == "unavailable":
        del app.state.companion_deployment_service_factory
    headers = {} if access == "anonymous" else bob_headers if access == "foreign" else alice_headers
    response = await client.post(url(f), headers=headers, json=body(f))
    assert response.status_code == status, response.text
    assert f["calls"] == []


@pytest.mark.parametrize("field", ["target_id", "artifact_id"])
async def test_cross_project_references_cannot_create_plan(
    client, alice_headers, db, app, tmp_path, field
):
    first = await setup(client, alice_headers, db, app, tmp_path / "first")
    second = await setup(client, alice_headers, db, app, tmp_path / "second")
    app.state.companion_deployment_service_factory = first["factory"]
    payload = body(first)
    payload[field] = body(second)[field]
    response = await client.post(url(first), headers=alice_headers, json=payload)
    assert response.status_code == 404, response.text
    assert first["calls"] == second["calls"] == []


@pytest.mark.parametrize("access", ["viewer", "unverified", "forged_factory"])
async def test_prepare_rejects_insufficient_identity_and_forged_factory(
    client, alice_headers, bob_headers, db, app, tmp_path, access
):
    from conftest import ALICE, BOB, add_member, bearer, me

    f = await setup(client, alice_headers, db, app, tmp_path)
    headers = alice_headers
    expected = 403
    if access == "viewer":
        await me(client, bob_headers)
        await add_member(client, alice_headers, bob_headers, BOB, str(f["team"]), role="viewer")
        headers = bob_headers
    elif access == "unverified":
        headers = bearer(**ALICE, email_verified=False)
    else:
        other = f["factory"](db, uuid4(), f["user"], app.state.artifact_store)
        app.state.companion_deployment_service_factory = lambda *_args: other
        expected = 503
    response = await client.post(url(f), headers=headers, json=body(f))
    assert response.status_code == expected, response.text
    assert not f["calls"]


async def test_same_team_cannot_preview_or_decide_another_creators_plan(
    client, alice_headers, bob_headers, db, app, tmp_path, engine
):
    from conftest import BOB, add_member, me
    from solus_api.agent.confirmations import request_confirmation
    from solus_api.agent.tools.shapes import ToolCall
    from solus_api.core.errors import APIError
    from sqlalchemy.ext.asyncio import async_sessionmaker

    f = await setup(client, alice_headers, db, app, tmp_path)
    bob = await me(client, bob_headers)
    await add_member(client, alice_headers, bob_headers, BOB, str(f["team"]), role="member")
    response = await client.post(url(f), headers=alice_headers, json=body(f))
    plan_id = response.json()["data"]["plan_id"]
    service = f["factory"](db, f["project"], f["user"], app.state.artifact_store)
    registry = build_sol_registry(
        async_sessionmaker(engine, expire_on_commit=False),
        f["project"],
        user_id=f["user"],
        companion_deployment_service=service,
    )
    parked = await request_confirmation(
        db,
        registry,
        ToolCall(tool="hardware.deploy_companion", args={"plan_id": plan_id}),
        project_id=f["project"],
        team_id=f["team"],
        user_id=f["user"],
    )
    await db.commit()
    assert parked and parked.confirmation_id
    other = f["factory"](db, f["project"], uuid.UUID(bob["id"]), app.state.artifact_store)
    with pytest.raises(APIError) as error:
        await other.preview(uuid.UUID(plan_id))
    assert error.value.status_code == 404
    response = await client.post(
        f"/api/v1/projects/{f['project']}/sol/confirmations/{parked.confirmation_id}",
        headers=bob_headers,
        json={"decision": "approve"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["error"]["code"] == "not_found"
    assert not f["calls"]


@pytest.mark.parametrize("session_kind", ["old", "foreign", "expired", "new"])
async def test_real_bridge_handshake_requires_new_authorized_session(session_kind):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from solus_api.hardware.companion_deployment import FreshCompanionHandshake

    scope = (uuid4(), uuid4(), uuid4())
    registry = MagicMock()
    registry.get.return_value = SimpleNamespace(session_id="before")
    check = FreshCompanionHandshake(
        registry,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        expected_sha256="a" * 64,
        timeout_seconds=0.01,
    )
    registry.get.return_value = SimpleNamespace(
        session_id="before" if session_kind == "old" else "after",
        scope=(uuid4(), scope[1], scope[2]) if session_kind == "foreign" else scope,
        may_write=True,
        companion_instance_id="fixture-companion",
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC) + timedelta(seconds=-1 if session_kind == "expired" else 60),
    )
    assert await check("fixture-companion", "a" * 64) == (session_kind == "new")
