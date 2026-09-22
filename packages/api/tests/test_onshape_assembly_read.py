"""Complete bounded assembly feature evidence survives model containment."""

import copy
import json
from typing import Any

import pytest
from solus_api.connectors.contracts import ConnectorError
from test_onshape_circle_connector import roots


def fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    root = roots()[1]
    root.update(documentMicroversion="revision", configuration="default")
    tree = {
        "sourceMicroversion": "revision",
        "isComplete": True,
        "features": [
            {
                "featureId": "created",
                "name": "Connector",
                "featureType": "mateConnector",
                "suppressed": False,
            }
        ],
        "featureStates": {"created": {"featureStatus": "OK", "inactive": False}},
    }
    return {"rootAssembly": root}, tree


def select(root: Any, tree: Any, **kwargs: Any) -> Any:
    from solus_api.connectors.onshape_assembly_read import AssemblyFeaturePage

    return AssemblyFeaturePage(view="features", **kwargs).select(root, tree)


def test_complete_feature_page_contains_current_health_and_actual_world_frame() -> None:
    root, tree = fixture()
    result = select(root, tree)
    assert result["total"] == 1 and result["next_offset"] is None
    item = result["items"][0]
    assert item["feature_id"] == "created"
    assert item["health"] == {"status": "OK", "inactive": False}
    assert item["occurrence_path"] == ["instance+/"]
    assert item["world_origin_m"] == [1, 2, 3]
    assert item["world_axis"] == [0, 0, 1]
    assert "parameters" not in item
    assert len(json.dumps(result)) < 3000


@pytest.mark.parametrize(
    "bad",
    [
        "root_revision",
        "tree_revision",
        "missing_revisions",
        "health",
        "inactive",
        "duplicate",
        "frame",
        "pose",
        "incomplete",
    ],
)
def test_unverified_assembly_evidence_is_refused(bad: str) -> None:
    root, tree = fixture()
    assembly = root["rootAssembly"]
    if bad == "root_revision":
        assembly["documentMicroversion"] = "other"
    elif bad == "tree_revision":
        tree["sourceMicroversion"] = "other"
    elif bad == "missing_revisions":
        del assembly["documentMicroversion"]
        del tree["sourceMicroversion"]
    elif bad == "health":
        tree["featureStates"] = {}
    elif bad == "inactive":
        tree["featureStates"]["created"]["inactive"] = "false"
    elif bad == "duplicate":
        assembly["features"].append(copy.deepcopy(assembly["features"][0]))
    elif bad == "frame":
        assembly["features"][0]["featureData"]["mateConnectorCS"]["zAxis"] = [0, 0, 0]
    elif bad == "pose":
        assembly["occurrences"][0]["transform"][0] = True
    else:
        tree["isComplete"] = False
    with pytest.raises(ConnectorError):
        select(root, tree)


def test_pagination_requires_snapshot_and_detects_changed_health() -> None:
    root, tree = fixture()
    first = select(root, tree)
    with pytest.raises(ConnectorError):
        select(root, tree, offset=1)
    tree["featureStates"]["created"]["featureStatus"] = "ERROR"
    with pytest.raises(ConnectorError):
        select(root, tree, offset=1, expected_snapshot=first["snapshot"])
    assert select(root, tree)["items"][0]["health"]["status"] == "ERROR"


def test_feature_view_is_registered_on_existing_operation() -> None:
    from solus_api.connectors.onshape_ops import operation_by_name

    operation = operation_by_name("onshape.get_assembly_definition")
    assert operation.params["properties"]["view"]["const"] == "features"


def test_pages_keep_complete_items_and_bind_pose_changes() -> None:
    root, tree = fixture()
    first_feature = root["rootAssembly"]["features"][0]
    second = copy.deepcopy(first_feature)
    second["id"] = "second+/"
    root["rootAssembly"]["features"].append(second)
    tree["features"].append({**tree["features"][0], "featureId": "second+/"})
    tree["featureStates"]["second+/"] = {"featureStatus": "OK", "inactive": False}
    first = select(root, tree, limit=1)
    second_page = select(root, tree, limit=1, offset=1, expected_snapshot=first["snapshot"])
    assert first["next_offset"] == 1
    assert second_page["next_offset"] is None
    assert second_page["items"][0]["feature_id"] == "second+/"
    root["rootAssembly"]["occurrences"][0]["transform"][3] += 0.001
    with pytest.raises(ConnectorError):
        select(root, tree, offset=1, expected_snapshot=first["snapshot"])


def test_single_oversized_feature_refuses_instead_of_truncating() -> None:
    root, tree = fixture()
    tree["features"][0]["name"] = "x" * 4000
    with pytest.raises(ConnectorError) as error:
        select(root, tree)
    assert error.value.code == "result_too_large"


@pytest.mark.parametrize("kind", ["REVOLUTE", "FASTENED"])
def test_mate_type_is_observed_from_unique_native_parameter(kind: str) -> None:
    root, tree = fixture()
    root["rootAssembly"]["features"][0]["featureType"] = "mate"
    tree["features"][0].update(
        featureType="mate",
        parameters=[{"parameterId": "mateType", "enumName": "Mate type", "value": kind}],
    )
    assert select(root, tree)["items"][0]["mate_type"] == kind
    tree["features"][0]["parameters"] *= 2
    with pytest.raises(ConnectorError):
        select(root, tree)


@pytest.mark.parametrize("location", ["payload", "root", "tree"])
@pytest.mark.parametrize(
    "flag,value", [("incomplete", True), ("isIncomplete", True), ("errorEnum", "ERROR")]
)
def test_vendor_incomplete_or_error_envelopes_are_refused(
    location: str, flag: str, value: Any
) -> None:
    root, tree = fixture()
    target = {"payload": root, "root": root["rootAssembly"], "tree": tree}[location]
    target[flag] = value
    with pytest.raises(ConnectorError):
        select(root, tree)


async def test_feature_view_reads_fresh_root_and_tree_and_preserves_workspace() -> None:
    import respx
    from solus_api.connectors.contracts import Credentials
    from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
    from solus_api.connectors.onshape_ops import operation_by_name

    root, tree = fixture()
    url = f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/doc/w/work/e/assembly"
    with respx.mock:
        assembly = respx.get(url).respond(200, json=root)
        features = respx.get(f"{url}/features").respond(200, json=tree)
        connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
        async with connector.http(Credentials(token="fixture")) as client:
            operation = operation_by_name("onshape.get_assembly_definition")
            result = await operation.run(
                connector,
                client,
                {
                    "document_id": "doc",
                    "workspace_id": "work",
                    "element_id": "assembly",
                    "view": "features",
                },
            )
        assert result["workspace_id"] == "work"
        assert result["items"][0]["health"]["status"] == "OK"
        assert assembly.call_count == features.call_count == 1
        assert assembly.calls[0].request.url.params["includeMateConnectors"] == "true"


def test_feature_page_exposes_full_basis_for_rigid_alignment() -> None:
    root, tree = fixture()
    row = select(root, tree)["items"][0]
    assert row["world_x_axis"] == [0, 1, 0]
    assert row["world_y_axis"] == [-1, 0, 0]
