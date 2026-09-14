"""Feature specs are reusable only at a freshly observed immutable revision."""

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.onshape_ops import _get_feature_specs, _preview_add_feature

SPECS = {"featureSpecs": [{"featureType": "extrude", "parameters": []}]}
ARGS = {
    "document_id": "doc",
    "workspace_id": "workspace",
    "element_id": "element",
    "feature_type": "extrude",
    "name": "Feature",
    "parameters": {},
}


def connector(account: str = "account", cache: IntegrationCache | None = None) -> OnshapeConnector:
    return OnshapeConnector(
        client_id="id",
        client_secret="secret",
        account_ref=account,
        cache=cache or IntegrationCache(InMemoryCacheStore()),
    )


async def fetch(
    subject: OnshapeConnector, client: httpx.AsyncClient, revision="rev1", collection="partstudios"
):
    return await subject.immutable_feature_specs(
        client,
        document_id="doc",
        element_id="element",
        microversion_id=revision,
        collection=collection,
    )


async def test_spec_cache_isolates_account_revision_collection_and_mutable_result() -> None:
    cache = IntegrationCache(InMemoryCacheStore())
    first, other = connector(cache=cache), connector("other", cache)
    read = AsyncMock(return_value=SPECS)
    first.get_json = other.get_json = read
    async with httpx.AsyncClient() as client:
        result = await fetch(first, client)
        result["featureSpecs"].clear()
        assert await fetch(first, client) == SPECS
        await fetch(first, client, "rev2")
        await fetch(first, client, collection="assemblies")
        await fetch(other, client)
    assert read.await_count == 4
    assert all("/m/" in call.args[1] for call in read.await_args_list)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"featureSpecs": None},
        {"featureSpecs": [None]},
        {"featureSpecs": [], "errorEnum": "BAD"},
        {"featureSpecs": [], "incomplete": True},
        {"featureSpecs": [], "libraryVersion": "bad"},
        {"featureSpecs": [{"featureType": "x", "parameters": None}]},
        {"featureSpecs": [{"featureType": "x", "value": float("nan")}]},
    ],
)
async def test_malformed_specs_never_become_a_sticky_cache_entry(body: Any) -> None:
    subject = connector()
    read = AsyncMock(side_effect=[body, SPECS])
    subject.get_json = read
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError):
            await fetch(subject, client)
        assert await fetch(subject, client) == SPECS
    assert read.await_count == 2


@pytest.mark.parametrize("operation", [_get_feature_specs, _preview_add_feature])
async def test_standalone_operations_refresh_tree_but_reuse_revision_specs(operation) -> None:
    subject = connector()
    paths: list[str] = []
    revision = "rev1"

    async def read(client: httpx.AsyncClient, path: str, **kwargs: Any) -> Any:
        paths.append(path)
        if path.endswith("/features"):
            return {"features": [], "sourceMicroversion": revision}
        return SPECS

    subject.get_json = read
    async with httpx.AsyncClient() as client:
        await operation(subject, client, ARGS)
        await operation(subject, client, ARGS)
        revision = "rev2"
        await operation(subject, client, ARGS)
    assert sum(path.endswith("/features") for path in paths) == 3
    assert [path for path in paths if path.endswith("/featurespecs")] == [
        "/api/v6/partstudios/d/doc/m/rev1/e/element/featurespecs",
        "/api/v6/partstudios/d/doc/m/rev2/e/element/featurespecs",
    ]


