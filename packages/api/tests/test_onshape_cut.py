"""Scoped cut creation validates live identity and never replays an uncertain write."""

import copy
import json
import re
from typing import Any

import httpx
import pytest
import respx
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_confirmation import PreviewBinding
from solus_api.connectors.onshape_cut import CUT_OPERATIONS

ARGS = {
    "document_id": "document",
    "workspace_id": "workspace",
    "element_id": "studio",
    "sketch_feature_id": "sketch1",
    "part_id": "part1",
    "name": "Sensor recess",
    "depth_mm": 2.5,
    "opposite_direction": True,
}
BASE = f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/document/w/workspace/e/studio"
PARTS = f"{ONSHAPE_API_BASE}/api/v6/parts/d/document/w/workspace/e/studio"
SKETCH = {
    "btType": "BTMSketch-151",
    "featureType": "newSketch",
    "featureId": "sketch1",
    "name": "Sensor footprint",
    "suppressed": False,
    "parameters": [],
}


def specs() -> dict[str, Any]:
    parameters = []
    for identity, kind, enum, value in [
        ("bodyType", "Enum", "ExtendedToolBodyType", "SOLID"),
        ("operationType", "Enum", "NewBodyOperationType", "REMOVE"),
        ("endBound", "Enum", "BoundingType", "BLIND"),
        ("entities", "Query", None, None),
        ("booleanScope", "Query", None, None),
        ("depth", "Quantity", None, None),
        ("oppositeDirection", "Boolean", None, None),
        ("defaultScope", "Boolean", None, None),
    ]:
        suffix = {"Enum": 171, "Query": 174, "Quantity": 173, "Boolean": 170}[kind]
        parameters.append(
            {
                "parameterId": identity,
                "btType": f"BTParameterSpec{kind}-{suffix}",
                **({"quantityType": "LENGTH"} if kind == "Quantity" else {}),
                **({"enumName": enum, "options": [value], "namespace": ""} if enum else {}),
            }
        )
    return {"featureSpecs": [{"featureType": "extrude", "namespace": "", "parameters": parameters}]}


def tree(features: list[dict[str, Any]] | None = None, micro: str = "before") -> dict[str, Any]:
    features = [copy.deepcopy(SKETCH)] if features is None else features
    return {
        "features": features,
        "sourceMicroversion": micro,
        "serializationVersion": "1.2.4",
        "libraryVersion": 2399,
        "featureStates": {
            feature["featureId"]: {"featureStatus": "OK", "inactive": False} for feature in features
        },
    }


async def run(args: dict[str, Any] | None = None, *, preview: bool = False) -> Any:
    operation = CUT_OPERATIONS[0]
    step = operation.preview if preview else operation.run
    assert step is not None
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    async with connector.http(Credentials(token="fixture")) as client:
        raw = ARGS if args is None else args
        if preview:
            return await step(connector, client, raw)
        assert operation.preview is not None
        rows = await operation.preview(connector, client, raw)
        binding = PreviewBinding()
        binding.remember(raw, rows)
        with binding.execution(raw):
            return await step(connector, client, raw)


def reads() -> None:
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=specs()
    )
    respx.get(PARTS).respond(200, json=[{"partId": "part1", "name": "Bracket"}])
    respx.get(f"{BASE}/features").respond(200, json=tree())


@respx.mock
async def test_preview_is_complete_read_only_and_microversion_sensitive() -> None:
    reads()
    first = await run(preview=True)
    respx.get(f"{BASE}/features").respond(200, json=tree(micro="changed"))
    second = await run(preview=True)
    assert first != second
    for value in (
        "Sensor recess",
        "Sensor footprint",
        "sketch1",
        "part1",
        "Bracket",
        "2.5",
        "before",
        "all sketch regions",
    ):
        assert value.lower() in str(first).lower()
    assert all(call.request.method == "GET" for call in respx.calls)
    assert CUT_OPERATIONS[0].requires_confirmation
    assert "write" in CUT_OPERATIONS[0].tags


