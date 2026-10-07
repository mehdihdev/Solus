"""ADR-038 section 5 - SOL reads through the mirror (T-C).

One SOL turn is one HTTP request, and `deps.get_sol_registry` builds ONE tool
registry per request, so the registry IS the turn: the memo that
`build_onshape_tools` creates lives and dies with it. These tests count the
requests that reach a fake provider transport (respx), because the contract is
a budget: the annual allowance is spent per successful provider call.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest
import respx
from fixtures.onshape_sample import ELEMENT_LIST, VARIABLES, WORKSPACE_INFO
from solus_api.agent.tools.onshape_tools import _prepare, build_onshape_tools
from solus_api.agent.tools.registry import ToolRegistry
from solus_api.agent.tools.shapes import ToolCall
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_read_cache import TurnReadMemo
from solus_api.connectors.registry import ConnectorContext, ConnectorRegistry
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.models import Project, Source, SourceStatus, SourceType, Team
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

API = f"{ONSHAPE_API_BASE}/api/v6"
MV = "mvaaaaaaaaaa"
FEATURES = {
    "sourceMicroversion": MV,
    "serializationVersion": "1.1.0",
    "libraryVersion": 1,
    "features": [
        {
            "message": {
                "name": "Extrude 1",
                "featureId": "F1",
                "featureType": "extrude",
                "parameters": [],
            }
        }
    ],
}
MASS = {"bodies": {"-all-": {"mass": [0.42, 0.42, 0.42]}}}


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class Harness:
    """A cache-equipped scoped connector, recording every ConnectorContext."""

    def __init__(self, cache: IntegrationCache | None = None) -> None:
        self.cache = cache or IntegrationCache(InMemoryCacheStore())
        self.contexts: list[ConnectorContext] = []

    def registry(self) -> ConnectorRegistry:
        connectors = ConnectorRegistry()
        connectors.register("onshape", lambda: OnshapeConnector(client_id="c", client_secret="s"))

        def scoped(ctx: ConnectorContext) -> OnshapeConnector:
            self.contexts.append(ctx)
            return OnshapeConnector(
                client_id="c",
                client_secret="s",
                cache=self.cache,
                account_ref=ctx.account_ref,
            )

        connectors.register_scoped("onshape", scoped)
        return connectors


async def _seed(
    maker: async_sessionmaker[AsyncSession],
    *,
    account: str = "acct-A",
    access: str = "write",
    cursor: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, str, uuid.UUID]:
    async with maker() as db:
        team = Team(name="T")
        db.add(team)
        await db.flush()
        project = Project(team_id=team.id, name="P")
        db.add(project)
        await db.flush()
        secret_ref = f"source/{uuid.uuid4()}/onshape"
        source = Source(
            project_id=project.id,
            team_id=team.id,
            type=SourceType.ONSHAPE,
            name="onshape",
            status=SourceStatus.CONNECTED,
            config={"documents": ["d1"], "access": access},
            cursor={"workspaces": {"d1": "w1"}} if cursor is None else cursor,
            account_external_id=account,
            secret_ref=secret_ref,
        )
        db.add(source)
        await db.commit()
        return project.id, secret_ref, source.id


async def _turn(
    maker: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    ref: str,
    harness: Harness,
) -> ToolRegistry:
    """A fresh registry: build_onshape_tools builds the turn memo, so this IS a turn."""
    store = InMemorySecretStore()
    await store.put(ref, "token")
    registry = ToolRegistry()
    for tool in build_onshape_tools(
        maker, project_id, secret_store=store, connectors=harness.registry()
    ):
        registry.register(tool)
    return registry


class Provider:
    """The fake Onshape. Every route is a counted respx route."""

    def __init__(self, mock: respx.MockRouter) -> None:
        self.document = mock.get(f"{API}/documents/d1").respond(200, json=WORKSPACE_INFO)
        self.probe = mock.get(f"{API}/documents/d/d1/w/w1/currentmicroversion").respond(
            200, json={"microversion": MV}
        )
        self.elements = mock.get(f"{API}/documents/d/d1/m/{MV}/elements").respond(
            200, json=ELEMENT_LIST
        )
        self.features = mock.get(f"{API}/partstudios/d/d1/m/{MV}/e/e1/features").respond(
            200, json=FEATURES
        )
        self.mass = mock.get(f"{API}/partstudios/d/d1/m/{MV}/e/e1/massproperties").respond(
            200, json=MASS
        )
        self.variables = mock.get(f"{API}/variables/d/d1/m/{MV}/e/e1/variables").respond(
            200, json=VARIABLES
        )
        self.live_variables = mock.get(f"{API}/variables/d/d1/w/w1/e/e1/variables").respond(
            200, json=VARIABLES
        )


GUIDE_TURN = (
    ("onshape.list_elements", {"document_id": "d1"}),
    ("onshape.get_feature_tree", {"document_id": "d1", "element_id": "e1"}),
    ("onshape.get_mass_properties", {"document_id": "d1", "element_id": "e1"}),
    ("onshape.get_variables", {"document_id": "d1", "element_id": "e1"}),
)


async def _run_guide_turn(registry: ToolRegistry) -> None:
    for name, args in GUIDE_TURN:
        result = await registry.invoke(ToolCall(tool=name, args=args))
        assert result.ok is True, (name, result.error)


# ------------------------------------------------------------ labels + purpose


async def test_read_and_write_tools_construct_the_agent_connector_with_labels(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    harness = Harness()
    store = InMemorySecretStore()
    await store.put(ref, "t")

    await _prepare(maker, project_id, store, harness.registry(), is_write=False)
    await _prepare(maker, project_id, store, harness.registry(), is_write=True)
    # build_onshape_tools -> _prepare is the only construction site.
    assert [(c.purpose, c.label) for c in harness.contexts] == [
        ("agent", "agent_read"),
        ("agent", "agent_write"),
    ]


# ----------------------------------------------------------- the Guide turn


@respx.mock
async def test_guide_turn_costs_one_probe_and_no_document_lookup(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    provider = Provider(respx.mock)

    await _run_guide_turn(await _turn(maker, project_id, ref, Harness()))

    assert provider.probe.call_count == 1
    assert provider.document.call_count == 0
    assert [
        provider.elements.call_count,
        provider.features.call_count,
        provider.mass.call_count,
        provider.variables.call_count,
    ] == [1, 1, 1, 1]
    assert len(respx.calls) == 5


@respx.mock
async def test_guide_turn_without_a_cursor_workspace_looks_the_document_up_once(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker, cursor={})
    provider = Provider(respx.mock)

    await _run_guide_turn(await _turn(maker, project_id, ref, Harness()))

    assert provider.document.call_count == 1
    assert provider.probe.call_count == 1


@respx.mock
async def test_a_warm_mirror_serves_the_next_turn_for_one_probe(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    provider = Provider(respx.mock)
    harness = Harness()
    await _run_guide_turn(await _turn(maker, project_id, ref, harness))

    # A new registry is a new turn: its memo is empty, the shared cache is not.
    await _run_guide_turn(await _turn(maker, project_id, ref, harness))

    assert provider.probe.call_count == 2
    assert len(respx.calls) == 5 + 1


@respx.mock
async def test_a_changed_microversion_is_a_new_key_never_a_stale_hit(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    provider = Provider(respx.mock)
    harness = Harness()
    await _run_guide_turn(await _turn(maker, project_id, ref, harness))
    provider.probe.respond(200, json={"microversion": "mvbbbbbbbbbb"})
    changed = respx.get(f"{API}/partstudios/d/d1/m/mvbbbbbbbbbb/e/e1/massproperties").respond(
        200, json={"bodies": {"-all-": {"mass": [9, 9, 9]}}}
    )

    registry = await _turn(maker, project_id, ref, harness)
    result = await registry.invoke(
        ToolCall(tool="onshape.get_mass_properties", args={"document_id": "d1", "element_id": "e1"})
    )

    assert changed.call_count == 1
    assert result.value == {"bodies": {"-all-": {"mass": [9, 9, 9]}}}


@respx.mock
async def test_a_hostile_microversion_never_reaches_a_url(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    provider = Provider(respx.mock)
    provider.probe.respond(200, json={"microversion": "../../x?y=1"})

    registry = await _turn(maker, project_id, ref, Harness())
    result = await registry.invoke(
        ToolCall(tool="onshape.get_variables", args={"document_id": "d1", "element_id": "e1"})
    )

    assert result.ok is False
    assert provider.variables.call_count == 0


# ----------------------------------------------------------------- paging


def _body_details(faces: int) -> dict[str, Any]:
    return {
        "bodies": [
            {
                "id": "B1",
                "faces": [{"id": f"F{i}", "area": 0.001 * i} for i in range(faces)],
                "edges": [],
                "vertices": [],
            }
        ],
        "microversionId": MV,
    }


@respx.mock
async def test_five_body_detail_pages_cost_one_payload_fetch(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    Provider(respx.mock)
    details = respx.get(f"{API}/partstudios/d/d1/m/{MV}/e/e1/bodydetails").respond(
        200, json=_body_details(5)
    )
    registry = await _turn(maker, project_id, ref, Harness())
    base = {"document_id": "d1", "element_id": "e1", "body_id": "B1", "collection": "faces"}

    first = await registry.invoke(ToolCall(tool="onshape.get_body_details", args=base))
    assert first.ok and first.value is not None
    fingerprint = first.value["fingerprint"]
    rest = await asyncio.gather(
        *(
            registry.invoke(
                ToolCall(
                    tool="onshape.get_body_details",
                    args={**base, "offset": offset, "expected_fingerprint": fingerprint},
                )
            )
            for offset in range(1, 5)
        )
    )

    assert all(result.ok for result in rest)
    pages = [first, *rest]
    assert [r.value["items"][0]["id"] for r in pages if r.value] == [
        "F0",
        "F1",
        "F2",
        "F3",
        "F4",
    ]
    assert details.call_count == 1
    assert details.calls[0].request.url.params["includeGeometricData"] == "true"


@respx.mock
async def test_paging_survives_a_payload_too_large_for_the_shared_cache(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """IntegrationCache declines storage above its byte cap; the in-turn memo
    still keeps later pages of that turn off the provider."""
    project_id, ref, _ = await _seed(maker)
    Provider(respx.mock)
    details = respx.get(f"{API}/partstudios/d/d1/m/{MV}/e/e1/bodydetails").respond(
        200, json=_body_details(5)
    )
    tiny = IntegrationCache(InMemoryCacheStore(), max_payload_bytes=64)
    registry = await _turn(maker, project_id, ref, Harness(tiny))
    base = {"document_id": "d1", "element_id": "e1", "body_id": "B1", "collection": "faces"}

    first = await registry.invoke(ToolCall(tool="onshape.get_body_details", args=base))
    assert first.ok and first.value is not None
    for offset in (1, 2):
        args = {**base, "offset": offset, "expected_fingerprint": first.value["fingerprint"]}
        assert (await registry.invoke(ToolCall(tool="onshape.get_body_details", args=args))).ok

    assert details.call_count == 1


@respx.mock
async def test_an_incomplete_vendor_payload_is_served_but_never_pinned_in_the_cache(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    provider = Provider(respx.mock)
    provider.mass.respond(200, json={"bodies": {}, "isComplete": False})
    harness = Harness()

    for _ in range(2):
        registry = await _turn(maker, project_id, ref, harness)
        await registry.invoke(
            ToolCall(
                tool="onshape.get_mass_properties",
                args={"document_id": "d1", "element_id": "e1"},
            )
        )

    assert provider.mass.call_count == 2


# ------------------------------------------------------------ list_documents

LISTING = [
    {"id": "d1", "name": "Rover chassis", "subtitle": "Ada"},
    {"id": "other", "name": "Someone else's", "subtitle": "Bob"},
]


@respx.mock
async def test_list_documents_with_a_warm_listing_makes_no_provider_call(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    harness = Harness()
    await harness.cache.fetch(
        harness.cache.listing_key("onshape", "acct-A"),
        ttl_seconds=3600,
        fetch=_async_value(LISTING),
    )
    walk = respx.get(f"{API}/documents").respond(200, json={"items": []})

    registry = await _turn(maker, project_id, ref, harness)
    result = await registry.invoke(ToolCall(tool="onshape.list_documents", args={}))

    assert walk.call_count == 0 and len(respx.calls) == 0
    # Still the PROJECT's menu, never the account's.
    assert result.value == {"documents": [{"id": "d1", "name": "Rover chassis", "owner": "Ada"}]}


@respx.mock
async def test_list_documents_cold_walks_once_then_serves_every_later_turn(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    harness = Harness()
    walk = respx.get(f"{API}/documents").respond(
        200,
        json={"items": [{"id": "d1", "name": "Rover chassis", "owner": {"name": "Ada"}}]},
    )

    for _ in range(3):
        registry = await _turn(maker, project_id, ref, harness)
        result = await registry.invoke(ToolCall(tool="onshape.list_documents", args={}))
        assert result.value == {
            "documents": [{"id": "d1", "name": "Rover chassis", "owner": "Ada"}]
        }

    assert walk.call_count == 1


@respx.mock
async def test_list_documents_refresh_is_explicit_and_cooldown_bounded(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    now = [1000.0]
    harness = Harness(IntegrationCache(InMemoryCacheStore(), clock=lambda: now[0]))
    walk = respx.get(f"{API}/documents").respond(
        200, json={"items": [{"id": "d1", "name": "Rover chassis"}]}
    )
    call = ToolCall(tool="onshape.list_documents", args={"refresh": True})

    await (await _turn(maker, project_id, ref, harness)).invoke(call)
    await (await _turn(maker, project_id, ref, harness)).invoke(call)
    assert walk.call_count == 1, "a refresh inside the cooldown is served from the cache"
    now[0] += harness.cache.listing_refresh_cooldown_seconds + 1
    await (await _turn(maker, project_id, ref, harness)).invoke(call)

    assert walk.call_count == 2


@respx.mock
async def test_list_documents_walk_stays_inside_the_page_bound(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    walk = respx.get(f"{API}/documents").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json={
                "items": [
                    {"id": f"p{request.url.params['offset']}x{i}", "name": "n"} for i in range(20)
                ]
            },
        )
    )

    registry = await _turn(maker, project_id, ref, Harness())
    result = await registry.invoke(ToolCall(tool="onshape.list_documents", args={}))

    assert result.ok is True
    assert walk.call_count == 10


def _async_value(value: Any) -> Any:
    async def fetch() -> Any:
        return value

    return fetch


# ------------------------------------------------------ writes stay live


def _variables_after(name: str, expression: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads(json.dumps(VARIABLES))
    for row in rows[0]["variables"]:
        if row["name"] == name:
            row["expression"] = expression
    return rows


@respx.mock
async def test_a_write_preview_names_the_document_without_a_lookup(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    provider = Provider(respx.mock)
    harness = Harness()
    await harness.cache.fetch(
        harness.cache.listing_key("onshape", "acct-A"),
        ttl_seconds=3600,
        fetch=_async_value(LISTING),
    )
    registry = await _turn(maker, project_id, ref, harness)
    tool = next(t for t in registry.tools() if t.descriptor.name == "onshape.set_variable")
    args = {"document_id": "d1", "element_id": "e1", "name": "width", "expression": "150 mm"}

    first = await tool.preview(args)  # type: ignore[attr-defined]
    second = await tool.preview(args)  # type: ignore[attr-defined]

    assert first[0] == second[0] == {"label": "document", "before": None, "after": "Rover chassis"}
    # The document NAME came from the listing, but the workspace is resolved live for a
    # write (one GET /documents/{d} per preview): the old `== 0` pinned the stale-hint bug.
    assert provider.document.call_count == 2
    assert provider.probe.call_count == 0, "previews are live reads, never the mirror"
    assert provider.live_variables.call_count == 2


@respx.mock
async def test_a_write_preview_uses_the_graph_name_when_there_is_no_listing(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    from solus_api.models import Domain, GraphEntity

    project_id, ref, source_id = await _seed(maker)
    provider = Provider(respx.mock)
    # The write's live workspace lookup now also reads the document, so for the graph name to
    # be the fallback under test Onshape's answer must carry no name of its own.
    provider.document.respond(200, json={"id": "d1", "defaultWorkspace": {"id": "w1"}})
    async with maker() as db:
        db.add(
            GraphEntity(
                project_id=project_id,
                kind="cad_document",
                domain=Domain.MECHANICAL,
                name="Graph named chassis",
                source_id=source_id,
                source_connector="onshape",
                external_ref="d1:document",
            )
        )
        await db.commit()
    registry = await _turn(maker, project_id, ref, Harness())
    tool = next(t for t in registry.tools() if t.descriptor.name == "onshape.set_variable")

    rows = await tool.preview(  # type: ignore[attr-defined]
        {"document_id": "d1", "element_id": "e1", "name": "width", "expression": "150 mm"}
    )

    assert rows[0]["after"] == "Graph named chassis"
    # One live default-workspace lookup for the write preview (was 0: the pinned bug).
    assert provider.document.call_count == 1


@respx.mock
async def test_a_write_does_its_own_live_pre_read_and_readback_with_a_warm_memo(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    provider = Provider(respx.mock)
    harness = Harness()
    registry = await _turn(maker, project_id, ref, harness)
    # Warm the turn: probe + immutable variables read are now memoised.
    warm = await registry.invoke(ToolCall(tool="onshape.get_variables", args=GUIDE_TURN[3][1]))
    assert warm.ok and provider.probe.call_count == 1 and provider.variables.call_count == 1

    provider.live_variables.mock(
        side_effect=[
            httpx.Response(200, json=VARIABLES),  # preview
            httpx.Response(200, json=VARIABLES),  # pre-write read
            httpx.Response(200, json=_variables_after("width", "150 mm")),  # readback
        ]
    )
    post = respx.post(f"{API}/variables/d/d1/w/w1/e/e1/variables").respond(204)
    args = {"document_id": "d1", "element_id": "e1", "name": "width", "expression": "150 mm"}
    tool = next(t for t in registry.tools() if t.descriptor.name == "onshape.set_variable")
    await tool.preview(args)  # type: ignore[attr-defined]
    written = await registry.invoke(ToolCall(tool="onshape.set_variable", args=args))

    assert written.ok is True, written.error
    assert provider.live_variables.call_count == 3
    assert post.call_count == 1
    # The memoised immutable read was never what a write consulted.
    assert provider.variables.call_count == 1

    # And the write retired the turn's probe: the next read re-asks Onshape
    # instead of serving a revision that no longer exists.
    provider.probe.respond(200, json={"microversion": "mvbbbbbbbbbb"})
    after = respx.get(f"{API}/variables/d/d1/m/mvbbbbbbbbbb/e/e1/variables").respond(
        200, json=_variables_after("width", "150 mm")
    )
    reread = await registry.invoke(ToolCall(tool="onshape.get_variables", args=GUIDE_TURN[3][1]))
    assert reread.ok and provider.probe.call_count == 2 and after.call_count == 1


@respx.mock
async def test_a_failed_write_also_retires_the_probe(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker)
    provider = Provider(respx.mock)
    registry = await _turn(maker, project_id, ref, Harness())
    await registry.invoke(ToolCall(tool="onshape.get_variables", args=GUIDE_TURN[3][1]))
    respx.post(f"{API}/variables/d/d1/w/w1/e/e1/variables").respond(500)
    args = {"document_id": "d1", "element_id": "e1", "name": "width", "expression": "150 mm"}
    tool = next(t for t in registry.tools() if t.descriptor.name == "onshape.set_variable")
    await tool.preview(args)  # type: ignore[attr-defined]

    failed = await registry.invoke(ToolCall(tool="onshape.set_variable", args=args))
    await registry.invoke(ToolCall(tool="onshape.get_variables", args=GUIDE_TURN[3][1]))

    assert failed.ok is False
    assert provider.probe.call_count == 2


# ------------------------------------------------------- isolation + memo


@respx.mock
async def test_two_accounts_with_the_same_document_id_never_share_reads(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_a, ref_a, _ = await _seed(maker, account="acct-A")
    project_b, ref_b, _ = await _seed(maker, account="acct-B")
    provider = Provider(respx.mock)
    shared = Harness()  # ONE cache for both accounts: keys alone must isolate them

    for project, ref in ((project_a, ref_a), (project_b, ref_b)):
        registry = await _turn(maker, project, ref, shared)
        assert (
            await registry.invoke(
                ToolCall(
                    tool="onshape.get_mass_properties",
                    args={"document_id": "d1", "element_id": "e1"},
                )
            )
        ).ok

    assert provider.probe.call_count == 2
    assert provider.mass.call_count == 2


async def test_the_memo_keys_every_entry_by_account() -> None:
    memo = TurnReadMemo()
    calls: list[str] = []

    async def make(account: str) -> str:
        calls.append(account)
        return f"value-{account}"

    one = await memo.once(("acct-A", "d1", "probe"), lambda: make("A"))
    two = await memo.once(("acct-B", "d1", "probe"), lambda: make("B"))
    again = await memo.once(("acct-A", "d1", "probe"), lambda: make("A2"))

    assert (one, two, again) == ("value-A", "value-B", "value-A")
    assert calls == ["A", "B"]


async def test_the_memo_expires_inside_sixty_seconds_and_refuses_a_longer_ttl() -> None:
    now = [0.0]
    memo = TurnReadMemo(clock=lambda: now[0])
    runs: list[int] = []

    async def make() -> int:
        runs.append(1)
        return len(runs)

    assert await memo.once(("a", "d", "probe"), make) == 1
    now[0] = 59.0
    assert await memo.once(("a", "d", "probe"), make) == 1
    now[0] = 61.0
    assert await memo.once(("a", "d", "probe"), make) == 2
    with pytest.raises(ValueError):
        TurnReadMemo(ttl_seconds=61)


async def test_the_memo_collapses_concurrent_callers_and_never_memoises_a_failure() -> None:
    memo = TurnReadMemo()
    gate = asyncio.Event()
    runs: list[int] = []

    async def slow() -> str:
        runs.append(1)
        await gate.wait()
        return "ok"

    tasks = [asyncio.create_task(memo.once(("a", "d", "probe"), slow)) for _ in range(5)]
    await asyncio.sleep(0)
    gate.set()
    assert await asyncio.gather(*tasks) == ["ok"] * 5
    assert len(runs) == 1

    attempts: list[int] = []

    async def flaky() -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectorError("api_error", "boom")
        return "fine"

    with pytest.raises(ConnectorError):
        await memo.once(("a", "d2", "probe"), flaky)
    assert await memo.once(("a", "d2", "probe"), flaky) == "fine"


async def test_forgetting_a_document_drops_only_its_probes() -> None:
    memo = TurnReadMemo()

    async def make(value: str) -> str:
        return value

    await memo.once(("a", "d1", "probe", "w1"), lambda: make("mv1"))
    await memo.once(("a", "d1", "read", MV, "/p"), lambda: make("kept"))
    await memo.once(("a", "d2", "probe", "w1"), lambda: make("other-doc"))

    memo.forget_probes("d1")

    assert await memo.once(("a", "d1", "probe", "w1"), lambda: make("mv2")) == "mv2"
    assert await memo.once(("a", "d1", "read", MV, "/p"), lambda: make("x")) == "kept"
    assert await memo.once(("a", "d2", "probe", "w1"), lambda: make("x")) == "other-doc"


@respx.mock
async def test_a_two_write_build_turn_spends_only_the_live_reads_and_posts(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Per write: park preview + decide preview (one live read each), then the
    pre-write read, the POST and the readback. A write resolves its workspace live,
    so each of those three tool calls spends one `GET /documents/{d}`; no name lookup,
    no probe. (Before ADR-038: 10 per write, 20 for the turn.)"""
    project_id, ref, _ = await _seed(maker)
    harness = Harness()
    await harness.cache.fetch(
        harness.cache.listing_key("onshape", "acct-A"),
        ttl_seconds=3600,
        fetch=_async_value(LISTING),
    )
    table = [dict(row) for row in VARIABLES[0]["variables"]]

    def read(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"variables": table}])

    def write(request: httpx.Request) -> httpx.Response:
        table[:] = [{**entry, "value": "0 m"} for entry in json.loads(request.content)]
        return httpx.Response(204)

    document = respx.get(f"{API}/documents/d1").respond(200, json=WORKSPACE_INFO)
    probe = respx.get(f"{API}/documents/d/d1/w/w1/currentmicroversion").respond(
        200, json={"microversion": MV}
    )
    respx.get(f"{API}/variables/d/d1/w/w1/e/e1/variables").mock(side_effect=read)
    respx.post(f"{API}/variables/d/d1/w/w1/e/e1/variables").mock(side_effect=write)
    registry = await _turn(maker, project_id, ref, harness)
    tool = next(t for t in registry.tools() if t.descriptor.name == "onshape.set_variable")

    for name, expression in (("width", "150 mm"), ("count", "6")):
        args = {"document_id": "d1", "element_id": "e1", "name": name, "expression": expression}
        await tool.preview(args)  # type: ignore[attr-defined]
        await tool.preview(args)  # type: ignore[attr-defined]
        result = await registry.invoke(ToolCall(tool="onshape.set_variable", args=args))
        assert result.ok is True, result.error

    # 3 live workspace lookups per write (two previews + the invocation): was 0, which
    # let a write target a stale cursor workspace.
    assert document.call_count == 6 and probe.call_count == 0
    assert len(respx.calls) == 16


