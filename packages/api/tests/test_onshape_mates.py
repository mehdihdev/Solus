"""Assembly authoring binds observed root identities before any external mutation."""

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
from solus_api.connectors.onshape_mates import MATE_OPERATIONS

BASE = f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/document/w/workspace/e/assembly"
DONOR = f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/donor/m/pinned/e/studio/bodydetails"
COMMON = {
    "document_id": "document",
    "workspace_id": "workspace",
    "element_id": "assembly",
    "name": "Fixture",
    "_documents": ["document", "donor"],
}
ARGS = [
    {**COMMON, "instance_id": "part+1", "face_id": "face1"},
    {**COMMON, "first_connector_id": "connector_1", "second_connector_id": "connector-2"},
]


def test_existing_healthy_opaque_feature_ids_can_be_used_as_mate_inputs() -> None:
    from solus_api.connectors.onshape_cut import _features, _healthy
    from solus_api.connectors.onshape_mates import RevoluteMateArgs

    feature = {"featureId": "connector+/", "featureType": "mateConnector", "suppressed": False}
    body = {"features": [feature], "featureStates": {"connector+/": {"featureStatus": "OK"}}}
    assert _features(body) == [feature]
    assert _healthy(body, feature)
    args = RevoluteMateArgs.model_validate(
        {
            "document_id": "document",
            "element_id": "assembly",
            "name": "Joint",
            "first_connector_id": "connector+/",
            "second_connector_id": "other+/",
        }
    )
    assert args.first_connector_id == "connector+/"


def tree() -> dict[str, Any]:
    features = [
        {
            "featureId": identity,
            "featureType": "mateConnector",
            "name": identity,
            "suppressed": False,
            "parameters": [],
        }
        for identity in ("connector_1", "connector-2")
    ]
    return {
        "features": features,
        "isComplete": True,
        "sourceMicroversion": "before",
        "serializationVersion": "1.2.4",
        "libraryVersion": 2399,
        "featureStates": {f["featureId"]: {"featureStatus": "OK"} for f in features},
    }


def assembly() -> dict[str, Any]:
    return {
        "rootAssembly": {
            "documentMicroversion": "before",
            "configuration": "default",
            "instances": [
                {
                    "id": "part+1",
                    "type": "Part",
                    "suppressed": False,
                    "documentId": "donor",
                    "elementId": "studio",
                    "partId": "part1",
                    "documentMicroversion": "pinned",
                    "configuration": "default",
                }
            ],
            "occurrences": [
                {"path": ["part+1"], "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
            ],
        }
    }


def specs() -> dict[str, Any]:
    result = []
    for kind, enum_id, enum_name, value, query, picks, flags in [
        (
            "mateConnector",
            "originType",
            "Origin type",
            "ON_ENTITY",
            "originQuery",
            1,
            {"realign": False, "transform": False, "flipPrimary": False},
        ),
        (
            "mate",
            "mateType",
            "Mate type",
            "FASTENED",
            "mateConnectorsQuery",
            2,
            {
                "mateOffsetEnabled": False,
                "limitsEnabled": False,
                "functionalconnection": False,
                "primaryAxisAlignment": True,
            },
        ),
    ]:
        params = [
            {
                "parameterId": enum_id,
                "btType": "BTParameterSpecEnum-171",
                "enumName": enum_name,
                "namespace": "",
                "options": [value],
            },
            {"parameterId": query, "btType": "BTParameterSpecQuery-174", "maxNumberOfPicks": picks},
        ]
        params += [
            {
                "parameterId": key,
                "btType": "BTParameterSpecBoolean-170",
                "defaultValue": {"value": val},
            }
            for key, val in flags.items()
        ]
        if kind == "mate":
            params.append(
                {
                    "parameterId": "secondaryAxisAlignment",
                    "btType": "BTParameterSpecEnum-171",
                    "enumName": "Reorient secondary axis",
                    "namespace": "",
                    "options": ["PLUS_X"],
                }
            )
        result.append({"featureType": kind, "namespace": "", "parameters": params})
    return {"featureSpecs": result}


def fastened_frames():
    payload = assembly()
    root = payload["rootAssembly"]
    root["instances"].append({**root["instances"][0], "id": "part+2"})
    root["occurrences"].append({**root["occurrences"][0], "path": ["part+2"]})
    root["features"] = [
        {
            "id": identity,
            "featureType": "mateConnector",
            "suppressed": False,
            "featureData": {
                "occurrence": [f"part+{i + 1}"],
                "mateConnectorCS": {
                    "origin": [0, 0, 0],
                    "xAxis": [1, 0, 0],
                    "yAxis": [0, -1 if i else 1, 0],
                    "zAxis": [0, 0, -1 if i else 1],
                },
            },
        }
        for i, identity in enumerate(("connector_1", "connector-2"))
    ]
    return payload


@respx.mock
async def test_fastened_preview_selects_measured_secondary_axis():
    reads()
    payload = fastened_frames()
    cs = payload["rootAssembly"]["features"][1]["featureData"]["mateConnectorCS"]
    cs.update(xAxis=[0, 1, 0], yAxis=[1, 0, 0])
    respx.get(BASE).respond(200, json=payload)
    schema = specs()
    schema["featureSpecs"][1]["parameters"][-1]["options"].append("PLUS_Y")
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=schema
    )
    preview = await call(1, preview=True)
    assert "PLUS_Y" in json.dumps(preview)


