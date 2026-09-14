"""Explicit revolute semantics against the verified built-in mate schema."""

import copy
import json
import re
from typing import Any

import httpx
import pytest
import respx
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape_mates import MATE_OPERATIONS
from test_onshape_mates import ARGS, BASE, assembly, call, reads, specs, tree


def operation_index() -> int:
    return next(
        i for i, op in enumerate(MATE_OPERATIONS) if op.name == "onshape.create_revolute_mate"
    )


def observed_specs(*, revolute: bool = True) -> dict[str, Any]:
    body = specs()
    if revolute:
        body["featureSpecs"][1]["parameters"][0]["options"].append("REVOLUTE")
    body["featureSpecs"][1]["parameters"].append(
        {
            "btType": "BTParameterSpecQuantity-173",
            "parameterId": "mateOffsetDistanceZ",
            "quantityType": "LENGTH",
        }
    )
    return body


def assembly_frames(distance: float = 0) -> dict[str, Any]:
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
                "occurrence": [f"part+{index + 1}"],
                "mateConnectorCS": {
                    "origin": [0, 0, -distance if index else 0],
                    "xAxis": [1, 0, 0],
                    "yAxis": [0, -1 if index else 1, 0],
                    "zAxis": [0, 0, -1 if index else 1],
                },
            },
        }
        for index, identity in enumerate(("connector_1", "connector-2"))
    ]
    return payload


def setup(*, revolute: bool = True, distance: float = 0) -> None:
    reads()
    respx.get(BASE).respond(200, json=assembly_frames(distance))
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=observed_specs(revolute=revolute)
    )


async def invoke(
    *, preview: bool = False, bound: bool = True, changes: dict[str, Any] | None = None
) -> Any:
    return await call(
        operation_index(), args={**ARGS[1], **(changes or {})}, preview=preview, bound=bound
    )


