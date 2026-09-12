"""BYO-license tiering (SOLUSDEV-153 MCP-05 Part A).

The catalog carries the tier as data, `byo_paid_tools` is a plan limit read as
DATA (ADR-023, never a plan-name branch), the data migration backfills existing
subscriptions (absent key = unlimited would fail-open a paid feature), and the
invoke-time gate blocks byo_paid bridge tools: plan entitlement first, then
license-credential presence under the tenant-scoped ref. Free-tier and
uncataloged servers get zero new checks.
"""

import asyncio
import importlib.util
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import me
from httpx import AsyncClient
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools.mcp_servers import (
    MCP_SERVER_CATALOG,
    build_license_preflight,
    license_secret_ref,
)
from solus_api.agent.tools.mcp_tool import LicenseTier
from solus_api.agent.tools.shapes import ToolCall, ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.core.errors import APIError
from solus_api.models import PLAN_LIMITS, PlanType, Subscription, User, utcnow
from solus_api.services.limits import check_can_use_byo_tool
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

#: SOLUS-ONS-A1 removed `onshape`: it was an API-KEY-PAIR spec, a credential
#: that authenticates the developer rather than the customer. Onshape is now
#: reached through the customer OAuth grant as in-process tools, not MCP.
FREE_SERVERS = {"brave", "kicad", "fusion"}
BYO_SERVERS = {"altium", "solidworks", "autocad"}


# --------------------------------------------------------------- catalog + data
def test_catalog_tiers_rosters_and_license_keys() -> None:
    assert set(MCP_SERVER_CATALOG) == FREE_SERVERS | BYO_SERVERS
    for name, spec in MCP_SERVER_CATALOG.items():
        assert spec.name == name  # keyed by spec name
    for name in FREE_SERVERS:
        spec = MCP_SERVER_CATALOG[name]
        assert spec.license_tier is LicenseTier.FREE
        assert spec.license_secrets == ()  # free tier needs no license keys
    for name in BYO_SERVERS:
        spec = MCP_SERVER_CATALOG[name]
        assert spec.license_tier is LicenseTier.BYO_PAID
        assert spec.license_secrets  # every byo_paid tool names its license keys


def test_new_stdio_specs_are_pinned_paths_not_package_runners() -> None:
    # MCP-03 rule: no npx/uvx/PATH-resolved names. `brave` was the last
    # PATH-resolved holdout and is now a vendored fork (SOLUSDEV-252 P6), so
    # there is no exemption left — every stdio spec is a pinned launcher path.
    for name in (FREE_SERVERS | BYO_SERVERS) - {"onshape"}:
        spec = MCP_SERVER_CATALOG[name]
        if spec.url is not None:
            continue  # vendor-run, not a fork we launch — see below
        assert spec.command is not None and "/" in spec.command
        assert spec.command.split("/")[0] not in {"npx", "uvx"}


def test_vendor_run_specs_are_loopback_only() -> None:
    """CAD-02. A url spec names a server on the CUSTOMER's machine, which is a
    licensing requirement (Autodesk prohibits hosting or multiplexing a licensed
    seat) as well as the only place a local CAD app exists.

    A non-loopback url here would point the companion at an arbitrary host —
    an SSRF primitive inside the customer's network."""
    from solus_companion.config import is_loopback_url

    for name in FREE_SERVERS | BYO_SERVERS:
        spec = MCP_SERVER_CATALOG[name]
        if spec.url is None:
            continue
        assert is_loopback_url(spec.url), f"{name} url is not loopback: {spec.url}"


def test_license_secret_ref_is_tenant_scoped() -> None:
    team_id = uuid.uuid4()
    ref = license_secret_ref(team_id, "altium", "altium_license")
    assert ref == f"mcp-license/{team_id}/altium/altium_license"


def test_plan_limits_carry_byo_paid_tools() -> None:
    assert PLAN_LIMITS[PlanType.BASIC]["byo_paid_tools"] == 0  # blocked
    assert PLAN_LIMITS[PlanType.PRO]["byo_paid_tools"] is None  # unlimited
    assert PLAN_LIMITS[PlanType.ENTERPRISE] == {}  # custom per deal, untouched


