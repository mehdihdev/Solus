"""Onshape operations exposed to SOL as in-process tools (SOLUS-ONS-A1).

The seam this proves: an MCP tool invocation is NOT a sync, so the credentials
have to be found a different way — project → the connected Onshape `Source` →
its `secret_ref` → `resolve_credentials` → `call_with_refresh`. The tenant is
bound at CONSTRUCTION by Solus code (the `get_entity` idiom), so the model has no
argument that could reach another team's Onshape.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from fixtures.onshape_sample import DOCUMENT_LIST, VARIABLES, WORKSPACE_INFO
from solus_api.agent.tools.onshape_tools import build_onshape_tools
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall, ToolErrorCode
from solus_api.connectors.contracts import Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.registry import ConnectorRegistry
from solus_api.connectors.runtime import refresh_secret_ref
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import Project, Source, SourceStatus, SourceType, Team
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _connectors() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.register("onshape", lambda: OnshapeConnector(client_id="cid", client_secret="sec"))
    return registry


async def _seed(
    maker: async_sessionmaker[AsyncSession],
    *,
    connected: bool = True,
    status: SourceStatus = SourceStatus.CONNECTED,
    documents: list[str] | None = None,
) -> tuple[uuid.UUID, str]:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        secret_ref = f"source/{uuid.uuid4()}/onshape"
        db.add(
            Source(
                project_id=project.id,
                team_id=team.id,
                type=SourceType.ONSHAPE,
                name="onshape",
                status=status,
                # SOLUSDEV-168: tools refuse a document the project does not
                # track, so a fixture has to say what it tracks.
                config={"documents": ["d1"] if documents is None else documents},
                secret_ref=secret_ref if connected else None,
            )
        )
        await db.commit()
        return project.id, secret_ref


def _registry(
    maker: async_sessionmaker[AsyncSession], project_id: uuid.UUID, store: InMemorySecretStore
) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_onshape_tools(
        maker, project_id, secret_store=store, connectors=_connectors()
    ):
        registry.register(tool)
    return registry


# --------------------------------------------------------------- registration


async def test_every_operation_is_registered_as_a_tool(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, _ref = await _seed(maker)

    names = {d.name for d in _registry(maker, project_id, InMemorySecretStore()).list()}

    assert "onshape.list_documents" in names
    assert "onshape.get_body_details" in names


async def test_no_tool_exposes_a_tenant_argument(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Scope is constructor-bound. A model passing `project_id` must be rejected
    by the registry's schema validation, not silently honoured."""
    project_id, _ref = await _seed(maker)

    for descriptor in _registry(maker, project_id, InMemorySecretStore()).list():
        assert descriptor.params["additionalProperties"] is False
        assert "project_id" not in descriptor.params.get("properties", {})


async def test_read_tools_are_not_confirmation_gated(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, _ref = await _seed(maker)

    gated = {
        d.name
        for d in _registry(maker, project_id, InMemorySecretStore()).list()
        if d.requires_confirmation
    }

    # A3 added writes; nothing that only READS may ever ask for a confirmation,
    # or the gate stops meaning anything.
    assert gated == {"onshape.set_variable", "onshape.add_feature", "onshape.update_feature"}


# --------------------------------------------------------------- invocation


@respx.mock
async def test_a_read_reaches_onshape_with_the_stored_credentials(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    # Tracks what the fixture's document list actually returns, since the tool
    # now filters to the project's own documents.
    project_id, ref = await _seed(maker, documents=["dA", "dB"])
    store = InMemorySecretStore()
    await store.put(ref, "the-access-token")
    route = respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(200, json=DOCUMENT_LIST)
    )

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_documents", args={})
    )

    assert result.ok is True
    assert result.value is not None
    assert [d["id"] for d in result.value["documents"]] == ["dA", "dB"]
    assert route.calls[0].request.headers["authorization"] == "Bearer the-access-token"


@respx.mock
async def test_an_expired_token_is_refreshed_and_the_call_retried(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """A tool call is not a sync, but it needs the same refresh-once seam —
    Onshape access tokens live 60 minutes."""
    project_id, ref = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(ref, "stale")
    await store.put(refresh_secret_ref(ref), "the-refresh-token")
    respx.post("https://oauth.onshape.com/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "fresh", "refresh_token": "rot"})
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        side_effect=[
            httpx.Response(401),
            httpx.Response(200, json=DOCUMENT_LIST),
        ]
    )

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_documents", args={})
    )

    assert result.ok is True
    assert await store.get(ref) == "fresh"
    assert await store.get(refresh_secret_ref(ref)) == "rot"