@respx.mock
async def test_a_stale_recorded_workspace_heals_once_and_the_turn_reads_on(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id, ref, _ = await _seed(maker, cursor={"workspaces": {"d1": "wstale"}})
    provider = Provider(respx.mock)
    stale = respx.get(f"{API}/documents/d/d1/w/wstale/currentmicroversion").respond(404)

    await _run_guide_turn(await _turn(maker, project_id, ref, Harness()))

    assert stale.call_count == 1
    assert provider.document.call_count == 1
    assert provider.probe.call_count == 1
    assert provider.variables.call_count == 1


@respx.mock
async def test_assembly_feature_pages_fetch_the_definition_and_tree_once(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    from test_onshape_assembly_read import fixture

    root, tree = fixture()
    project_id, ref, _ = await _seed(maker)
    Provider(respx.mock)
    url = f"{API}/assemblies/d/d1/m/{MV}/e/e1"
    definition = respx.get(url).respond(200, json=root)
    health = respx.get(f"{url}/features").respond(200, json=tree)
    registry = await _turn(maker, project_id, ref, Harness())
    args = {"document_id": "d1", "element_id": "e1", "view": "features"}

    for _ in range(3):
        result = await registry.invoke(ToolCall(tool="onshape.get_assembly_definition", args=args))
        assert result.ok is True, result.error

    assert definition.call_count == health.call_count == 1


# ------------------------------------------- writes resolve the workspace live


def _info_with_workspace(workspace: str) -> dict[str, Any]:
    return {**WORKSPACE_INFO, "defaultWorkspace": {"id": workspace}}


@respx.mock
async def test_a_write_targets_the_live_default_workspace_not_the_cursor_hint(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The default workspace changed after the last sync: the cursor still says w1.
    A write must act on what Onshape says NOW, never on the recorded hint."""
    project_id, ref, _ = await _seed(maker)
    respx.get(f"{API}/documents/d1").respond(200, json=_info_with_workspace("wlive0000001"))
    live_get = respx.get(f"{API}/variables/d/d1/w/wlive0000001/e/e1/variables").respond(
        200, json=VARIABLES
    )
    stale_get = respx.get(f"{API}/variables/d/d1/w/w1/e/e1/variables").respond(200, json=VARIABLES)
    stale_post = respx.post(f"{API}/variables/d/d1/w/w1/e/e1/variables").respond(204)
    live_post = respx.post(f"{API}/variables/d/d1/w/wlive0000001/e/e1/variables").respond(204)
    registry = await _turn(maker, project_id, ref, Harness())
    args = {"document_id": "d1", "element_id": "e1", "name": "width", "expression": "150 mm"}
    tool = next(t for t in registry.tools() if t.descriptor.name == "onshape.set_variable")

    await tool.preview(args)  # type: ignore[attr-defined]
    await registry.invoke(ToolCall(tool="onshape.set_variable", args=args))

    assert stale_get.call_count == 0 and stale_post.call_count == 0
    assert live_get.call_count >= 1 and live_post.call_count == 1


@respx.mock
async def test_a_write_ignores_a_memoised_workspace_override_from_an_earlier_read(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """A read that healed a stale hint memoises an override for the turn; a write in the same
    turn still asks Onshape rather than trusting that memo."""
    from solus_api.connectors.onshape_ops import workspace_for
    from solus_api.connectors.onshape_read_cache import (
        ReadScope,
        TurnReadMemo,
        bind_read_scope,
    )

    document = respx.get(f"{API}/documents/d1").respond(
        200, json=_info_with_workspace("wnow00000001")
    )
    memo = TurnReadMemo()
    memo.remember(("acct-A", "d1", "workspace-override"), "wmemo0000001")
    scope = ReadScope(memo=memo, account_ref="acct-A", workspaces={"d1": "w1"}, is_write=True)
    connector = OnshapeConnector(client_id="c", client_secret="s")

    async with httpx.AsyncClient(base_url=ONSHAPE_API_BASE) as client:
        with bind_read_scope(scope):
            resolved = await workspace_for(connector, client, {"document_id": "d1"})
        with bind_read_scope(ReadScope(memo, "acct-A", {"d1": "w1"}, is_write=False)):
            read_resolved = await workspace_for(connector, client, {"document_id": "d1"})

    assert resolved == "wnow00000001"
    assert document.call_count == 1
    assert read_resolved == "wmemo0000001"  # reads keep the override: unchanged behaviour
