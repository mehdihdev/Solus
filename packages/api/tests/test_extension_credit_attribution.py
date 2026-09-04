"""Credit attribution for extension-originated SOL turns (SOLUSDEV-235 / EXT-11).

docs/api/extensions.md §9: `X-Solus-Extension: <slug>` on the SOL turn route is
accepted ONLY when the project has an ENABLED install of that slug granting
`sol.ask` and the team has not blocked the extension — otherwise `403
scope_denied`, never a silently unattributed turn. The debit stays on the
invoking user (ADR-018/024, no pooling); `credit_ledger.extension_id` records
the attribution (ADR-035 §2) and survives the dead-letter path (contract §6).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from conftest import create_project, create_team, me
from fastapi import FastAPI
from fixtures.fake_systems import FakeSolSystems
from httpx import AsyncClient
from solus_api.agent.runtime import AgentRunContext, LlmRunner
from solus_api.agent.stream import AgentEvent
from solus_api.billing import credits as billing_credits
from solus_api.billing import reconciliation
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.core.errors import APIError
from solus_api.extensions.attribution import (
    EXTENSION_HEADER,
    SOL_ASK_SCOPE,
    resolve_extension_attribution,
)
from solus_api.models import (
    ArtifactStorage,
    CreditBalance,
    CreditLedger,
    Extension,
    ExtensionInstall,
    ExtensionPublisher,
    ExtensionVersion,
    PendingCreditDebit,
    Project,
    Team,
    TeamExtensionPolicy,
    User,
)
from solus_api.orchestration import gateway
from solus_api.orchestration.config import CostConfig
from solus_api.orchestration.cost import track_cost
from solus_api.orchestration.enums import InteractionContext
from solus_api.orchestration.providers import ToolConversation, Usage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_cost import _model
from test_sol_red_team import _funded_ctx, _registry

SHA256_HEX = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
_COST = CostConfig(credits_per_dollar=100.0)


# ------------------------------------------------------------------ seeding


@dataclass(frozen=True)
class _Seeded:
    project: Project
    extension: Extension
    version: ExtensionVersion


async def _seed_extension(
    db: AsyncSession, slug: str = "bom"
) -> tuple[Extension, ExtensionVersion]:
    publisher = ExtensionPublisher(display_name="Ada")
    db.add(publisher)
    await db.flush()
    extension = Extension(slug=slug, publisher_id=publisher.id, name="BOM", summary="Bill.")
    db.add(extension)
    await db.flush()
    version = ExtensionVersion(
        extension_id=extension.id,
        version="1.0.0",
        manifest={"schema_version": 1, "extension": {"id": slug}},
        bundle_storage=ArtifactStorage.LOCAL,
        content_hash=SHA256_HEX,
        bundle_size_bytes=1024,
    )
    db.add(version)
    await db.flush()
    return extension, version


async def _install(
    db: AsyncSession,
    project_id: uuid.UUID,
    extension: Extension,
    version: ExtensionVersion,
    *,
    enabled: bool = True,
    scopes: tuple[str, ...] = (SOL_ASK_SCOPE,),
) -> ExtensionInstall:
    row = ExtensionInstall(
        project_id=project_id,
        extension_id=extension.id,
        version_id=version.id,
        enabled=enabled,
        granted_scopes=list(scopes),
    )
    db.add(row)
    await db.commit()
    return row


async def _policy(
    db: AsyncSession, team_id: uuid.UUID, extension: Extension, *, blocked: bool
) -> None:
    db.add(TeamExtensionPolicy(team_id=team_id, extension_id=extension.id, blocked=blocked))
    await db.commit()


async def _seed_project(db: AsyncSession) -> _Seeded:
    tag = uuid.uuid4().hex[:8]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com")
    team = Team(name="Ext")
    db.add_all([user, team])
    await db.flush()
    project = Project(team_id=team.id, name="Rover", created_by=user.id)
    db.add(project)
    await db.flush()
    extension, version = await _seed_extension(db)
    await db.commit()
    return _Seeded(project=project, extension=extension, version=version)


async def _ledger_rows(db: AsyncSession, call_id: str) -> list[CreditLedger]:
    rows = await db.scalars(select(CreditLedger).where(CreditLedger.idempotency_key == call_id))
    return list(rows.all())


async def _seed_user(db: AsyncSession, balance: int = 1_000) -> User:
    tag = uuid.uuid4().hex[:10]
    user = User(supabase_user_id=f"sub-{tag}", email=f"{tag}@example.com")
    db.add(user)
    await db.flush()
    db.add(CreditBalance(user_id=user.id, balance=balance))
    await db.commit()
    return user


# -------------------------------------------------- resolver (unit, over the DB)


async def test_absent_header_resolves_to_none(db: AsyncSession) -> None:
    seeded = await _seed_project(db)
    resolved = await resolve_extension_attribution(db, project=seeded.project, header_value=None)
    assert resolved is None


async def test_enabled_install_with_sol_ask_resolves_to_extension_id(db: AsyncSession) -> None:
    seeded = await _seed_project(db)
    await _install(db, seeded.project.id, seeded.extension, seeded.version)
    resolved = await resolve_extension_attribution(db, project=seeded.project, header_value="bom")
    assert resolved == seeded.extension.id


async def test_explicit_unblocked_policy_row_still_resolves(db: AsyncSession) -> None:
    seeded = await _seed_project(db)
    await _install(db, seeded.project.id, seeded.extension, seeded.version)
    await _policy(db, seeded.project.team_id, seeded.extension, blocked=False)
    resolved = await resolve_extension_attribution(db, project=seeded.project, header_value="bom")
    assert resolved == seeded.extension.id


async def _assert_scope_denied(project: Project, db: AsyncSession, header: str) -> None:
    with pytest.raises(APIError) as excinfo:
        await resolve_extension_attribution(db, project=project, header_value=header)
    assert excinfo.value.status_code == 403
    assert excinfo.value.code == "scope_denied"


@pytest.mark.parametrize(
    "header", ["", "B0M", "-bom", "a", "bom_x", "bom; drop", "x" * 65, "bom\n"]
)
async def test_malformed_slug_is_scope_denied(db: AsyncSession, header: str) -> None:
    seeded = await _seed_project(db)
    await _install(db, seeded.project.id, seeded.extension, seeded.version)
    await _assert_scope_denied(seeded.project, db, header)


async def test_unknown_extension_is_scope_denied(db: AsyncSession) -> None:
    seeded = await _seed_project(db)
    await _assert_scope_denied(seeded.project, db, "nope")


async def test_extension_without_install_is_scope_denied(db: AsyncSession) -> None:
    """A client-asserted header is never accepted without the install row."""
    seeded = await _seed_project(db)
    await _assert_scope_denied(seeded.project, db, "bom")


async def test_install_in_another_project_does_not_count(db: AsyncSession) -> None:
    seeded = await _seed_project(db)
    other = Project(team_id=seeded.project.team_id, name="Other", created_by=None)
    db.add(other)
    await db.flush()
    await _install(db, other.id, seeded.extension, seeded.version)
    await _assert_scope_denied(seeded.project, db, "bom")


async def test_disabled_install_is_scope_denied(db: AsyncSession) -> None:
    seeded = await _seed_project(db)
    await _install(db, seeded.project.id, seeded.extension, seeded.version, enabled=False)
    await _assert_scope_denied(seeded.project, db, "bom")


async def test_install_without_sol_ask_is_scope_denied(db: AsyncSession) -> None:
    seeded = await _seed_project(db)
    await _install(db, seeded.project.id, seeded.extension, seeded.version, scopes=("storage.own",))
    await _assert_scope_denied(seeded.project, db, "bom")


async def test_team_blocked_extension_is_scope_denied(db: AsyncSession) -> None:
    seeded = await _seed_project(db)
    await _install(db, seeded.project.id, seeded.extension, seeded.version)
    await _policy(db, seeded.project.team_id, seeded.extension, blocked=True)
    await _assert_scope_denied(seeded.project, db, "bom")


# ---------------------------------------------- ledger: debit hook + dead-letter


async def test_track_cost_without_attribution_leaves_extension_id_null(db: AsyncSession) -> None:
    user = await _seed_user(db)
    await track_cost("call-plain", user.id, _model(), 10_000, 5_000, session=db, cost=_COST)
    (row,) = await _ledger_rows(db, "call-plain")
    assert row.extension_id is None


async def test_track_cost_records_attribution_on_the_users_debit(db: AsyncSession) -> None:
    """The row is attributed to the extension but debited from the INVOKING user's
    balance — attribution only, never a separate budget (ADR-018/024)."""
    user = await _seed_user(db, balance=1_000)
    extension, _ = await _seed_extension(db)
    await db.commit()
    await track_cost(
        "call-ext",
        user.id,
        _model(),
        10_000,
        5_000,
        session=db,
        cost=_COST,
        extension_id=extension.id,
    )
    (row,) = await _ledger_rows(db, "call-ext")
    assert row.extension_id == extension.id
    assert row.user_id == user.id
    assert row.amount < 0
    balance = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == user.id))
    assert balance == 1_000 + row.amount


async def test_debit_failure_keeps_attribution_through_reconciliation(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract §6: the result is served (no raise), the dead-letter record carries
    the extension id, and the swept debit lands in the ledger WITH `extension_id`."""
    user = await _seed_user(db, balance=1_000)
    extension, _ = await _seed_extension(db)
    await db.commit()
    real_debit = billing_credits.debit_credits
    calls = {"n": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db went away mid-debit")
        return await real_debit(*args, **kwargs)

    monkeypatch.setattr(billing_credits, "debit_credits", flaky)
    await track_cost(
        "call-dl",
        user.id,
        _model(),
        10_000,
        5_000,
        session=db,
        cost=_COST,
        extension_id=extension.id,
    )  # must not raise
    pending = await db.scalar(
        select(PendingCreditDebit).where(PendingCreditDebit.idempotency_key == "call-dl")
    )
    assert pending is not None
    assert pending.attrs["extension_id"] == str(extension.id)
    assert pending.attrs["tokens_in"] == 10_000

    maker = async_sessionmaker(engine, expire_on_commit=False)
    assert await reconciliation.reconcile_pending_debits(maker) == 1
    (row,) = await _ledger_rows(db, "call-dl")
    assert row.extension_id == extension.id
    assert row.user_id == user.id
    assert "extension_id" not in row.attrs  # lifted into the column, not duplicated


async def test_dead_letter_without_attribution_reconciles_unattributed(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    user = await _seed_user(db)
    await reconciliation.record_failed_debit(db, user.id, 7, idempotency_key="call-na", attrs={})
    maker = async_sessionmaker(engine, expire_on_commit=False)
    await reconciliation.reconcile_pending_debits(maker)
    (row,) = await _ledger_rows(db, "call-na")
    assert row.extension_id is None


# ------------------------------------------------ gateway + runner threading


class _OneShotModel:
    """A scripted adapter: one text chunk, then usage — enough to fire the hook."""

    async def stream(
        self,
        model_name: str,
        query: str,
        *,
        max_tokens: int,
        images: Any = None,
        conversation: ToolConversation | None = None,
    ) -> AsyncIterator[str | Usage]:
        yield "ok"
        yield Usage(tokens_in=10_000, tokens_out=5_000)


def _adapters() -> dict[str, Any]:
    model = _OneShotModel()
    return {"anthropic": model, "openai": model, "google": model}


async def test_gateway_complete_threads_attribution_to_the_ledger(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    extension, _ = await _seed_extension(db)
    await db.commit()
    ctx = await _funded_ctx(engine, _registry([]))
    assert ctx.sessionmaker is not None and ctx.user_id is not None
    async with ctx.sessionmaker() as session:
        completion = await gateway.complete(
            "hello",
            secret_store=InMemorySecretStore(),
            context=InteractionContext.SOL_OPEN_QUESTION,
            adapters=_adapters(),
            user_id=ctx.user_id,
            session=session,
            extension_id=extension.id,
        )
    (row,) = await _ledger_rows(db, completion.call_id)
    assert row.extension_id == extension.id
    assert row.user_id == ctx.user_id


async def test_llm_runner_passes_context_attribution_to_the_gateway(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    extension, _ = await _seed_extension(db)
    await db.commit()
    ctx = await _funded_ctx(
        engine, _registry([]), systems=FakeSolSystems(), extension_id=extension.id
    )
    runner = LlmRunner(adapters=_adapters())
    _ = [event async for event in runner.run(ctx)]
    rows = await db.scalars(select(CreditLedger).where(CreditLedger.user_id == ctx.user_id))
    attributed = [r.extension_id for r in rows.all()]
    assert attributed and all(e == extension.id for e in attributed)


async def test_llm_runner_default_context_is_unattributed(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    ctx = await _funded_ctx(engine, _registry([]), systems=FakeSolSystems())
    runner = LlmRunner(adapters=_adapters())
    _ = [event async for event in runner.run(ctx)]
    rows = await db.scalars(select(CreditLedger).where(CreditLedger.user_id == ctx.user_id))
    attributed = [r.extension_id for r in rows.all()]
    assert attributed and all(e is None for e in attributed)


# ------------------------------------------------------- the SOL turn route


class _Capture:
    """Records the context the router built; a model-free turn."""

    def __init__(self) -> None:
        self.seen: list[AgentRunContext] = []

    async def run(self, ctx: AgentRunContext) -> AsyncIterator[AgentEvent]:
        self.seen.append(ctx)
        yield AgentEvent.message("ok")


@dataclass(frozen=True)
class _Route:
    team_id: uuid.UUID
    project_id: uuid.UUID
    url: str
    extension: Extension
    version: ExtensionVersion


async def _route(client: AsyncClient, headers: dict[str, str], db: AsyncSession) -> _Route:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    convo = await client.post(
        f"/api/v1/projects/{project['id']}/sol/conversations", json={}, headers=headers
    )
    assert convo.status_code == 201, convo.text
    extension, version = await _seed_extension(db)
    await db.commit()
    return _Route(
        team_id=uuid.UUID(team["id"]),
        project_id=uuid.UUID(project["id"]),
        url=f"/api/v1/projects/{project['id']}/sol/conversations/{convo.json()['data']['id']}",
        extension=extension,
        version=version,
    )


async def _post(
    client: AsyncClient, route: _Route, headers: dict[str, str], slug: str | None
) -> Any:
    sent = dict(headers) if slug is None else {**headers, EXTENSION_HEADER: slug}
    return await client.post(f"{route.url}/messages", json={"content": "hello"}, headers=sent)


async def _turn_count(client: AsyncClient, route: _Route, headers: dict[str, str]) -> int:
    resp = await client.get(f"{route.url}/turns", headers=headers)
    assert resp.status_code == 200
    return len(resp.json()["data"])


async def test_route_without_header_builds_unattributed_context(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    capture = _Capture()
    app.state.agent_runner = capture
    route = await _route(client, alice_headers, db)
    resp = await _post(client, route, alice_headers, None)
    assert resp.status_code == 200
    assert capture.seen[0].extension_id is None


async def test_route_with_valid_header_attributes_the_turn(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    capture = _Capture()
    app.state.agent_runner = capture
    route = await _route(client, alice_headers, db)
    await _install(db, route.project_id, route.extension, route.version)
    resp = await _post(client, route, alice_headers, "bom")
    assert resp.status_code == 200
    assert capture.seen[0].extension_id == route.extension.id
    # The invoking user's identity is unchanged — metering stays per-user.
    assert capture.seen[0].user_id is not None


async def test_route_end_to_end_debits_alice_with_attribution(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    """Whole chain through the real gateway: header → install check → run
    context → gateway → track_cost → `credit_ledger.extension_id`, debited from
    the invoking user (Alice), with the SSE turn served normally."""
    app.state.agent_runner = LlmRunner(adapters=_adapters())
    app.state.sol_systems = FakeSolSystems()
    route = await _route(client, alice_headers, db)
    await _install(db, route.project_id, route.extension, route.version)
    alice = await db.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice is not None
    before = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == alice.id))

    resp = await _post(client, route, alice_headers, "bom")
    assert resp.status_code == 200, resp.text
    assert "event: done" in resp.text

    rows = (await db.scalars(select(CreditLedger).where(CreditLedger.amount < 0))).all()
    assert rows and all(
        r.user_id == alice.id and r.extension_id == route.extension.id for r in rows
    )
    after = await db.scalar(select(CreditBalance.balance).where(CreditBalance.user_id == alice.id))
    assert before is not None and after is not None and after < before


@pytest.mark.parametrize(
    "case", ["not_installed", "disabled", "scope_not_granted", "blocked", "malformed"]
)
async def test_route_refuses_unauthorized_header_before_admission(
    client: AsyncClient,
    alice_headers: dict[str, str],
    app: FastAPI,
    db: AsyncSession,
    case: str,
) -> None:
    """Every refusal is a 403 `scope_denied` — never a silently unattributed
    turn — and it fires BEFORE admission: no user turn is persisted."""
    capture = _Capture()
    app.state.agent_runner = capture
    route = await _route(client, alice_headers, db)
    slug = "bom"
    if case == "disabled":
        await _install(db, route.project_id, route.extension, route.version, enabled=False)
    elif case == "scope_not_granted":
        await _install(
            db, route.project_id, route.extension, route.version, scopes=("storage.own",)
        )
    elif case == "blocked":
        await _install(db, route.project_id, route.extension, route.version)
        await _policy(db, route.team_id, route.extension, blocked=True)
    elif case == "malformed":
        await _install(db, route.project_id, route.extension, route.version)
        slug = "BOM!"

    resp = await _post(client, route, alice_headers, slug)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "scope_denied"
    assert capture.seen == []
    assert await _turn_count(client, route, alice_headers) == 0


async def test_route_header_is_ignored_on_non_turn_routes(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """Only the turn-starting route consumes the header; a read with a bogus
    header is not refused (nothing to attribute)."""
    route = await _route(client, alice_headers, db)
    resp = await client.get(
        f"{route.url}/turns", headers={**alice_headers, EXTENSION_HEADER: "nope"}
    )
    assert resp.status_code == 200
