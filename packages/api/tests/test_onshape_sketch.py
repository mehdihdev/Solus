"""One circle on a verified plane: strict inputs, live identity and nonreplayed writes."""

import copy
import json
import re
from typing import Any

import httpx
import jsonschema
import pytest
import respx
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_confirmation import PreviewBinding
from solus_api.connectors.onshape_sketch import SKETCH_OPERATIONS

ARGS = {
    "document_id": "document",
    "workspace_id": "workspace",
    "element_id": "studio",
    "body_id": "body1",
    "face_id": "face1",
    "name": "Sensor circle",
    "center_x_mm": 12.3456789,
    "center_y_mm": -5.0,
    "radius_mm": 6.35,
}
BASE = f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/document/w/workspace/e/studio"


def tree(features: list[dict[str, Any]] | None = None, micro: str = "before") -> dict[str, Any]:
    features = (
        [{"featureId": "existing_1", "featureType": "extrude"}] if features is None else features
    )
    return {
        "features": features,
        "sourceMicroversion": micro,
        "serializationVersion": "1.2.21",
        "libraryVersion": 2399,
        "featureStates": {
            f["featureId"]: {"featureStatus": "OK", "inactive": False} for f in features
        },
    }


def geometry() -> dict[str, Any]:
    return {
        "microversionId": "before",
        "errorEnum": "NO_ERROR",
        "bodies": [
            {
                "id": "body1",
                "type": "SOLID",
                "faces": [
                    {
                        "id": "face1",
                        "surface": {
                            "btType": "BTPlaneDescription-692",
                            "type": "PLANE",
                            "origin": {"btType": "BTVector3d-389", "x": 0.0, "y": 0.002, "z": 0.0},
                            "normal": {"btType": "BTVector3d-389", "x": 0.0, "y": 1.0, "z": 0.0},
                        },
                    }
                ],
            }
        ],
    }


def specs() -> dict[str, Any]:
    return {
        "featureSpecs": [
            {
                "featureType": "newSketch",
                "namespace": "",
                "parameters": [
                    {
                        "parameterId": "sketchPlane",
                        "btType": "BTParameterSpecQuery-174",
                        "defaultValue": {"btType": "BTMParameterQueryList-148", "queries": []},
                    }
                ],
            }
        ]
    }


def reads() -> None:
    respx.get(f"{BASE}/features").respond(200, json=tree())
    respx.get(f"{BASE}/bodydetails").respond(200, json=geometry())
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=specs()
    )


async def run(args: dict[str, Any] | None = None, *, preview: bool = False) -> Any:
    operation = SKETCH_OPERATIONS[0]
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


@respx.mock
async def test_preview_is_read_only_explicit_local_coordinates_and_binds_geometry_and_spec() -> (
    None
):
    reads()
    first = await run(preview=True)
    for value in [
        "local sketch plane",
        "12.3456789",
        "6.35",
        "Sensor circle",
        "body1",
        "face1",
        "before",
        "0.002",
    ]:
        assert value in str(first)
    changed = geometry()
    changed["bodies"][0]["faces"][0]["surface"]["origin"]["y"] = 0.003
    respx.get(f"{BASE}/bodydetails").respond(200, json=changed)
    assert first != await run(preview=True)
    respx.get(f"{BASE}/bodydetails").respond(200, json=geometry())
    changed_spec = specs()
    changed_spec["featureSpecs"][0]["description"] = "changed"
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=changed_spec
    )
    assert first != await run(preview=True)
    assert all(c.request.method == "GET" for c in respx.calls)
    assert SKETCH_OPERATIONS[0].requires_confirmation and "write" in SKETCH_OPERATIONS[0].tags