@respx.mock
async def test_fastened_missing_measured_frames_refuses_before_write():
    reads()
    respx.get(BASE).respond(200, json=assembly())
    with pytest.raises(ConnectorError):
        await call(1, preview=True)
    assert all(row.request.method == "GET" for row in respx.calls)


def reads() -> None:
    respx.get(BASE).respond(200, json=fastened_frames())
    respx.get(f"{BASE}/features").respond(200, json=tree())
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=specs()
    )
    respx.get(DONOR).respond(
        200,
        json={
            "microversionId": {"btType": "BTMicroversionId-366", "theId": "pinned"},
            "bodies": [
                {
                    "id": "part1",
                    "type": "solid",
                    "faces": [
                        {
                            "id": "face1",
                            "surface": {"type": "plane", "origin": [0, 0, 0], "normal": [0, 0, 1]},
                        }
                    ],
                }
            ],
        },
    )


async def call(
    index: int, *, args: dict[str, Any] | None = None, preview: bool = False, bound: bool = True
) -> Any:
    operation = MATE_OPERATIONS[index]
    raw = copy.deepcopy(ARGS[index] if args is None else args)
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    async with connector.http(Credentials(token="fixture")) as client:
        assert operation.preview
        if preview:
            return await operation.preview(connector, client, raw)
        if not bound:
            return await operation.run(connector, client, raw)
        rows = await operation.preview(connector, client, raw)
        binding = PreviewBinding()
        binding.remember(raw, rows)
        with binding.execution(raw):
            return await operation.run(connector, client, raw)