@respx.mock
async def test_a_still_expired_token_is_unauthorized_not_a_crash(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(ref, "stale")
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(return_value=httpx.Response(401))

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_documents", args={})
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED


async def test_no_connected_onshape_source_is_a_typed_refusal(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, _ref = await _seed(maker, connected=False)

    result = await _registry(maker, project_id, InMemorySecretStore()).invoke(
        ToolCall(tool="onshape.list_documents", args={})
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND
    assert "Onshape" in result.error.message


async def test_a_disconnected_source_does_not_count_as_connected(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, _ref = await _seed(maker, status=SourceStatus.DISCONNECTED)

    result = await _registry(maker, project_id, InMemorySecretStore()).invoke(
        ToolCall(tool="onshape.list_documents", args={})
    )

    assert result.ok is False


async def test_another_projects_onshape_source_is_never_reachable(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The cross-tenant invariant: tools are built for ONE project, and a source
    in a different project must be invisible — no existence oracle."""
    _other_project, other_ref = await _seed(maker)
    project_id, _ref = await _seed(maker, connected=False)
    store = InMemorySecretStore()
    await store.put(other_ref, "someone-elses-token")

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_documents", args={})
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND


@respx.mock
async def test_a_bad_id_is_invalid_args_not_a_tool_error(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(ref, "at")

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_elements", args={"document_id": "../etc"})
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS


@respx.mock
async def test_an_unreachable_onshape_is_retryable(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(ref, "at")
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(side_effect=httpx.ConnectError("x"))

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_documents", args={})
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.retryable is True


@respx.mock
async def test_the_access_token_never_appears_in_a_tool_error(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(ref, "SENTINELTOKEN")
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(500, text="upstream detail")
    )

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_documents", args={})
    )

    assert result.error is not None
    assert "SENTINELTOKEN" not in result.error.message
    assert "upstream detail" not in result.error.message


@respx.mock
async def test_the_workspace_is_resolved_so_the_model_need_not_know_it(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(ref, "at")
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d1").mock(
        return_value=httpx.Response(200, json=WORKSPACE_INFO)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/d1/w/w1/elements").mock(
        return_value=httpx.Response(200, json=[])
    )

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_elements", args={"document_id": "d1"})
    )

    assert result.ok is True
    assert result.value is not None
    assert result.value["workspace_id"] == "w1"


async def test_tools_are_absent_without_a_secret_store(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Fail closed: no store means no way to authenticate, so the tools are not
    offered at all rather than registered and always failing."""
    project_id, _ref = await _seed(maker)

    assert build_onshape_tools(maker, project_id, secret_store=None, connectors=_connectors()) == []


def test_credentials_are_never_a_tool_argument() -> None:
    """A model must never be able to supply a token — the only path is the
    stored, refresh-managed one."""
    from solus_api.connectors.onshape_ops import READ_OPERATIONS

    forbidden = {"token", "access_token", "credentials", "authorization"}
    for operation in READ_OPERATIONS:
        assert not forbidden & set(operation.params.get("properties", {}))


async def test_credentials_are_resolved_per_call_not_cached_at_build(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Tools are built once per request but a token can rotate mid-request; the
    handler must read the store when it runs, not when it was constructed."""
    project_id, ref = await _seed(maker)
    store = InMemorySecretStore()
    tools = build_onshape_tools(maker, project_id, secret_store=store, connectors=_connectors())

    # Nothing was stored at build time; storing it now must be enough.
    await store.put(ref, "late-token")
    with respx.mock:
        route = respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
            return_value=httpx.Response(200, json=DOCUMENT_LIST)
        )
        tool = next(t for t in tools if t.descriptor.name == "onshape.list_documents")
        await tool.invoke({})

    assert route.calls[0].request.headers["authorization"] == "Bearer late-token"


def test_the_connector_http_helper_is_public_and_static() -> None:
    """A1 promoted these from `_`-private so the tool layer reuses ONE auth path
    instead of growing a second."""
    client = OnshapeConnector.http(Credentials(token="at"))

    assert client.headers["authorization"] == "Bearer at"


# --------------------------------------------------------------- writes (A3)


async def _seed_access(
    maker: async_sessionmaker[AsyncSession], access: str | None
) -> tuple[uuid.UUID, str]:
    """A project whose Onshape source was connected under a given grant."""
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        secret_ref = f"source/{uuid.uuid4()}/onshape"
        db.add(
            Source(
                project_id=project.id,
                team_id=team.id,
                type=SourceType.ONSHAPE,
                name="onshape",
                status=SourceStatus.CONNECTED,
                config=(
                    {"documents": ["d1"], "access": access} if access else {"documents": ["d1"]}
                ),
                secret_ref=secret_ref,
            )
        )
        await db.commit()
        return project.id, secret_ref


async def test_write_tools_are_registered_and_gated(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, _ref = await _seed_access(maker, "write")

    by_name = {d.name: d for d in _registry(maker, project_id, InMemorySecretStore()).list()}

    assert by_name["onshape.set_variable"].requires_confirmation is True
    assert by_name["onshape.add_feature"].requires_confirmation is True


async def test_a_read_only_grant_refuses_writes(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The connect-time choice is enforced server-side, not just in the picker.
    A read-only source must not be able to change a customer's model."""
    project_id, ref = await _seed_access(maker, "read")
    store = InMemorySecretStore()
    await store.put(ref, "t")
    registry = _registry(maker, project_id, store)

    result = await registry.invoke(
        ToolCall(
            tool="onshape.set_variable",
            args={"document_id": "d1", "element_id": "e1", "name": "w", "expression": "1 mm"},
        )
    )

    assert result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED


async def test_a_source_with_no_recorded_grant_refuses_writes(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Sources connected before the grant choice existed have no `access`. Fail
    closed: absent is read, never write."""
    project_id, ref = await _seed_access(maker, None)
    store = InMemorySecretStore()
    await store.put(ref, "t")

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(
            tool="onshape.set_variable",
            args={"document_id": "d1", "element_id": "e1", "name": "w", "expression": "1 mm"},
        )
    )

    assert result.error is not None
    assert result.error.code is ToolErrorCode.UNAUTHORIZED


async def test_a_read_only_grant_still_allows_reads(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref = await _seed_access(maker, "read")
    store = InMemorySecretStore()
    await store.put(ref, "t")

    with respx.mock:
        respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
            httpx.Response(200, json=DOCUMENT_LIST)
        )
        result = await _registry(maker, project_id, store).invoke(
            ToolCall(tool="onshape.list_documents", args={})
        )

    assert result.error is None


async def test_write_tools_expose_a_preview_for_the_confirmation_card(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The confirmation flow duck-types `preview` off the tool. Without it a user
    would be asked to approve a bare action name."""
    project_id, ref = await _seed_access(maker, "write")
    store = InMemorySecretStore()
    await store.put(ref, "t")
    tools = {
        t.descriptor.name: t
        for t in build_onshape_tools(
            maker, project_id, secret_store=store, connectors=_connectors()
        )
    }

    with respx.mock:
        respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d1").mock(
            httpx.Response(200, json=WORKSPACE_INFO)
        )
        respx.get(f"{ONSHAPE_API_BASE}/api/v6/variables/d/d1/w/w1/e/e1/variables").mock(
            httpx.Response(200, json=VARIABLES)
        )
        rows = await tools["onshape.set_variable"].preview(  # type: ignore[attr-defined]
            {"document_id": "d1", "element_id": "e1", "name": "width", "expression": "150 mm"}
        )

    # SOLUSDEV-168: WHICH document, by name, first — approving an edit to a
    # 24-hex id is approving an edit to a document you cannot identify.
    assert rows == [
        {"label": "document", "before": None, "after": "Rover chassis"},
        {"label": "width", "before": "120 mm", "after": "150 mm"},
    ]


async def test_read_tools_have_no_preview(maker: async_sessionmaker[AsyncSession]) -> None:
    project_id, _ref = await _seed_access(maker, "write")
    tools = {
        t.descriptor.name: t
        for t in build_onshape_tools(
            maker, project_id, secret_store=InMemorySecretStore(), connectors=_connectors()
        )
    }

    assert getattr(tools["onshape.list_documents"], "preview", None) is None


# ------------------------------------------- addressing: the project's own documents


@respx.mock
async def test_a_document_the_project_does_not_track_is_refused(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """THE addressing hole. `list_documents` used to list the customer's WHOLE
    Onshape account, so the model's menu was wider than the project — and the
    only thing between a mis-addressed write and their CAD was a confirmation
    card showing a 24-hex id no human can recognise."""
    project_id, ref = await _seed(maker)  # tracks d1
    store = InMemorySecretStore()
    await store.put(ref, "at")

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_elements", args={"document_id": "someoneelsesdoc"})
    )

    assert result.ok is False
    assert result.error is not None
    # NOT_FOUND, never UNAUTHORIZED: a permission error would confirm it exists.
    assert result.error.code is ToolErrorCode.NOT_FOUND
    assert result.error.retryable is False


@respx.mock
async def test_the_guard_covers_reads_not_only_writes(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Guarding only the write path would still let SOL read any document in the
    customer's account. Every operation routes through the same `_call`."""
    project_id, ref = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(ref, "at")
    registry = _registry(maker, project_id, store)

    for tool, args in (
        ("onshape.get_body_details", {"document_id": "untracked", "element_id": "e1"}),
        ("onshape.get_variables", {"document_id": "untracked", "element_id": "e1"}),
        ("onshape.get_feature_tree", {"document_id": "untracked", "element_id": "e1"}),
    ):
        result = await registry.invoke(ToolCall(tool=tool, args=args))
        assert result.error is not None, tool
        assert result.error.code is ToolErrorCode.NOT_FOUND, tool


@respx.mock
async def test_a_source_tracking_nothing_fails_closed(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """A connected but idle source tracks nothing, and "nothing tracked" must
    never read as "everything allowed"."""
    project_id, ref = await _seed(maker)
    store = InMemorySecretStore()
    await store.put(ref, "at")
    async with maker() as db:
        source = await db.scalar(select(Source).where(Source.project_id == project_id))
        assert source is not None
        source.config = {}
        await db.commit()

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_elements", args={"document_id": "d1"})
    )

    assert result.error is not None
    assert result.error.code is ToolErrorCode.NOT_FOUND
    assert "tracked" in result.error.message


@respx.mock
async def test_the_models_menu_is_the_project_not_the_account(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """`list_documents` is what the model picks from. Listing the whole Onshape
    account made its menu strictly wider than the project's scope."""
    project_id, ref = await _seed(maker, documents=["dA"])
    store = InMemorySecretStore()
    await store.put(ref, "at")
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(200, json=DOCUMENT_LIST)
    )

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_documents", args={})
    )

    assert result.ok is True
    assert result.value is not None
    # dB is in the account and NOT tracked, so the model never learns it exists.
    assert [d["id"] for d in result.value["documents"]] == ["dA"]


async def test_a_model_cannot_supply_its_own_document_menu(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The scope is bound by Solus code, the `get_entity` idiom. Every operation
    schema forbids extra properties, so `_documents` is unforgeable — a model
    that tries to widen its own menu is rejected at registry validation, before
    any handler runs."""
    project_id, ref = await _seed(maker, documents=["dA"])
    store = InMemorySecretStore()
    await store.put(ref, "at")

    result = await _registry(maker, project_id, store).invoke(
        ToolCall(tool="onshape.list_documents", args={"_documents": ["dA", "dB", "anything"]})
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS


async def test_a_failed_document_lookup_degrades_to_the_id_not_a_lost_card(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """A weaker card beats an unreachable action. If Onshape does not name the
    document, the row falls back to the id rather than the whole park failing."""
    project_id, ref = await _seed_access(maker, "write")
    store = InMemorySecretStore()
    await store.put(ref, "at")
    tools = {
        tool.descriptor.name: tool
        for tool in build_onshape_tools(
            maker, project_id, secret_store=store, connectors=_connectors()
        )
    }

    with respx.mock:
        # Same endpoint the workspace lookup uses, answering WITHOUT a name.
        respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d1").mock(
            httpx.Response(200, json={"id": "d1", "defaultWorkspace": {"id": "w1"}})
        )
        respx.get(f"{ONSHAPE_API_BASE}/api/v6/variables/d/d1/w/w1/e/e1/variables").mock(
            httpx.Response(200, json=VARIABLES)
        )
        rows = await tools["onshape.set_variable"].preview(  # type: ignore[attr-defined]
            {"document_id": "d1", "element_id": "e1", "name": "width", "expression": "150 mm"}
        )

    assert rows[0] == {"label": "document", "before": None, "after": "d1"}
    assert len(rows) == 2, "the operation's own diff must survive a naming failure"
