"""Complete circle inference and independently verified connector frames."""

import copy
import math
from typing import Any

import pytest
from solus_api.connectors.contracts import ConnectorError

TRANSFORM = [0, -1, 0, 1, 1, 0, 0, 2, 0, 0, 1, 3, 0, 0, 0, 1]


def part() -> dict[str, Any]:
    return {
        "id": "body+/",
        "type": "solid",
        "edges": [
            {
                "id": "circle+/",
                "curve": {
                    "type": "CIRCLE",
                    "radius": 0.01,
                    "origin": {"x": 0, "y": 0, "z": 0},
                    "normal": {"x": 0, "y": 0, "z": 1},
                },
                "geometry": {
                    "arcSweep": 2 * math.pi,
                    "length": 0.02 * math.pi,
                    "startPoint": {"x": 0.01, "y": 0, "z": 0},
                    "endPoint": {"x": 0.01, "y": 0, "z": 0},
                },
            }
        ],
    }


def roots() -> tuple[dict[str, Any], dict[str, Any]]:
    before = {"occurrences": [{"path": ["instance+/"], "transform": TRANSFORM.copy()}]}
    after = copy.deepcopy(before)
    after["features"] = [
        {
            "id": "created",
            "featureType": "mateConnector",
            "suppressed": False,
            "featureData": {
                "occurrence": ["instance+/"],
                "mateConnectorCS": {
                    "origin": [0, 0, 0],
                    "xAxis": [1, 0, 0],
                    "yAxis": [0, 1, 0],
                    "zAxis": [0, 0, 1],
                },
            },
        }
    ]
    return before, after


def test_observed_circle_transforms_center_and_axis_into_world_space() -> None:
    from solus_api.connectors.onshape_circle_geometry import circle_frame

    result = circle_frame(part(), "circle+/", TRANSFORM)
    assert result == {"origin": [1, 2, 3], "axis": [0, 0, 1]}


@pytest.mark.parametrize(
    "bad",
    [
        "arc",
        "length",
        "endpoint",
        "radius",
        "normal",
        "nonfinite",
        "boolean",
        "overflow",
        "duplicate",
        "missing",
    ],
)
def test_circle_evidence_requires_complete_consistent_numeric_geometry(bad: str) -> None:
    from solus_api.connectors.onshape_circle_geometry import circle_frame

    body = part()
    edge = body["edges"][0]
    if bad == "arc":
        edge["geometry"]["arcSweep"] = math.pi
    elif bad == "length":
        edge["geometry"]["length"] = 0.01
    elif bad == "endpoint":
        edge["geometry"]["endPoint"]["z"] = 0.001
    elif bad == "radius":
        edge["curve"]["radius"] = 0
    elif bad == "normal":
        edge["curve"]["normal"]["z"] = 2
    elif bad == "nonfinite":
        edge["curve"]["origin"]["x"] = math.nan
    elif bad == "boolean":
        edge["curve"]["radius"] = True
    elif bad == "overflow":
        edge["curve"]["radius"] = 10**1000
    elif bad == "duplicate":
        body["edges"].append(copy.deepcopy(edge))
    else:
        del edge["geometry"]["startPoint"]
    with pytest.raises(ConnectorError):
        circle_frame(body, "circle+/", TRANSFORM)


@pytest.mark.parametrize("index,value", [(0, 1), (15, 2), (0, True), (3, math.inf), (10, -1)])
def test_occurrence_transform_must_be_proper_rigid(index: int, value: float) -> None:
    from solus_api.connectors.onshape_circle_geometry import circle_frame

    transform = TRANSFORM.copy()
    transform[index] = value  # type: ignore[call-overload]  # parametrized value is float
    with pytest.raises(ConnectorError):
        circle_frame(part(), "circle+/", transform)


def test_coordinate_readback_matches_identity_frame_and_all_occurrence_poses() -> None:
    from solus_api.connectors.onshape_circle_geometry import circle_frame, verify_connector_frame

    before, after = roots()
    frame = circle_frame(part(), "circle+/", TRANSFORM)
    assert verify_connector_frame(before, after, "created", "instance+/", frame) == frame


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "identity",
        "occurrence",
        "origin",
        "axis",
        "near_axis",
        "handedness",
        "moved",
        "pathset",
        "duplicate",
    ],
)
def test_bad_coordinate_readback_is_uncertain(bad: str) -> None:
    from solus_api.connectors.onshape_circle_geometry import verify_connector_frame

    before, after = roots()
    feature = after["features"][0]
    cs = feature["featureData"]["mateConnectorCS"]
    if bad == "missing":
        del feature["featureData"]["mateConnectorCS"]
    elif bad == "identity":
        feature["id"] = "other"
    elif bad == "occurrence":
        feature["featureData"]["occurrence"] = ["other"]
    elif bad == "origin":
        cs["origin"][0] = 0.001
    elif bad == "axis":
        cs.update(xAxis=[1, 0, 0], yAxis=[0, 0, 1], zAxis=[0, -1, 0])
    elif bad == "near_axis":
        angle = 1e-5
        cs.update(
            yAxis=[0, math.cos(angle), math.sin(angle)],
            zAxis=[0, -math.sin(angle), math.cos(angle)],
        )
    elif bad == "handedness":
        cs["yAxis"] = [0, -1, 0]
    elif bad == "moved":
        after["occurrences"][0]["transform"][3] += 0.001
    elif bad == "pathset":
        after["occurrences"][0]["path"] = ["other"]
    else:
        after["features"].append(copy.deepcopy(feature))
    with pytest.raises(ConnectorError) as error:
        verify_connector_frame(
            before, after, "created", "instance+/", {"origin": [1, 2, 3], "axis": [0, 0, 1]}
        )
    assert error.value.code == "mutation_unverified"