@pytest.mark.parametrize(
    "module_name", ["test_onshape_sketch", "test_onshape_cut", "test_onshape_mates"]
)
async def test_geometry_preview_calls_shared_revision_spec_reader(
    module_name: str, monkeypatch
) -> None:
    import importlib

    fixture = importlib.import_module(module_name)
    subject = connector()
    reader = AsyncMock(return_value=fixture.specs())
    subject.immutable_feature_specs = reader

    async def read(client: httpx.AsyncClient, path: str, **kwargs: Any) -> Any:
        if path.endswith("/features"):
            return fixture.tree()
        if path.endswith("/bodydetails"):
            return fixture.geometry()
        if "/parts/" in path:
            return [{"partId": "part1", "name": "Bracket"}]
        if module_name == "test_onshape_mates":
            return fixture.fastened_frames()
        return fixture.assembly()

    subject.get_json = read
    if module_name == "test_onshape_mates":
        operation, args = fixture.MATE_OPERATIONS[1], fixture.ARGS[1]
    elif module_name == "test_onshape_cut":
        operation, args = fixture.CUT_OPERATIONS[0], fixture.ARGS
    else:
        operation, args = fixture.SKETCH_OPERATIONS[0], fixture.ARGS
    async with httpx.AsyncClient() as client:
        await operation.preview(subject, client, args)
    reader.assert_awaited_once()
    assert reader.await_args.kwargs["microversion_id"] == "before"
    assert reader.await_args.kwargs["collection"] == (
        "assemblies" if module_name == "test_onshape_mates" else "partstudios"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"featureSpecs": [], "isComplete": False},
        {"featureSpecs": [{"featureType": "extrude", "parameters": [{}]}]},
        {"featureSpecs": [{"featureType": "extrude", "parameters": [], "parameterIdToSpec": {}}]},
    ],
)
async def test_partial_or_ambiguous_parameter_table_is_refused_before_cache(body: Any) -> None:
    subject = connector()
    read = AsyncMock(side_effect=[body, SPECS])
    subject.get_json = read
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError):
            await fetch(subject, client)
        assert await fetch(subject, client) == SPECS
    assert read.await_count == 2


async def test_generic_add_reads_fresh_tree_before_shared_specs_and_verifies_write() -> None:
    from solus_api.connectors.onshape_ops import _add_feature

    subject = connector()
    feature = {
        "featureId": "created",
        "featureType": "extrude",
        "name": "Feature",
        "parameters": [],
    }
    before = {
        "features": [],
        "sourceMicroversion": "before",
        "serializationVersion": "1",
        "libraryVersion": 1,
    }
    after = {**before, "features": [feature], "featureStates": {"created": {"featureStatus": "OK"}}}
    order: list[str] = []
    trees = iter([before, after])

    async def tree_read(*args, **kwargs):
        order.append("tree")
        return next(trees)

    async def spec_read(*args, **kwargs):
        order.append("specs")
        assert kwargs["microversion_id"] == "before"
        return SPECS

    subject.get_json = tree_read
    subject.immutable_feature_specs = spec_read
    subject.post_json = AsyncMock(return_value={"feature": feature})
    async with httpx.AsyncClient() as client:
        result = await _add_feature(subject, client, ARGS)
    assert result["verified"] is True
    assert order == ["tree", "specs", "tree"]
    subject.post_json.assert_awaited_once()


async def test_vendor_variants_cache_without_weakening_selected_write() -> None:
    from solus_api.connectors.onshape_mates import _spec
    from solus_api.connectors.onshape_ops import _feature_parameters
    from test_onshape_mates import specs as mate_specs

    # Minimal vendor-shaped replace visibility variants; no customer CAD or generated IDs.
    variants = [
        {
            "parameterId": "replacingPart",
            "btType": "BTParameterSpecReferencePartStudio-1256",
            "visibilityCondition": {"btType": "BTParameterVisibilityCondition-177"},
        },
        {
            "parameterId": "replacingPart",
            "btType": "BTParameterSpecReferenceWithConfiguration-2950",
            "visibilityCondition": None,
        },
    ]
    unrelated = {"featureType": "replace", "parameters": variants}
    library = mate_specs()
    library["featureSpecs"].append(unrelated)
    subject = connector()
    reader = AsyncMock(return_value=library)
    subject.get_json = reader
    async with httpx.AsyncClient() as client:
        first = await fetch(subject, client, collection="assemblies")
        second = await fetch(subject, client, collection="assemblies")
    assert first == second == library
    assert first["featureSpecs"][-1]["parameters"] == variants
    assert _spec(second, "mate")
    reader.assert_awaited_once()
    with pytest.raises(ConnectorError, match="parameter identities"):
        _feature_parameters(second["featureSpecs"][-1], {})