@respx.mock
async def test_cut_has_exact_scope_and_echoes_microversion_then_verifies_readback() -> None:
    reads()
    payloads: list[dict[str, Any]] = []

    def posted(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        feature = {**payload["feature"], "featureId": "cut1"}
        respx.get(f"{BASE}/features").respond(200, json=tree([SKETCH, feature], "after"))
        return httpx.Response(
            200, json={"feature": feature, "featureState": {"featureStatus": "OK"}}
        )

    post = respx.post(f"{BASE}/features").mock(side_effect=posted)
    result = await run()
    assert result["feature_id"] == "cut1" and post.call_count == 1
    payload = payloads[0]
    assert payload["sourceMicroversion"] == "before" and payload["rejectMicroversionSkew"] is True
    fields = {p["parameterId"]: p for p in payload["feature"]["parameters"]}
    assert fields["operationType"]["value"] == "REMOVE"
    assert fields["defaultScope"]["value"] is False
    assert fields["depth"]["expression"] == "2.5 mm"
    assert fields["oppositeDirection"]["value"] is True
    assert fields["entities"]["queries"] == [
        {"btType": "BTMIndividualSketchRegionQuery-140", "featureId": "sketch1"}
    ]
    assert fields["booleanScope"]["queries"] == [
        {"btType": "BTMIndividualQuery-138", "deterministicIds": ["part1"]}
    ]


@pytest.mark.parametrize("active_offset", [True, False])
@respx.mock
async def test_additional_cut_parameters_must_match_observed_defaults(active_offset: bool) -> None:
    reads()
    schema = specs()
    default = {
        "btType": "BTMParameterBoolean-144",
        "parameterId": "startOffset",
        "value": False,
        "nodeId": "spec-node",
    }
    schema["featureSpecs"][0]["parameters"].append(
        {
            "parameterId": "startOffset",
            "btType": "BTParameterSpecBoolean-170",
            "defaultValue": default,
        }
    )
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=schema
    )

    def posted(request: httpx.Request) -> httpx.Response:
        feature = {**json.loads(request.content)["feature"], "featureId": "cut1"}
        feature["parameters"].append({**default, "value": active_offset, "nodeId": "result-node"})
        respx.get(f"{BASE}/features").respond(200, json=tree([SKETCH, feature], "after"))
        return httpx.Response(200, json={"feature": feature})

    post = respx.post(f"{BASE}/features").mock(side_effect=posted)
    if active_offset:
        with pytest.raises(ConnectorError) as error:
            await run()
        assert error.value.code == "mutation_unverified"
    else:
        assert (await run())["feature_id"] == "cut1"
    assert post.call_count == 1


@pytest.mark.parametrize(
    "change",
    [
        {"depth_mm": 0},
        {"depth_mm": float("inf")},
        {"depth_mm": True},
        {"depth_mm": "2"},
        {"depth_mm": 10001},
        {"opposite_direction": 1},
        {"part_id": "../part"},
        {"name": ""},
        {"name": "x" * 121},
        {"raw_query": "anything"},
    ],
)
@respx.mock
async def test_invalid_input_refuses_before_network(change: dict[str, Any]) -> None:
    with pytest.raises(ConnectorError):
        await run({**ARGS, **change})
    assert not respx.calls


@pytest.mark.parametrize(
    "failure",
    [
        "suppressed",
        "wrong_type",
        "duplicate_sketch",
        "missing_part",
        "duplicate_part",
        "missing_spec",
        "wrong_spec",
        "custom_spec",
        "duplicate_spec",
        "missing_micro",
        "bad_sketch_state",
    ],
)
@respx.mock
async def test_missing_ambiguous_or_unusable_live_identity_refuses_without_post(
    failure: str,
) -> None:
    reads()
    current = tree()
    if failure == "suppressed":
        current["features"][0]["suppressed"] = True
    elif failure == "wrong_type":
        current["features"][0]["featureType"] = "extrude"
    elif failure == "duplicate_sketch":
        current["features"].append(copy.deepcopy(SKETCH))
    elif failure == "missing_micro":
        current.pop("sourceMicroversion")
    elif failure == "bad_sketch_state":
        current["featureStates"]["sketch1"]["featureStatus"] = "ERROR"
    elif failure in ("missing_part", "duplicate_part"):
        respx.get(PARTS).respond(
            200, json=[] if failure == "missing_part" else [{"partId": "part1"}] * 2
        )
    else:
        observed = specs()
        if failure == "missing_spec":
            observed["featureSpecs"][0]["parameters"].pop()
        elif failure == "wrong_spec":
            observed["featureSpecs"][0]["parameters"][0]["enumName"] = "Wrong"
        elif failure == "custom_spec":
            observed["featureSpecs"][0]["namespace"] = "custom"
        else:
            observed["featureSpecs"].append(copy.deepcopy(observed["featureSpecs"][0]))
        respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
            200, json=observed
        )
    respx.get(f"{BASE}/features").respond(200, json=current)
    with pytest.raises(ConnectorError):
        await run()
    assert all(call.request.method == "GET" for call in respx.calls)