@pytest.mark.parametrize("index", [0, 1])
@respx.mock
async def test_complete_preview_and_verified_write(index: int) -> None:
    reads()
    rows = await call(index, preview=True)
    assert len(rows) >= 6
    assert all(row["after"] is not None for row in rows)

    def post(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["rejectMicroversionSkew"] is True
        assert payload["sourceMicroversion"] == "before"
        feature = payload["feature"]
        parameters = {p["parameterId"]: p for p in feature["parameters"]}
        if index == 0:
            assert parameters["originQuery"]["queries"][0]["path"] == ["part+1"]
            assert parameters["originQuery"]["queries"][0]["deterministicIds"] == ["face1"]
            assert parameters["transform"]["value"] is False
        else:
            assert [q["featureId"] for q in parameters["mateConnectorsQuery"]["queries"]] == [
                "connector_1",
                "connector-2",
            ]
            assert parameters["mateOffsetEnabled"]["value"] is False
        feature["featureId"] = "created_1"
        after = tree()
        after["features"].append(feature)
        after["featureStates"]["created_1"] = {"featureStatus": "OK"}
        respx.get(f"{BASE}/features").respond(200, json=after)
        return httpx.Response(200, json={"feature": feature})

    route = respx.post(f"{BASE}/features").mock(side_effect=post)
    result = await call(index)
    assert result["feature_id"] == "created_1"
    assert route.call_count == 1


@pytest.mark.parametrize("index", [0, 1])
@respx.mock
async def test_execution_requires_approval_observation(index: int) -> None:
    reads()
    with pytest.raises(ConnectorError, match="approved"):
        await call(index, bound=False)
    assert all(c.request.method == "GET" for c in respx.calls)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize(
    "bad", [{"unknown": 1}, {"document_id": "../other"}, {"name": "\n"}, {"workspace_id": False}]
)
@respx.mock
async def test_public_inputs_rejected_before_io(index: int, bad: dict[str, Any]) -> None:
    with pytest.raises(ConnectorError):
        await call(index, args={**ARGS[index], **bad}, preview=True)
    assert not respx.calls


@respx.mock
async def test_donor_scope_checked_before_read() -> None:
    reads()
    with pytest.raises(ConnectorError) as error:
        await call(0, args={**ARGS[0], "_documents": ["document"]}, preview=True)
    assert error.value.code == "not_found"
    assert not any(str(c.request.url).startswith(DONOR) for c in respx.calls)


@pytest.mark.parametrize(
    "change", ["suppressed", "subassembly", "configuration", "microversion", "duplicate", "face"]
)
@respx.mock
async def test_ambiguous_or_changed_geometry_refused(change: str) -> None:
    reads()
    root = assembly()
    part = root["rootAssembly"]["instances"][0]
    if change == "suppressed":
        part["suppressed"] = True
    if change == "subassembly":
        part["type"] = "Assembly"
    if change == "configuration":
        part["configuration"] = "other"
    if change == "microversion":
        root["rootAssembly"]["documentMicroversion"] = "other"
    if change == "duplicate":
        root["rootAssembly"]["instances"].append(copy.deepcopy(part))
    if change == "face":
        respx.get(DONOR).respond(200, json={"bodies": []})
    respx.get(BASE).respond(200, json=root)
    with pytest.raises(ConnectorError):
        await call(0, preview=True)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("failure", ["post401", "read401", "wrongrelation", "unhealthy", "oldid"])
@respx.mock
async def test_uncertain_mutation_never_becomes_retryable(index: int, failure: str) -> None:
    reads()

    def post(request: httpx.Request) -> httpx.Response:
        if failure == "post401":
            return httpx.Response(401)
        feature = json.loads(request.content)["feature"]
        feature["featureId"] = "connector_1" if failure == "oldid" else "newmate"
        after = tree()
        if failure == "wrongrelation":
            feature["parameters"][1]["queries"] = []
        after["features"].append(feature)
        after["featureStates"]["newmate"] = {
            "featureStatus": "ERROR" if failure == "unhealthy" else "OK"
        }
        respx.get(f"{BASE}/features").respond(401 if failure == "read401" else 200, json=after)
        return httpx.Response(200, json={"feature": feature})

    route = respx.post(f"{BASE}/features").mock(side_effect=post)
    with pytest.raises(ConnectorError) as error:
        await call(index)
    assert error.value.code == "mutation_unverified"
    assert route.call_count == 1


@respx.mock
async def test_duplicate_connector_selection_refused() -> None:
    with pytest.raises(ConnectorError):
        await call(1, args={**ARGS[1], "second_connector_id": "connector_1"}, preview=True)
    assert not respx.calls


@pytest.mark.parametrize("index", [0, 1])
@respx.mock
async def test_changed_root_after_preview_prevents_post(index: int) -> None:
    reads()
    original = fastened_frames() if index else assembly()
    changed = copy.deepcopy(original)
    for occurrence in changed["rootAssembly"]["occurrences"]:
        occurrence["transform"][3] = 0.01
    respx.get(BASE).mock(
        side_effect=[httpx.Response(200, json=original), httpx.Response(200, json=changed)]
    )
    with pytest.raises(ConnectorError) as error:
        await call(index)
    assert error.value.code == "stale_state"
    assert all(c.request.method == "GET" for c in respx.calls)


@pytest.mark.parametrize("index", [0, 1])
@respx.mock
async def test_random_spec_node_ids_do_not_invalidate_preview(index: int) -> None:
    reads()
    first, second = specs(), specs()
    first["featureSpecs"][index]["parameters"][0]["nodeId"] = "random1"
    second["featureSpecs"][index]["parameters"][0]["nodeId"] = "random2"
    first["featureSpecs"][index]["parameters"][0]["visibilityCondition"] = {"children": ["a", "b"]}
    second["featureSpecs"][index]["parameters"][0]["visibilityCondition"] = {"children": ["b", "a"]}
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).mock(
        side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=second)]
    )
    assert await call(index, preview=True) == await call(index, preview=True)


