"""Rigid mate recovery uses historical poses, never client-supplied matrices."""

import copy
import json
import re

import httpx
import pytest
import respx
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.onshape_confirmation import PreviewBinding
from solus_api.connectors.onshape_mate_repair import REPAIR_OPERATION
from test_onshape_mates import BASE, COMMON, fastened_frames, reads, specs, tree

ARGS = {k: v for k, v in COMMON.items() if k != "name"} | {
    "feature_id": "joint+/",
    "reference_microversion": "historic",
}
HISTORY = BASE.replace("/w/workspace/", "/m/historic/")


def fixture():
    reads()
    current = fastened_frames()
    cs = current["rootAssembly"]["features"][1]["featureData"]["mateConnectorCS"]
    cs.update(xAxis=[0, 1, 0], yAxis=[1, 0, 0])
    historical = copy.deepcopy(current)
    historical["rootAssembly"]["documentMicroversion"] = "historic"
    historical["rootAssembly"]["features"] = []
    current["rootAssembly"]["occurrences"][1]["transform"] = [
        0,
        1,
        0,
        0,
        -1,
        0,
        0,
        0,
        0,
        0,
        1,
        0,
        0,
        0,
        0,
        1,
    ]
    parameters = [
        {
            "btType": "BTMParameterEnum-145",
            "parameterId": "mateType",
            "enumName": "Mate type",
            "value": "FASTENED",
        },
        {
            "btType": "BTMParameterEnum-145",
            "parameterId": "secondaryAxisAlignment",
            "enumName": "Reorient secondary axis",
            "value": "PLUS_X",
        },
        {
            "btType": "BTMParameterQueryWithOccurrenceList-67",
            "parameterId": "mateConnectorsQuery",
            "queries": [
                {
                    "btType": "BTMFeatureQueryWithOccurrence-157",
                    "featureId": identity,
                    "path": [],
                    "queryData": "",
                }
                for identity in ("connector_1", "connector-2")
            ],
        },
        *[
            {"btType": "BTMParameterBoolean-144", "parameterId": key, "value": value}
            for key, value in {
                "primaryAxisAlignment": True,
                "mateOffsetEnabled": False,
                "limitsEnabled": False,
                "functionalconnection": False,
            }.items()
        ],
    ]
    feature = {
        "featureId": "joint+/",
        "featureType": "mate",
        "name": "Rigid mount",
        "suppressed": False,
        "parameters": parameters,
    }
    features = tree()
    features["features"].append(feature)
    features["featureStates"]["joint+/"] = {"featureStatus": "OK"}
    schema = specs()
    schema["featureSpecs"][1]["parameters"][-1]["options"].append("PLUS_Y")
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=schema
    )
    respx.get(BASE).respond(200, json=current)
    respx.get(HISTORY).respond(200, json=historical)
    respx.get(BASE + "/features").respond(200, json=features)
    return current, historical, features


async def invoke():
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    binding = PreviewBinding()
    async with connector.http(Credentials(token="fixture")) as client:
        binding.remember(ARGS, await REPAIR_OPERATION.preview(connector, client, ARGS))
        with binding.execution(ARGS):
            return await REPAIR_OPERATION.run(connector, client, ARGS)


@pytest.mark.parametrize("bad_pose", [False, True, "incomplete"])
@respx.mock
async def test_repair_changes_only_secondary_enum_then_proves_historical_poses(bad_pose):
    current, historical, features = fixture()
    original = copy.deepcopy(features["features"][-1])

    def post(request):
        payload = json.loads(request.content)
        edited = payload["feature"]
        expected = copy.deepcopy(original)
        expected["parameters"][1]["value"] = "PLUS_Y"
        assert edited == expected and payload["rejectMicroversionSkew"] is True
        features["features"][-1] = edited
        respx.get(BASE + "/features").respond(200, json=features)
        if bad_pose == "incomplete":
            current["isComplete"] = False
        if bad_pose is not True:
            current["rootAssembly"]["occurrences"] = historical["rootAssembly"]["occurrences"]
        respx.get(BASE).respond(200, json=current)
        return httpx.Response(200, json={"feature": edited})

    route = respx.post(BASE + "/features/featureid/joint%2B%2F").mock(side_effect=post)
    if bad_pose:
        with pytest.raises(ConnectorError) as error:
            await invoke()
        assert error.value.code == "mutation_unverified"
    else:
        result = await invoke()
        assert result["pose_restored"] is True
    assert route.call_count == 1