# ------------------------------------------------------------------- migration
def _load_migration() -> Any:
    versions = Path(__file__).resolve().parent.parent / "migrations" / "versions"
    matches = list(versions.glob("*byo_paid_tools*.py"))
    assert len(matches) == 1, f"expected exactly one MCP-05 migration, found {matches}"
    spec = importlib.util.spec_from_file_location("mcp05_migration", matches[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _seed_subscription(db: AsyncSession, plan: PlanType, limits: dict[str, Any]) -> uuid.UUID:
    user = User(supabase_user_id=f"mig-{uuid.uuid4()}", email=f"{uuid.uuid4()}@example.com")
    db.add(user)
    await db.flush()
    sub = Subscription(user_id=user.id, plan=plan, limits=limits)
    db.add(sub)
    await db.flush()
    return sub.id


async def test_migration_backfills_and_downgrade_removes(db: AsyncSession) -> None:
    """The data migration's own SQL (imported, not copied): basic rows gain 0,
    pro rows gain explicit null, enterprise and already-set rows are untouched;
    the downgrade removes the key. Without the backfill, `_limit()` treats the
    absent key as unlimited — every existing BASIC user gets paid tools free."""
    migration = _load_migration()
    basic = await _seed_subscription(db, PlanType.BASIC, {"max_teams": 2})
    pro = await _seed_subscription(db, PlanType.PRO, {"max_teams": None})
    custom = await _seed_subscription(db, PlanType.BASIC, {"byo_paid_tools": 5})
    enterprise = await _seed_subscription(db, PlanType.ENTERPRISE, {})
    await db.commit()

    for statement in migration.UPGRADE_SQL:
        await db.execute(text(statement))
    await db.commit()

    async def limits_of(sub_id: uuid.UUID) -> dict[str, Any]:
        row = await db.scalar(select(Subscription).where(Subscription.id == sub_id))
        assert row is not None
        await db.refresh(row)
        return row.limits

    assert (await limits_of(basic))["byo_paid_tools"] == 0
    pro_limits = await limits_of(pro)
    assert "byo_paid_tools" in pro_limits and pro_limits["byo_paid_tools"] is None
    assert (await limits_of(custom))["byo_paid_tools"] == 5  # already set: untouched
    assert "byo_paid_tools" not in await limits_of(enterprise)

    for statement in migration.DOWNGRADE_SQL:
        await db.execute(text(statement))
    await db.commit()
    assert "byo_paid_tools" not in await limits_of(basic)
    assert "byo_paid_tools" not in await limits_of(pro)


# ------------------------------------------------------------ entitlement check
async def _user(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, uuid.UUID(user_id))
    assert user is not None
    return user


async def test_basic_plan_blocks_byo_tool(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    user = await _user(db, alice["id"])
    with pytest.raises(APIError) as info:
        await check_can_use_byo_tool(db, user, "altium")
    assert info.value.status_code == 409
    assert info.value.code == "plan_limit_reached"
    assert info.value.details[0]["limit"] == "byo_paid_tools"
    assert "Pro plan" in info.value.message and "altium" in info.value.message


async def test_pro_plan_allows_byo_tool(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    resp = await client.patch(
        "/api/v1/users/me/subscription", json={"plan": "pro"}, headers=alice_headers
    )
    assert resp.status_code == 200, resp.text
    await check_can_use_byo_tool(db, await _user(db, alice["id"]), "altium")  # no raise


async def test_nonzero_cap_allows_byo_tool(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await db.scalar(
        select(Subscription).where(Subscription.user_id == uuid.UUID(alice["id"]))
    )
    assert sub is not None
    sub.limits = {"byo_paid_tools": 3}  # any positive cap = entitled (data, not plan name)
    await db.commit()
    await check_can_use_byo_tool(db, await _user(db, alice["id"]), "altium")  # no raise


async def test_no_subscription_stays_402(
    client: AsyncClient, db: AsyncSession, alice_headers: dict[str, str]
) -> None:
    alice = await me(client, alice_headers)
    sub = await db.scalar(
        select(Subscription).where(Subscription.user_id == uuid.UUID(alice["id"]))
    )
    assert sub is not None
    sub.deleted_at = utcnow()
    await db.commit()
    with pytest.raises(APIError) as info:
        await check_can_use_byo_tool(db, await _user(db, alice["id"]), "altium")
    assert info.value.status_code == 402
    assert info.value.code == "subscription_required"


# ------------------------------------------------------------- invoke-time gate
Scope = tuple[uuid.UUID, uuid.UUID, uuid.UUID]


def _tool_spec(server: str, tool: str) -> BridgeToolSpec:
    return BridgeToolSpec(
        server=server,
        remote_name=tool,
        descriptor=ToolDescriptor(
            name=f"{server}.{tool}",
            description=tool,
            params={"type": "object"},
            returns={"type": "object"},
        ),
    )


def _live_session(scope: Scope, inventory: tuple[BridgeToolSpec, ...]) -> BridgeSession:
    async def _send(frame: str) -> None:
        return None

    async def _close(code: int) -> None:
        return None

    return BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        companion_instance_id="i-1",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=inventory,
        send=_send,
        close=_close,
        max_inflight=8,
    )


async def _gated_registry(
    engine: AsyncEngine,
    client: AsyncClient,
    headers: dict[str, str],
    store: InMemorySecretStore | None,
    *,
    servers: tuple[tuple[str, str], ...] = (("altium", "list_units"),),
) -> tuple[Any, InMemoryBridgeSessionRegistry, BridgeSession, Scope]:
    """A SOL registry whose bridge inventory carries the given servers, with the
    session left LIVE. Returns (registry, sessions, session, scope)."""
    user = await me(client, headers)
    scope: Scope = (uuid.UUID(user["id"]), uuid.uuid4(), uuid.uuid4())
    sessions = InMemoryBridgeSessionRegistry()
    session = _live_session(scope, tuple(_tool_spec(s, t) for s, t in servers))
    sessions.bind(session)
    registry = build_sol_registry(
        async_sessionmaker(engine, expire_on_commit=False),
        scope[2],
        bridge=sessions,
        user_id=scope[0],
        team_id=scope[1],
        secret_store=store,
    )
    return registry, sessions, session, scope


async def test_gate_blocks_basic_plan_with_upgrade_message(
    engine: AsyncEngine, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    registry, _, _, _ = await _gated_registry(engine, client, alice_headers, InMemorySecretStore())
    result = await registry.invoke(ToolCall(tool="altium.list_units", args={}))
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    assert result.error.retryable is False
    assert "Pro plan" in result.error.message and "altium" in result.error.message
    assert "APIError" not in result.error.message  # message, never the raw repr


async def test_gate_names_missing_license_keys_for_entitled_user(
    engine: AsyncEngine, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/subscription", json={"plan": "pro"}, headers=alice_headers
    )
    assert resp.status_code == 200
    registry, _, _, _ = await _gated_registry(engine, client, alice_headers, InMemorySecretStore())
    result = await registry.invoke(ToolCall(tool="altium.list_units", args={}))
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    assert "Bring your license" in result.error.message
    assert "altium_license" in result.error.message  # key NAMES name the fix


async def test_gate_passes_with_stored_license_then_bridge_owns_the_call(
    engine: AsyncEngine, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """PRO + license stored under the EXACT gate ref → the gate no longer blocks:
    the failure (session removed → bridge offline) is the transport's, proving
    the round-trip between Part B's write ref and Part A's read ref."""
    resp = await client.patch(
        "/api/v1/users/me/subscription", json={"plan": "pro"}, headers=alice_headers
    )
    assert resp.status_code == 200
    store = InMemorySecretStore()
    registry, sessions, session, scope = await _gated_registry(engine, client, alice_headers, store)
    await store.put(license_secret_ref(scope[1], "altium", "altium_license"), "fake-lic-1")
    sessions.remove(session)  # gate passes → next failure is the offline transport
    result = await registry.invoke(ToolCall(tool="altium.list_units", args={}))
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.UNAVAILABLE
    assert "bridge offline" in result.error.message


async def test_free_and_uncataloged_servers_have_zero_new_checks(
    engine: AsyncEngine, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    # BASIC user, no licenses anywhere: kicad (free tier) and mock (not in the
    # catalog) must behave exactly as before — straight to the transport.
    registry, sessions, session, _ = await _gated_registry(
        engine,
        client,
        alice_headers,
        InMemorySecretStore(),
        servers=(("kicad", "list_footprints"), ("mock", "echo")),
    )
    sessions.remove(session)
    for tool in ("kicad.list_footprints", "mock.echo"):
        result = await registry.invoke(ToolCall(tool=tool, args={}))
        assert result.ok is False and result.error is not None
        assert result.error.code is ToolErrorCode.UNAVAILABLE  # never UNAUTHORIZED


async def test_gate_fails_closed_without_a_secret_store(
    engine: AsyncEngine, client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """No secret_store threaded (legacy call shape) + byo_paid server: the license
    check treats every key as missing — a paid feature never fails open."""
    resp = await client.patch(
        "/api/v1/users/me/subscription", json={"plan": "pro"}, headers=alice_headers
    )
    assert resp.status_code == 200
    registry, _, _, _ = await _gated_registry(engine, client, alice_headers, None)
    result = await registry.invoke(ToolCall(tool="altium.list_units", args={}))
    assert result.ok is False and result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED
    assert "Bring your license" in result.error.message


async def test_preflight_rejects_unknown_user() -> None:
    """Defensive: a preflight for a user id with no row is UNAUTHORIZED, not a crash."""
    spec = MCP_SERVER_CATALOG["altium"]
    # A real sessionmaker against the test DB; the user id simply does not exist.
    from conftest import TEST_DATABASE_URL
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        preflight = build_license_preflight(
            spec,
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
            user_id=uuid.uuid4(),
            team_id=uuid.uuid4(),
            secret_store=InMemorySecretStore(),
        )
        with pytest.raises(ToolException) as info:
            await preflight()
        assert info.value.code is ToolErrorCode.UNAUTHORIZED
    finally:
        await engine.dispose()


def test_bridge_tool_runs_preflight_before_session_lookup() -> None:
    """Order matters: an entitlement refusal must win over 'bridge offline', so a
    blocked user sees the upgrade path, not a transport hint."""
    from solus_api.bridge.tool import BridgeTool

    async def _preflight() -> None:
        raise ToolException("blocked", code=ToolErrorCode.UNAUTHORIZED, retryable=False)

    tool = BridgeTool(
        descriptor=ToolDescriptor(
            name="altium.list_units",
            description="d",
            params={"type": "object"},
            returns={"type": "object"},
        ),
        sessions=InMemoryBridgeSessionRegistry(),  # offline — lookup would say UNAVAILABLE
        user_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        call_cap_bytes=262_144,
        preflight=_preflight,
    )
    with pytest.raises(ToolException) as info:
        asyncio.run(tool.invoke({}))
    assert info.value.code is ToolErrorCode.UNAUTHORIZED
    assert "blocked" in str(info.value)


def test_catalog_specs_serialize_without_leaking_anything() -> None:
    # The catalog is config, not credentials: license_secrets are KEY NAMES only.
    for spec in MCP_SERVER_CATALOG.values():
        dumped = json.dumps(spec.model_dump(mode="json"))
        assert "fake-lic" not in dumped  # trivially true; guards accidental value fields


def test_fusion_carries_a_personal_tier_notice() -> None:
    """CAD-02. Fusion Personal forbids commercial use and >$1,000/year of
    output, and Autodesk asks integrations to warn about it. A paying Solus
    customer driving a free-tier Fusion for business work breaches their terms.

    The notice INFORMS and does not block: the licence is the customer's to
    hold, and refusing to connect would neither enforce it nor help them."""
    notice = MCP_SERVER_CATALOG["fusion"].connect_notice

    assert notice is not None
    assert "non-commercial" in notice.lower()


def test_the_notice_is_generic_catalog_data_not_a_fusion_branch() -> None:
    """Any surface offering a tool can render this without knowing which tool it
    is — the treatment `access_modes` and `selection` already get on connectors.
    Tools with nothing to say simply carry None."""
    assert MCP_SERVER_CATALOG["kicad"].connect_notice is None
    assert "connect_notice" in type(MCP_SERVER_CATALOG["fusion"]).model_fields
