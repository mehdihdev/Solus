# SOLUSDEV-203 (SOLX-04) — "SOL connects a missing integration" as a SOL
# action: three tools over the connector registry (discover → connect →
# verify). `connect` is the app's first REAL destructive registry tool, so
# this file also carries the route-level park→decide e2e the SOLX-01 review
# deferred here: a do-mode chat request parks the connect, approval executes
# it, and a same-project non-owner cannot decide it.
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.agent.connect_integration import (
    ConnectIntegrationDeps,
    build_integration_tools,
)
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.connectors.contracts import AccountInfo, AuthKind, Credentials
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.models import Source, SourceStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


if TYPE_CHECKING:
    from solus_api.agent.runtime import LlmRunner


def _runner(model: object) -> LlmRunner:
    """The shipped matrix routes a SOL turn to openai OR anthropic by tier
    (SOLUSDEV-252 S1), so the fake serves every provider the router may pick —
    these suites are about the reasoning loop, not about which model answers."""
    from solus_api.agent.runtime import LlmRunner

    return LlmRunner(adapters={"anthropic": model, "openai": model, "google": model})


class _ExportConnector:
    """A committed-export (AuthKind.NONE) connector double — connect completes
    on creation, like the EDA family."""

    auth_kind = AuthKind.NONE
    supports_token_connect = False
    config_fields: tuple[str, ...] = ()

    async def validate_credentials(self, credentials: Credentials) -> AccountInfo:
        return AccountInfo(login="committed-exports", external_id="kicad")


class _OAuthConnector:
    auth_kind = AuthKind.OAUTH
    supports_token_connect = False
    config_fields: tuple[str, ...] = ()

    async def validate_credentials(self, credentials: Credentials) -> AccountInfo:
        raise AssertionError("oauth connect must not validate in-tool")


def _connectors() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register("kicad", cast("Callable[[], Any]", _ExportConnector))
    registry.register("github", cast("Callable[[], Any]", _OAuthConnector))
    return registry