@pytest.mark.parametrize(
    "failure",
    [
        "post_timeout",
        "post_401",
        "read_401",
        "missing_feature",
        "error_state",
        "changed_scope",
        "old_id",
    ],
)
@respx.mock
async def test_uncertain_mutation_is_nonretryable_and_never_posts_twice(failure: str) -> None:
    reads()

    def posted(request: httpx.Request) -> httpx.Response:
        if failure == "post_timeout":
            raise httpx.ReadTimeout("fixture", request=request)
        if failure == "post_401":
            return httpx.Response(401)
        feature = {
            **json.loads(request.content)["feature"],
            "featureId": "sketch1" if failure == "old_id" else "cut1",
        }
        after = tree([SKETCH, feature], "after")
        if failure == "missing_feature":
            after = tree(micro="after")
        if failure == "error_state":
            after["featureStates"]["cut1"]["featureStatus"] = "ERROR"
        if failure == "changed_scope":
            next(p for p in feature["parameters"] if p["parameterId"] == "defaultScope")[
                "value"
            ] = True
        respx.get(f"{BASE}/features").respond(401 if failure == "read_401" else 200, json=after)
        return httpx.Response(
            200, json={"feature": feature, "featureState": {"featureStatus": "OK"}}
        )

    post = respx.post(f"{BASE}/features").mock(side_effect=posted)
    with pytest.raises(ConnectorError) as error:
        await run()
    assert error.value.code == "mutation_unverified" and post.call_count == 1


@respx.mock
async def test_cut_depth_keeps_supplied_finite_precision() -> None:
    reads()
    depth = 2.123456789
    preview = await run({**ARGS, "depth_mm": depth}, preview=True)
    assert f"{depth} mm" in str(preview)


@respx.mock
async def test_preview_binds_complete_live_builtin_specification() -> None:
    reads()
    first = await run(preview=True)
    changed = specs()
    changed["featureSpecs"][0]["parameters"][0]["options"].append("THIN")
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=changed
    )
    second = await run(preview=True)
    assert first != second


@respx.mock
async def test_bound_tool_metadata_is_internal_not_a_model_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid
    from types import SimpleNamespace
    from typing import cast
    from unittest.mock import AsyncMock

    import jsonschema
    from solus_api.agent.tools import onshape_tools
    from solus_api.agent.tools.tool import InProcessTool
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.connectors.secrets import InMemorySecretStore
    from sqlalchemy.ext.asyncio import async_sessionmaker

    reads()
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    credentials = Credentials(token="fixture")
    source = SimpleNamespace(config={"documents": ["document"]})
    monkeypatch.setattr(
        onshape_tools, "_prepare", AsyncMock(return_value=(connector, credentials, source))
    )

    async def invoke(*args: Any, **kwargs: Any) -> Any:
        return await args[6](credentials)

    monkeypatch.setattr(onshape_tools, "_run_with_refresh", invoke)
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/document").respond(
        200, json={"name": "Fixture"}
    )
    tool = cast(
        InProcessTool,
        onshape_tools._build_tool(
            CUT_OPERATIONS[0],
            async_sessionmaker(),
            uuid.uuid4(),
            InMemorySecretStore(),
            ConnectorRegistry(),
        ),
    )
    assert await tool.preview(ARGS)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**ARGS, "_documents": ["document"]}, CUT_OPERATIONS[0].params)


@respx.mock
async def test_live_feature_ids_allow_underscores_and_hyphens() -> None:
    reads()
    sketch = {**SKETCH, "featureId": "actual_sketch-1"}
    respx.get(f"{BASE}/features").respond(200, json=tree([sketch]))
    assert await run({**ARGS, "sketch_feature_id": "actual_sketch-1"}, preview=True)


@respx.mock
async def test_generated_spec_node_ids_do_not_stale_cut_preview() -> None:
    reads()
    before = await run(preview=True)
    spec = specs()
    spec["featureSpecs"][0]["parameters"][0]["nodeId"] = "generatedPerRequest"
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=spec
    )
    assert await run(preview=True) == before


@respx.mock
async def test_cut_preview_ignores_transport_version_but_not_library_version() -> None:
    reads()
    before = await run(preview=True)
    changed = tree()
    changed["serializationVersion"] = "1.2.0"
    respx.get(f"{BASE}/features").respond(200, json=changed)
    assert await run(preview=True) == before
    changed["libraryVersion"] += 1
    respx.get(f"{BASE}/features").respond(200, json=changed)
    assert await run(preview=True) != before