@respx.mock
async def test_circle_payload_uses_metres_face_query_and_verified_new_feature() -> None:
    reads()
    payloads = []

    def post(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        feature = {**payload["feature"], "featureId": "created_sketch-1"}
        respx.get(f"{BASE}/features").respond(
            200, json=tree([*tree()["features"], feature], "after")
        )
        return httpx.Response(
            200, json={"feature": feature, "featureState": {"featureStatus": "OK"}}
        )

    posted = respx.post(f"{BASE}/features").mock(side_effect=post)
    result = await run()
    assert result["feature_id"] == "created_sketch-1" and posted.call_count == 1
    payload = payloads[0]
    assert payload["sourceMicroversion"] == "before" and payload["rejectMicroversionSkew"] is True
    feature = payload["feature"]
    assert feature["btType"] == "BTMSketch-151"
    assert feature["constraints"] == [] and len(feature["entities"]) == 1
    assert feature["parameters"][0]["queries"] == [
        {"btType": "BTMIndividualQuery-138", "deterministicIds": ["face1"]}
    ]
    circle = feature["entities"][0]["geometry"]
    assert circle["xCenter"] == ARGS["center_x_mm"] / 1000
    assert circle["yCenter"] == -0.005 and circle["radius"] == 0.00635
    assert circle["xDir"] == 1 and circle["yDir"] == 0 and circle["clockwise"] is False
    assert result["geometry"] == circle


@pytest.mark.parametrize(
    "change",
    [
        {"radius_mm": 0},
        {"radius_mm": True},
        {"radius_mm": "2"},
        {"radius_mm": 10001},
        {"center_x_mm": float("nan")},
        {"center_y_mm": 10001},
        {"face_id": "../face"},
        {"name": ""},
        {"name": "x" * 121},
        {"queryString": "query=anything"},
    ],
)
@respx.mock
async def test_invalid_input_precedes_reads(change: dict[str, Any]) -> None:
    with pytest.raises(ConnectorError):
        await run({**ARGS, **change})
    assert not respx.calls


@pytest.mark.parametrize(
    "failure",
    [
        "missing_body",
        "duplicate_body",
        "missing_face",
        "duplicate_face",
        "nonplanar",
        "bad_origin",
        "zero_normal",
        "bad_normal",
        "stale_geometry",
        "vendor_error",
        "bad_spec",
        "null_default",
        "list_default",
        "string_default",
        "custom_spec",
        "duplicate_spec",
        "missing_micro",
    ],
)
@respx.mock
async def test_invalid_geometry_or_spec_refuses_before_post(failure: str) -> None:
    reads()
    body = geometry()
    spec = specs()
    _corrupt_geometry(body, failure)
    if failure == "stale_geometry":
        body["microversionId"] = "other"
    elif failure == "vendor_error":
        body["errorEnum"] = "BAD_INPUT"
    elif failure == "bad_spec":
        spec["featureSpecs"][0]["parameters"][0]["btType"] = "BTParameterSpecBoolean-170"
    elif failure.endswith("_default"):
        spec["featureSpecs"][0]["parameters"][0]["defaultValue"] = {
            "null_default": None,
            "list_default": [],
            "string_default": "invalid",
        }[failure]
    elif failure == "custom_spec":
        spec["featureSpecs"][0]["namespace"] = "custom"
    elif failure == "duplicate_spec":
        spec["featureSpecs"] *= 2
    elif failure == "missing_micro":
        before = tree()
        before.pop("sourceMicroversion")
        respx.get(f"{BASE}/features").respond(200, json=before)
    respx.get(f"{BASE}/bodydetails").respond(200, json=body)
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=spec
    )
    with pytest.raises(ConnectorError):
        await run()
    assert all(c.request.method == "GET" for c in respx.calls)


@pytest.mark.parametrize(
    "failure",
    [
        "post_timeout",
        "post_401",
        "read_401",
        "old_id",
        "missing_feature",
        "error_state",
        "wrong_radius",
        "extra_entity",
        "wrong_plane",
        "numeric_boolean",
        "constraints",
    ],
)
@respx.mock
async def test_uncertain_write_returns_nonretryable_without_repeated_post(failure: str) -> None:
    reads()

    def post(request: httpx.Request) -> httpx.Response:
        if failure == "post_timeout":
            raise httpx.ReadTimeout("fixture", request=request)
        if failure == "post_401":
            return httpx.Response(401)
        feature = {
            **json.loads(request.content)["feature"],
            "featureId": "existing_1" if failure == "old_id" else "new_1",
        }
        _corrupt_created_feature(feature, failure)
        after = tree([*tree()["features"], feature], "after")
        if failure == "missing_feature":
            after = tree(micro="after")
        elif failure == "error_state":
            after["featureStates"]["new_1"]["featureStatus"] = "ERROR"
        respx.get(f"{BASE}/features").respond(401 if failure == "read_401" else 200, json=after)
        return httpx.Response(
            200, json={"feature": feature, "featureState": {"featureStatus": "OK"}}
        )

    posted = respx.post(f"{BASE}/features").mock(side_effect=post)
    with pytest.raises(ConnectorError) as error:
        await run()
    assert error.value.code == "mutation_unverified" and posted.call_count == 1