@respx.mock
async def test_revolute_preview_and_verified_payload_preserve_one_rotation() -> None:
    setup()
    preview = await invoke(preview=True)
    text = json.dumps(preview)
    assert "REVOLUTE" in text and "rotational" in text and "preserv" in text

    def post(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["rejectMicroversionSkew"] is True
        feature = body["feature"]
        params = {p["parameterId"]: p for p in feature["parameters"]}
        assert params["mateType"]["value"] == "REVOLUTE"
        assert params["mateOffsetEnabled"]["value"] is False
        assert params["limitsEnabled"]["value"] is False
        assert params["functionalconnection"]["value"] is False
        assert params["primaryAxisAlignment"]["value"] is True
        assert params["secondaryAxisAlignment"]["value"] == "PLUS_X"
        assert [q["path"] for q in params["mateConnectorsQuery"]["queries"]] == [[], []]
        feature["featureId"] = "joint_1"
        after = tree()
        after["features"].append(feature)
        after["featureStates"]["joint_1"] = {"featureStatus": "OK"}
        respx.get(f"{BASE}/features").respond(200, json=after)
        return httpx.Response(200, json={"feature": feature})

    route = respx.post(f"{BASE}/features").mock(side_effect=post)
    result = await invoke()
    assert result["feature_id"] == "joint_1"
    assert result["pose_preserved"] is True and result["axial_offset_m"] == 0
    assert route.call_count == 1


@pytest.mark.parametrize("distance", [0.025, -0.00015])
@respx.mock
async def test_measured_offset_serializes_vendor_sign_and_preserves_poses(distance):
    setup(distance=distance)

    def post(request):
        feature = json.loads(request.content)["feature"]
        params = {p["parameterId"]: p for p in feature["parameters"]}
        assert params["mateOffsetEnabled"]["value"] is True
        assert params["mateOffsetDistanceZ"]["btType"] == "BTMParameterQuantity-147"
        expression = params["mateOffsetDistanceZ"]["expression"]
        assert expression.endswith(" m") and float(expression[:-2]) == pytest.approx(distance)
        feature["featureId"] = "joint"
        after = tree()
        after["features"].append(feature)
        after["featureStates"]["joint"] = {"featureStatus": "OK"}
        respx.get(f"{BASE}/features").respond(200, json=after)
        return httpx.Response(200, json={"feature": feature})

    route = respx.post(f"{BASE}/features").mock(side_effect=post)
    result = await invoke(changes={"axial_offset_m": distance})
    assert result["pose_preserved"] is True
    assert result["axial_offset_m"] == pytest.approx(distance)
    assert route.call_count == 1


@pytest.mark.parametrize("requested", [None, 0.02, True, float("nan"), 501])
@respx.mock
async def test_unmeasured_or_invalid_offset_refuses_before_post(requested):
    setup(distance=0.025)
    changes = {} if requested is None else {"axial_offset_m": requested}
    with pytest.raises(ConnectorError):
        await invoke(changes=changes)
    assert all(row.request.method == "GET" for row in respx.calls)


@respx.mock
async def test_revolute_postwrite_pose_change_is_uncertain_without_replay():
    setup()

    def post(request):
        feature = json.loads(request.content)["feature"]
        feature["featureId"] = "joint"
        after = tree()
        after["features"].append(feature)
        after["featureStates"]["joint"] = {"featureStatus": "OK"}
        respx.get(f"{BASE}/features").respond(200, json=after)
        moved = assembly_frames()
        moved["rootAssembly"]["occurrences"][0]["transform"] = list(
            moved["rootAssembly"]["occurrences"][0]["transform"]
        )
        moved["rootAssembly"]["occurrences"][0]["transform"][3] += 0.001
        respx.get(BASE).respond(200, json=moved)
        return httpx.Response(200, json={"feature": feature})

    route = respx.post(f"{BASE}/features").mock(side_effect=post)
    with pytest.raises(ConnectorError) as error:
        await invoke()
    assert error.value.code == "mutation_unverified"
    assert route.call_count == 1


@respx.mock
async def test_revolute_refuses_missing_vendor_enum_before_write() -> None:
    setup(revolute=False)
    with pytest.raises(ConnectorError):
        await invoke()
    assert all(c.request.method == "GET" for c in respx.calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"first_connector_id": "connector-2"},
        {"first_connector_id": "missing"},
        {"limitsEnabled": True},
        {"name": "\n"},
    ],
)
@respx.mock
async def test_invalid_connector_or_extra_vendor_payload_never_writes(
    changes: dict[str, Any],
) -> None:
    setup()
    with pytest.raises(ConnectorError):
        await invoke(changes=changes)
    assert all(c.request.method == "GET" for c in respx.calls)


@respx.mock
async def test_revolute_requires_bound_preview() -> None:
    setup()
    with pytest.raises(ConnectorError):
        await invoke(bound=False)
    assert all(c.request.method == "GET" for c in respx.calls)


@respx.mock
async def test_same_direction_revolute_uses_measured_unflipped_primary():
    from solus_api.connectors.contracts import Credentials
    from solus_api.connectors.onshape import OnshapeConnector
    from solus_api.connectors.onshape_mates import _Mate

    setup()
    payload = assembly_frames()
    cs = payload["rootAssembly"]["features"][1]["featureData"]["mateConnectorCS"]
    cs.update(yAxis=[0, 1, 0], zAxis=[0, 0, 1])
    respx.get(BASE).respond(200, json=payload)
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    async with connector.http(Credentials(token="fixture")) as client:
        mate = await _Mate.observe(connector, client, ARGS[1], "mate", "REVOLUTE")
    parameters = {p["parameterId"]: p for p in mate.parameters()}
    assert parameters["primaryAxisAlignment"]["value"] is False