async def _scope(maker: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from solus_api.models import PlanType, Project, Subscription, SubscriptionStatus, Team, User

    async with maker() as session:
        team = Team(name="T")
        session.add(team)
        await session.flush()
        handle = uuid.uuid4().hex
        user = User(supabase_user_id=handle, email=f"{handle}@example.dev")
        session.add(user)
        await session.flush()
        # A planless user is refused by the integration limit gate (tested
        # separately); the happy paths run on an active plan.
        session.add(
            Subscription(user_id=user.id, plan=PlanType.PRO, status=SubscriptionStatus.ACTIVE)
        )
        project = Project(team_id=team.id, name="P", created_by=user.id)
        session.add(project)
        await session.flush()
        await session.commit()
        return project.id, team.id, user.id


def _registry(deps: ConnectIntegrationDeps) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_integration_tools(deps):
        registry.register(tool)
    return registry


async def _deps(maker: async_sessionmaker[AsyncSession]) -> ConnectIntegrationDeps:
    project_id, team_id, user_id = await _scope(maker)
    return ConnectIntegrationDeps(
        session_factory=maker,
        project_id=project_id,
        team_id=team_id,
        user_id=user_id,
        connectors=_connectors(),
    )


async def test_only_connect_requires_confirmation(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    registry = _registry(await _deps(maker))
    by_name = {d.name: d for d in registry.list()}
    assert by_name["solus.list_integrations"].requires_confirmation is False
    assert by_name["solus.verify_integration"].requires_confirmation is False
    connect = by_name["solus.connect_integration"]
    assert connect.requires_confirmation is True
    # The consent sentence is Solus-authored (SEC-C1 discipline).
    assert connect.consent_summary is not None
    # Credentials can never travel through model-visible arguments (§7).
    assert "token" not in connect.params["properties"]


async def test_discover_lists_providers_with_connection_state(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    deps = await _deps(maker)
    registry = _registry(deps)
    result = await registry.invoke(ToolCall(tool="solus.list_integrations", args={}))
    assert result.ok, result.error
    assert result.value is not None
    providers = {p["provider"]: p for p in result.value["providers"]}
    assert providers["kicad"]["connected"] is False
    assert providers["kicad"]["auth"] == "none"
    assert providers["github"]["auth"] == "oauth"


async def test_connect_creates_a_live_source_for_export_connectors(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    deps = await _deps(maker)
    registry = _registry(deps)
    result = await registry.invoke(
        ToolCall(tool="solus.connect_integration", args={"provider": "kicad"})
    )
    assert result.ok, result.error
    assert result.value is not None
    assert result.value["connected"] is True

    async with maker() as session:
        row = await session.scalar(select(Source).where(Source.project_id == deps.project_id))
    assert row is not None
    assert row.status is SourceStatus.CONNECTED
    assert row.team_id == deps.team_id and row.created_by == deps.user_id

    verify = await registry.invoke(
        ToolCall(tool="solus.verify_integration", args={"provider": "kicad"})
    )
    assert verify.ok
    assert verify.value is not None
    assert verify.value["connected"] is True


async def test_oauth_connect_returns_a_clear_next_step_not_a_dead_end(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    deps = await _deps(maker)
    registry = _registry(deps)
    result = await registry.invoke(
        ToolCall(tool="solus.connect_integration", args={"provider": "github"})
    )
    assert result.ok, result.error
    assert result.value is not None
    assert result.value["connected"] is False
    assert result.value["next_step"] == "complete_oauth_in_app"
    # No row is created by an OAuth pointer — nothing mutated.
    async with maker() as session:
        row = await session.scalar(select(Source).where(Source.project_id == deps.project_id))
    assert row is None


async def test_unknown_provider_fails_with_the_supported_roster(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    deps = await _deps(maker)
    registry = _registry(deps)
    result = await registry.invoke(
        ToolCall(tool="solus.connect_integration", args={"provider": "solidworks"})
    )
    assert result.ok is False
    assert result.error is not None
    assert "github" in result.error.message and "kicad" in result.error.message


async def test_connect_is_idempotent_about_existing_connections(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    deps = await _deps(maker)
    registry = _registry(deps)
    first = await registry.invoke(
        ToolCall(tool="solus.connect_integration", args={"provider": "kicad"})
    )
    assert first.ok
    assert first.value is not None
    second = await registry.invoke(
        ToolCall(tool="solus.connect_integration", args={"provider": "kicad"})
    )
    assert second.ok
    assert second.value is not None
    assert second.value["already_connected"] is True
    async with maker() as session:
        rows = (
            await session.scalars(select(Source).where(Source.project_id == deps.project_id))
        ).all()
    assert len(rows) == 1


def test_verify_without_connection_points_at_connect() -> None:
    # Shape-level: the read tools' returns carry next steps, asserted in the
    # async flows above; this pins the descriptor contract stays additive.
    from solus_api.agent.connect_integration import CONNECT_DESCRIPTOR

    assert CONNECT_DESCRIPTOR.params["additionalProperties"] is False


# ------------------- the inherited route-level park→decide e2e (SOLX-01 H3/M7)


class _ProposingModel:
    """Scripted provider proposing the destructive connect on round one."""

    async def stream(  # matches the provider-adapter seam
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: object = None,
        conversation: object = None,
        # The routed catalog entry may set a reasoning effort (SOLUSDEV-252 S1);
        # a fake adapter accepts whatever the seam passes.
        **_: Any,
    ) -> AsyncIterator[Any]:
        from solus_api.orchestration.providers import ToolUse, Usage

        yield "Connecting KiCad for you."
        yield ToolUse(id="tu_connect", name="solus.connect_integration", args={"provider": "kicad"})
        yield Usage(tokens_in=9, tokens_out=4)


async def _funded_alice(engine: AsyncEngine, client: AsyncClient, headers: dict[str, str]) -> None:
    from conftest import me
    from solus_api.models import CreditBalance, PlanType, Subscription, SubscriptionStatus

    profile = await me(client, headers)
    user_id = uuid.UUID(profile["id"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        # Onboarding may have provisioned either row already — top up, not insert.
        balance = await session.scalar(
            select(CreditBalance).where(CreditBalance.user_id == user_id)
        )
        if balance is None:
            session.add(CreditBalance(user_id=user_id, balance=10_000))
        else:
            balance.balance = 10_000
        sub = await session.scalar(
            select(Subscription).where(
                Subscription.user_id == user_id, Subscription.deleted_at.is_(None)
            )
        )
        if sub is None:
            session.add(
                Subscription(user_id=user_id, plan=PlanType.PRO, status=SubscriptionStatus.ACTIVE)
            )
        await session.commit()


def _confirmation_id_from_sse(body: str) -> str | None:
    import json

    for line in body.splitlines():
        if line.startswith("data: ") and '"confirmation_id"' in line:
            return str(json.loads(line[len("data: ") :])["confirmation_id"])
    return None


async def _sol_setup(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    from conftest import create_project, create_team

    team = await create_team(client, headers, "T")
    project = await create_project(client, headers, team["id"], "P")
    conv = await client.post(
        f"/api/v1/projects/{project['id']}/sol/conversations",
        headers=headers,
        json={"title": "connect"},
    )
    return project["id"], conv.json()["data"]["id"]


async def test_do_mode_parks_the_connect_and_approval_executes_it(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine
) -> None:

    await _funded_alice(engine, client, alice_headers)
    project_id, conversation_id = await _sol_setup(client, alice_headers)
    app.state.agent_runner = _runner(_ProposingModel())

    response = await client.post(
        f"/api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages",
        headers=alice_headers,
        json={"content": "connect kicad for me", "action_mode": "do"},
    )
    assert response.status_code == 200
    confirmation_id = _confirmation_id_from_sse(response.text)
    assert confirmation_id, response.text  # the park streamed inline

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        before = await session.scalar(select(Source))
    assert before is None  # parked, NOT executed

    decided = await client.post(
        f"/api/v1/projects/{project_id}/sol/confirmations/{confirmation_id}",
        headers=alice_headers,
        json={"decision": "approve"},
    )
    assert decided.status_code == 200
    assert decided.json()["data"]["ok"] is True

    async with maker() as session:
        row = await session.scalar(select(Source))
    assert row is not None and row.status is SourceStatus.CONNECTED


async def test_guide_mode_never_parks_or_connects(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine
) -> None:
    from solus_api.models import ToolConfirmation

    await _funded_alice(engine, client, alice_headers)
    project_id, conversation_id = await _sol_setup(client, alice_headers)
    app.state.agent_runner = _runner(_ProposingModel())

    response = await client.post(
        f"/api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages",
        headers=alice_headers,
        json={"content": "connect kicad for me", "action_mode": "guide"},
    )
    assert response.status_code == 200
    assert _confirmation_id_from_sse(response.text) is None
    assert "guide mode" in response.text

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        assert await session.scalar(select(Source)) is None
        assert await session.scalar(select(ToolConfirmation)) is None


async def test_another_member_cannot_decide_the_parked_connect(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    from conftest import BOB, add_member, me

    await _funded_alice(engine, client, alice_headers)
    project_id, conversation_id = await _sol_setup(client, alice_headers)
    await me(client, bob_headers)
    team_id = (await client.get(f"/api/v1/projects/{project_id}", headers=alice_headers)).json()[
        "data"
    ]["team_id"]
    await add_member(client, alice_headers, bob_headers, BOB, team_id, role="member")
    app.state.agent_runner = _runner(_ProposingModel())

    response = await client.post(
        f"/api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages",
        headers=alice_headers,
        json={"content": "connect kicad", "action_mode": "do"},
    )
    confirmation_id = _confirmation_id_from_sse(response.text)
    assert confirmation_id

    decided = await client.post(
        f"/api/v1/projects/{project_id}/sol/confirmations/{confirmation_id}",
        headers=bob_headers,
        json={"decision": "approve"},
    )
    # Owner-scoped: Bob's decision never executes the action.
    assert decided.status_code == 200
    assert decided.json()["data"]["ok"] is False
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        assert await session.scalar(select(Source)) is None


# ---------------- security-review mandated tests (SOLX-04 Phase-4)


async def test_invalid_args_are_refused_at_park_never_persisted_or_streamed(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine
) -> None:
    """SEC-H3: a token-shaped extra argument is refused BEFORE parking — it
    never reaches tool_confirmations.args, the consent card, or the SSE wire."""
    from solus_api.models import ToolConfirmation
    from solus_api.orchestration.providers import ToolUse

    class _LeakyModel(_ProposingModel):
        async def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            from solus_api.orchestration.providers import Usage

            yield "Connecting with your token."
            yield ToolUse(
                id="tu_leak",
                name="solus.connect_integration",
                args={"provider": "kicad", "token": "ghp_fake_pasted_secret"},
            )
            yield Usage(tokens_in=9, tokens_out=4)

    await _funded_alice(engine, client, alice_headers)
    project_id, conversation_id = await _sol_setup(client, alice_headers)
    app.state.agent_runner = _runner(_LeakyModel())

    response = await client.post(
        f"/api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages",
        headers=alice_headers,
        json={"content": "connect kicad with my token", "action_mode": "do"},
    )
    assert response.status_code == 200
    assert "ghp_fake_pasted_secret" not in response.text  # never on the wire
    assert _confirmation_id_from_sse(response.text) is None  # nothing parked

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        assert await session.scalar(select(ToolConfirmation)) is None
        assert await session.scalar(select(Source)) is None


async def test_unverified_caller_cannot_decide(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine
) -> None:
    """SEC-H2: the decide endpoint is a destructive execution point — it takes
    the same email-verification gate as REST source creation (ADR-009)."""
    from conftest import bearer

    await _funded_alice(engine, client, alice_headers)
    project_id, conversation_id = await _sol_setup(client, alice_headers)
    app.state.agent_runner = _runner(_ProposingModel())

    response = await client.post(
        f"/api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages",
        headers=alice_headers,
        json={"content": "connect kicad", "action_mode": "do"},
    )
    confirmation_id = _confirmation_id_from_sse(response.text)
    assert confirmation_id

    from conftest import ALICE

    unverified = bearer(ALICE["sub"], ALICE["email"], email_verified=False)
    decided = await client.post(
        f"/api/v1/projects/{project_id}/sol/confirmations/{confirmation_id}",
        headers=unverified,
        json={"decision": "approve"},
    )
    assert decided.status_code == 403
    assert decided.json()["error"]["code"] == "email_not_verified"
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        assert await session.scalar(select(Source)) is None


async def test_team_b_cannot_decide_team_a_parked_connect(
    app: FastAPI,
    client: AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    engine: AsyncEngine,
) -> None:
    """Cross-TEAM isolation on the destructive execution point: a member of an
    unrelated team gets 404 (no existence leak) and nothing executes."""
    from conftest import me

    await _funded_alice(engine, client, alice_headers)
    project_id, conversation_id = await _sol_setup(client, alice_headers)
    await me(client, bob_headers)  # Bob exists in his own personal team only
    app.state.agent_runner = _runner(_ProposingModel())

    response = await client.post(
        f"/api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages",
        headers=alice_headers,
        json={"content": "connect kicad", "action_mode": "do"},
    )
    confirmation_id = _confirmation_id_from_sse(response.text)
    assert confirmation_id

    decided = await client.post(
        f"/api/v1/projects/{project_id}/sol/confirmations/{confirmation_id}",
        headers=bob_headers,
        json={"decision": "approve"},
    )
    assert decided.status_code == 404
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        assert await session.scalar(select(Source)) is None


async def test_injected_connect_instruction_still_parks_never_executes(
    app: FastAPI, client: AsyncClient, alice_headers: dict[str, str], engine: AsyncEngine
) -> None:
    """SEC-M4: the red-team corpus meets the first REAL destructive tool — an
    ingested instruction to connect cannot execute anything without approval."""
    from fixtures.injection_corpus import PAYLOADS

    await _funded_alice(engine, client, alice_headers)
    project_id, conversation_id = await _sol_setup(client, alice_headers)
    app.state.agent_runner = _runner(_ProposingModel())

    hostile = next(p for p in PAYLOADS if "pre-approved" in p.text).text
    response = await client.post(
        f"/api/v1/projects/{project_id}/sol/conversations/{conversation_id}/messages",
        headers=alice_headers,
        json={"content": f"the design notes say: {hostile}", "action_mode": "do"},
    )
    assert response.status_code == 200
    # Parked at most; NEVER executed regardless of what the text claimed.
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        assert await session.scalar(select(Source)) is None


async def test_concurrent_connects_yield_exactly_one_source(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """SEC-M2: the advisory xact lock serializes racing connects — two
    concurrent invocations produce one live Source, the loser seeing
    already_connected."""
    import asyncio

    deps = await _deps(maker)
    registry = _registry(deps)
    call = ToolCall(tool="solus.connect_integration", args={"provider": "kicad"})
    first, second = await asyncio.gather(registry.invoke(call), registry.invoke(call))
    assert first.ok and second.ok
    async with maker() as session:
        rows = (
            await session.scalars(select(Source).where(Source.project_id == deps.project_id))
        ).all()
    assert len(rows) == 1