@respx.mock
async def test_internal_document_menu_is_not_public_schema_input() -> None:
    reads()
    before = copy.deepcopy(ARGS)
    assert await run({**ARGS, "_documents": ["document"]}, preview=True)
    assert ARGS == before
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**ARGS, "_documents": ["document"]}, SKETCH_OPERATIONS[0].params)


def _corrupt_geometry(body: dict[str, Any], failure: str) -> None:
    if failure == "missing_body":
        body["bodies"] = []
    elif failure == "duplicate_body":
        body["bodies"] *= 2
    elif failure == "missing_face":
        body["bodies"][0]["faces"] = []
    elif failure == "duplicate_face":
        body["bodies"][0]["faces"] *= 2
    elif failure == "nonplanar":
        body["bodies"][0]["faces"][0]["surface"]["type"] = "CYLINDER"
    elif failure == "bad_origin":
        body["bodies"][0]["faces"][0]["surface"]["origin"]["x"] = True
    elif failure == "bad_normal":
        body["bodies"][0]["faces"][0]["surface"]["normal"]["x"] = "bad"
    elif failure == "zero_normal":
        body["bodies"][0]["faces"][0]["surface"]["normal"]["y"] = 0


def _corrupt_created_feature(feature: dict[str, Any], failure: str) -> None:
    if failure == "wrong_radius":
        feature["entities"][0]["geometry"]["radius"] = 1.0
    elif failure == "extra_entity":
        feature["entities"] *= 2
    elif failure == "wrong_plane":
        feature["parameters"][0]["queries"][0]["deterministicIds"] = ["face2"]
    elif failure == "numeric_boolean":
        feature["entities"][0]["geometry"]["clockwise"] = 0
    elif failure == "constraints":
        feature["constraints"] = [{"anything": "unexpected"}]


@pytest.mark.parametrize("change", ["vendor_defaults", "construction", "incomplete"])
@respx.mock
async def test_real_vendor_sketch_defaults_and_failure_state(change: str) -> None:
    reads()

    def post(request: httpx.Request) -> httpx.Response:
        feature = {**json.loads(request.content)["feature"], "featureId": "created_1"}
        feature["parameters"].extend(
            [
                {
                    "parameterId": "disableImprinting",
                    "btType": "BTMParameterBoolean-144",
                    "value": False,
                },
                {
                    "parameterId": "asVersion",
                    "btType": "BTMParameterEnum-145",
                    "enumName": "FeatureScriptVersionNumber",
                    "namespace": "",
                    "value": "V2260_AUTO_POPULATE_OWNER_ENTITY_MATE_CONNECTOR_FIX",
                },
            ]
        )
        if change == "construction":
            feature["parameters"] = feature["parameters"][:1]
            feature["entities"][0]["isConstruction"] = True
        after = tree([*tree()["features"], feature], "after")
        if change == "incomplete":
            feature["parameters"] = feature["parameters"][:1]
            after["isComplete"] = False
        respx.get(f"{BASE}/features").respond(200, json=after)
        return httpx.Response(200, json={"feature": feature})

    respx.post(f"{BASE}/features").mock(side_effect=post)
    if change == "vendor_defaults":
        assert (await run())["feature_id"] == "created_1"
    else:
        with pytest.raises(ConnectorError):
            await run()


@respx.mock
async def test_native_microversion_object_and_generated_spec_node_ids() -> None:
    reads()
    body = geometry()
    body["microversionId"] = {"btType": "BTMicroversionId-366", "theId": "before"}
    respx.get(f"{BASE}/bodydetails").respond(200, json=body)
    before = await run(preview=True)
    spec = specs()
    spec["featureSpecs"][0]["parameters"][0]["defaultValue"]["nodeId"] = "generatedPerRequest"
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=spec
    )
    assert await run(preview=True) == before


@respx.mock
async def test_preview_ignores_generated_tree_ids_and_transport_version_only() -> None:
    reads()
    before = await run(preview=True)
    changed = tree()
    changed["serializationVersion"] = "1.2.0"
    changed["features"][0]["nodeId"] = "regenerated-query-identity"
    respx.get(f"{BASE}/features").respond(200, json=changed)
    assert await run(preview=True) == before
    changed["features"][0]["name"] = "Actual renamed feature"
    respx.get(f"{BASE}/features").respond(200, json=changed)
    assert await run(preview=True) != before