@pytest.mark.parametrize("bad_readback", ["FASTENED", "ERROR", "offset", "flag"])
@respx.mock
async def test_wrong_enum_or_failed_regeneration_is_uncertain_without_replay(
    bad_readback: str,
) -> None:
    setup()

    def post(request: httpx.Request) -> httpx.Response:
        feature = json.loads(request.content)["feature"]
        feature["featureId"] = "joint_1"
        after = tree()
        observed = copy.deepcopy(feature)
        if bad_readback == "FASTENED":
            next(p for p in observed["parameters"] if p["parameterId"] == "mateType")["value"] = (
                "FASTENED"
            )
        if bad_readback == "offset":
            next(p for p in observed["parameters"] if p["parameterId"] == "mateOffsetDistanceZ")[
                "expression"
            ] = "1 m"
        if bad_readback == "flag":
            next(p for p in observed["parameters"] if p["parameterId"] == "mateOffsetEnabled")[
                "value"
            ] = True
        after["features"].append(observed)
        after["featureStates"]["joint_1"] = {
            "featureStatus": "ERROR" if bad_readback == "ERROR" else "OK"
        }
        respx.get(f"{BASE}/features").respond(200, json=after)
        return httpx.Response(200, json={"feature": feature})

    route = respx.post(f"{BASE}/features").mock(side_effect=post)
    with pytest.raises(ConnectorError) as caught:
        await invoke()
    assert caught.value.code == "mutation_unverified"
    assert route.call_count == 1


@pytest.mark.parametrize("quantity_type", [None, "ANGLE"])
@respx.mock
async def test_revolute_requires_observed_length_offset_spec(quantity_type) -> None:
    setup()
    body = observed_specs()
    parameters = body["featureSpecs"][1]["parameters"]
    quantity = next(p for p in parameters if p["parameterId"] == "mateOffsetDistanceZ")
    if quantity_type is None:
        parameters.remove(quantity)
    else:
        quantity["quantityType"] = quantity_type
    respx.get(re.compile(BASE.replace("/w/workspace/", "/m/[^/]+/") + "/featurespecs")).respond(
        200, json=body
    )
    with pytest.raises(ConnectorError):
        await invoke()
    assert all(row.request.method == "GET" for row in respx.calls)


def test_real_factory_attests_revolute_for_normal_build_policy() -> None:
    from uuid import uuid4

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
    tool = next(
        tool for tool in registry.tools() if tool.descriptor.name == "onshape.create_revolute_mate"
    )
    assert tool.descriptor.requires_confirmation
    assert tool.requires_complete_preview
    assert getattr(tool, "_build_authority", None) is not None


@respx.mock
async def test_actual_revolute_preview_is_admitted_once_in_build(engine) -> None:
    from solus_api.agent.execution_policy import BuildExecutionPolicy
    from solus_api.agent.modes import ActionMode
    from solus_api.agent.runtime import build_sol_registry
    from solus_api.agent.tools.shapes import ToolCall, ToolResult
    from solus_api.connectors.onshape import ONSHAPE_API_BASE
    from solus_api.connectors.secrets import InMemorySecretStore
    from solus_api.models import Source
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from test_onshape_tools import _connectors, _seed

    maker = async_sessionmaker(engine, expire_on_commit=False)
    project, reference = await _seed(maker, documents=["document", "donor"])
    async with maker() as session:
        source = await session.scalar(select(Source).where(Source.project_id == project))
        source.config = {**source.config, "access": "write"}
        await session.commit()
    store = InMemorySecretStore()
    await store.put(reference, "fixture")
    registry = build_sol_registry(maker, project, secret_store=store, connectors=_connectors())
    setup()
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/document").respond(
        200, json={"name": "fixture"}
    )
    call = ToolCall(
        tool="onshape.create_revolute_mate",
        args={k: v for k, v in ARGS[1].items() if not k.startswith("_")},
        call_id="joint-call",
    )
    policy = BuildExecutionPolicy(registry, ActionMode.DO)
    assert await policy.prepare(call) is True
    repeated = await policy.prepare(call)
    assert isinstance(repeated, ToolResult) and not repeated.ok
    assert all(item.request.method == "GET" for item in respx.calls)