def test_antiparallel_axis_returns_actual_signed_axis() -> None:
    from solus_api.connectors.onshape_circle_geometry import verify_connector_frame

    before, after = roots()
    after["features"][0]["featureData"]["mateConnectorCS"].update(
        yAxis=[0, -1, 0], zAxis=[0, 0, -1]
    )
    result = verify_connector_frame(
        before, after, "created", "instance+/", {"origin": [1, 2, 3], "axis": [0, 0, 1]}
    )
    assert result["axis"] == [0, 0, -1]


@pytest.mark.parametrize(
    "readback", ["ok", "opaque_identity", "missing", "wrong_origin", "no_revisions"]
)
async def test_native_circle_creation_requires_actual_coordinate_readback(readback: str) -> None:
    import json

    import httpx
    import respx
    from solus_api.connectors.onshape_mates import MATE_OPERATIONS
    from test_onshape_mates import ARGS, BASE, DONOR, assembly, call, reads, tree

    with respx.mock:
        reads()
        root = assembly()
        root["rootAssembly"]["instances"][0]["partId"] = "body+/"
        root["rootAssembly"]["occurrences"][0]["transform"] = TRANSFORM.copy()
        respx.get(BASE).respond(200, json=root)
        respx.get(DONOR).respond(200, json={"microversionId": "pinned", "bodies": [part()]})
        index = next(
            i
            for i, op in enumerate(MATE_OPERATIONS)
            if op.name == "onshape.create_circle_mate_connector"
        )
        args = {k: v for k, v in ARGS[0].items() if k != "face_id"}
        args["edge_id"] = "circle+/"
        identity = "created+/" if readback == "opaque_identity" else "created"

        def post(request: httpx.Request) -> httpx.Response:
            feature = json.loads(request.content)["feature"]
            query = next(p for p in feature["parameters"] if p["parameterId"] == "originQuery")[
                "queries"
            ][0]
            assert query["inferenceType"] == "CENTER"
            assert query["deterministicIds"] == ["circle+/"]
            assert query["path"] == ["part+1"]
            feature["featureId"] = identity
            after_tree = tree()
            after_tree["features"].append(feature)
            after_tree["featureStates"][identity] = {"featureStatus": "OK"}
            after_root = copy.deepcopy(root)
            if readback == "no_revisions":
                del after_tree["sourceMicroversion"]
                del after_root["rootAssembly"]["documentMicroversion"]
            respx.get(f"{BASE}/features").respond(200, json=after_tree)
            cs_feature = roots()[1]["features"][0]
            cs_feature["id"] = identity
            cs_feature["featureData"]["occurrence"] = ["part+1"]
            if readback == "wrong_origin":
                cs_feature["featureData"]["mateConnectorCS"]["origin"][0] = 0.001
            after_root["rootAssembly"]["features"] = [cs_feature] if readback != "missing" else []
            respx.get(BASE).respond(200, json=after_root)
            return httpx.Response(200, json={"feature": feature})

        route = respx.post(f"{BASE}/features").mock(side_effect=post)
        if readback in ("ok", "opaque_identity"):
            result = await call(index, args=args)
            assert result["feature_id"] == identity
            assert result["world_origin_m"] == [1, 2, 3]
            assert result["world_axis"] == [0, 0, 1]
        else:
            with pytest.raises(ConnectorError) as error:
                await call(index, args=args)
            assert error.value.code == "mutation_unverified"
        assert route.call_count == 1


def test_occurrence_order_is_not_identity() -> None:
    from solus_api.connectors.onshape_circle_geometry import verify_connector_frame

    before, after = roots()
    other = {"path": ["other"], "transform": TRANSFORM.copy()}
    before["occurrences"].append(other)
    after["occurrences"].insert(0, copy.deepcopy(other))
    assert verify_connector_frame(
        before, after, "created", "instance+/", {"origin": [1, 2, 3], "axis": [0, 0, 1]}
    )["origin"] == [1, 2, 3]


def test_circle_operation_has_state_bound_normal_build_authority() -> None:
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
        t for t in registry.tools() if t.descriptor.name == "onshape.create_circle_mate_connector"
    )
    assert tool.requires_complete_preview  # type: ignore[attr-defined]  # set dynamically on the concrete tool
    assert getattr(tool, "_build_authority", None) is not None