@pytest.mark.parametrize("normal", [[0, 0, 1], [0, 0, 2]])
@pytest.mark.parametrize("plane_type", ["PLANE", "plane"])
@respx.mock
async def test_native_planar_vectors_require_unit_normal(
    normal: list[int], plane_type: str
) -> None:
    reads()
    respx.get(DONOR).respond(
        200,
        json={
            "errorEnum": "NO_ERROR",
            "microversionId": {"btType": "BTMicroversionId-366", "theId": "pinned"},
            "bodies": [
                {
                    "id": "part1",
                    "type": "solid",
                    "faces": [
                        {
                            "id": "face1",
                            "surface": {
                                "type": plane_type,
                                "origin": {"btType": "BTVector3d-389", "x": 0, "y": 0, "z": 0},
                                "normal": dict(zip("xyz", normal, strict=True)),
                            },
                        }
                    ],
                }
            ],
        },
    )
    if normal[-1] == 1:
        assert await call(0, preview=True)
    else:
        with pytest.raises(ConnectorError):
            await call(0, preview=True)


@respx.mock
async def test_vendor_geometry_error_refused() -> None:
    reads()
    respx.get(DONOR).respond(
        200,
        json={
            "errorEnum": "ERROR",
            "microversionId": "pinned",
            "bodies": [
                {
                    "id": "part1",
                    "type": "solid",
                    "faces": [
                        {
                            "id": "face1",
                            "surface": {"type": "plane", "origin": [0, 0, 0], "normal": [0, 0, 1]},
                        }
                    ],
                }
            ],
        },
    )
    with pytest.raises(ConnectorError):
        await call(0, preview=True)


@respx.mock
async def test_mate_preview_reuses_immutable_donor_but_rereads_target() -> None:
    from solus_api.connectors.httpcache import InMemoryCacheStore
    from solus_api.connectors.integration_cache import IntegrationCache

    reads()
    cache = IntegrationCache(InMemoryCacheStore())
    connector = OnshapeConnector(
        client_id="fixture", client_secret="fixture", cache=cache, account_ref="account-a"
    )
    operation = MATE_OPERATIONS[0]
    async with connector.http(Credentials(token="fixture")) as client:
        await operation.preview(connector, client, copy.deepcopy(ARGS[0]))
        await operation.preview(connector, client, copy.deepcopy(ARGS[0]))
    paths = [call.request.url.path for call in respx.calls]
    assert paths.count(httpx.URL(DONOR).path) == 1
    assert paths.count(httpx.URL(BASE).path) == 2
    assert paths.count(httpx.URL(f"{BASE}/features").path) == 2


@pytest.mark.parametrize("index", [0, 1, 2])
@respx.mock
async def test_mating_root_requests_complete_mate_inventory(index: int) -> None:
    reads()
    if index == 2:
        from test_onshape_revolute import setup

        setup()
    await call(index, args=ARGS[0 if index == 0 else 1], preview=True)
    request = next(
        item.request for item in respx.calls if item.request.url.path.endswith("/e/assembly")
    )
    assert request.url.params["includeMateFeatures"] == "true"
    assert request.url.params["includeMateConnectors"] == "true"


@respx.mock
async def test_opaque_topology_ids_stay_in_payload_not_url() -> None:
    reads()
    root = assembly()
    root["rootAssembly"]["instances"][0]["partId"] = "JF/"
    respx.get(BASE).respond(200, json=root)
    respx.get(DONOR).respond(
        200,
        json={
            "microversionId": "pinned",
            "bodies": [
                {
                    "id": "JF/",
                    "type": "solid",
                    "faces": [
                        {
                            "id": "Face+/",
                            "surface": {"type": "plane", "origin": [0, 0, 0], "normal": [0, 0, 1]},
                        }
                    ],
                }
            ],
        },
    )
    rows = await call(0, args={**ARGS[0], "face_id": "Face+/"}, preview=True)
    assert "JF/" in json.dumps(rows) and "Face+/" in json.dumps(rows)
    assert all(
        "JF" not in item.request.url.path and "Face" not in item.request.url.path
        for item in respx.calls
    )


@pytest.mark.parametrize("face_id", ["../face", "face?secret=value", "a b", "a\n", "x" * 129])
@respx.mock
async def test_invalid_topology_tokens_are_rejected_before_vendor_io(face_id: str) -> None:
    with pytest.raises(ConnectorError):
        await call(0, args={**ARGS[0], "face_id": face_id}, preview=True)
    assert not respx.calls