@pytest.mark.parametrize(
    "fault", ["identity", "foreign_revision", "missing_path", "unsafe_mate", "extra_args"]
)
@respx.mock
async def test_repair_refuses_unproven_reference_or_unsafe_mate_without_post(fault):
    current, historical, features = fixture()
    if fault == "identity":
        historical["rootAssembly"]["instances"][0]["partId"] = "different"
    elif fault == "foreign_revision":
        historical["rootAssembly"]["instances"][0]["documentMicroversion"] = "different"
    elif fault == "missing_path":
        historical["rootAssembly"]["occurrences"].pop()
    elif fault == "unsafe_mate":
        features["features"][-1]["parameters"][-1]["value"] = True
    respx.get(HISTORY).respond(200, json=historical)
    respx.get(BASE + "/features").respond(200, json=features)
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    async with connector.http(Credentials(token="fixture")) as client:
        with pytest.raises(ConnectorError):
            await REPAIR_OPERATION.preview(
                connector, client, ARGS | ({"matrix": []} if fault == "extra_args" else {})
            )
    assert all(row.request.method == "GET" for row in respx.calls)


@respx.mock
async def test_repair_requires_bound_current_preview():
    fixture()
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    async with connector.http(Credentials(token="fixture")) as client:
        with pytest.raises(ConnectorError):
            await REPAIR_OPERATION.run(connector, client, ARGS)
    assert all(row.request.method == "GET" for row in respx.calls)


@respx.mock
async def test_repair_changed_feature_invalidates_bound_preview_before_post():
    _, _, features = fixture()
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    binding = PreviewBinding()
    async with connector.http(Credentials(token="fixture")) as client:
        binding.remember(ARGS, await REPAIR_OPERATION.preview(connector, client, ARGS))
        features["features"][-1]["name"] = "Renamed concurrently"
        respx.get(BASE + "/features").respond(200, json=features)
        with binding.execution(ARGS), pytest.raises(ConnectorError) as error:
            await REPAIR_OPERATION.run(connector, client, ARGS)
    assert error.value.code == "stale_state"
    assert all(row.request.method == "GET" for row in respx.calls)


def test_repair_real_registry_has_scoped_build_authority():
    from uuid import uuid4

    from solus_api.agent.execution_policy import _ONSHAPE
    from solus_api.agent.runtime import build_sol_registry
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.connectors.secrets import InMemorySecretStore
    from sqlalchemy.ext.asyncio import async_sessionmaker

    registry = build_sol_registry(
        async_sessionmaker(),
        uuid4(),
        secret_store=InMemorySecretStore(),
        connectors=ConnectorRegistry(),
    )
    tool = next(t for t in registry.tools() if t.descriptor.name == REPAIR_OPERATION.name)
    assert tool.requires_complete_preview and tool.descriptor.requires_confirmation
    assert getattr(tool, "_build_authority", None) is not None
    assert REPAIR_OPERATION.name in _ONSHAPE


@pytest.mark.parametrize("which", ["current", "historical"])
@respx.mock
async def test_repair_incomplete_envelope_refuses_before_write(which):
    current, historical, _ = fixture()
    body = current if which == "current" else historical
    body["isComplete"] = False
    respx.get(BASE if which == "current" else HISTORY).respond(200, json=body)
    with pytest.raises(ConnectorError):
        await invoke()
    assert all(row.request.method == "GET" for row in respx.calls)
