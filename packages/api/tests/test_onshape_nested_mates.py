"""Nested connector references preserve full paths and measured world frames."""

import copy
import json

import httpx
import pytest
import respx
from pydantic import ValidationError
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.onshape_mates import MATE_OPERATIONS, CircleConnectorArgs, _Mate
from test_onshape_circle_connector import TRANSFORM, part, roots
from test_onshape_mates import BASE, COMMON, DONOR, assembly, call, reads, tree

PATH = ["sub+/", "part+1"]
ARGS = {**COMMON, "occurrence_path": PATH, "edge_id": "circle+/"}


def nested():
    payload = assembly()
    root = payload["rootAssembly"]
    leaf = root["instances"][0]
    leaf["partId"] = "body+/"
    parent = {
        "id": PATH[0],
        "type": "Assembly",
        "suppressed": False,
        "configuration": "default",
        "documentId": "document",
        "elementId": "nested",
        "documentMicroversion": "ancestor",
    }
    root["instances"] = [parent]
    parent_pose = TRANSFORM.copy()
    parent_pose[3] = 100
    root["occurrences"] = [
        {"path": [PATH[0]], "transform": parent_pose},
        {"path": PATH.copy(), "transform": TRANSFORM.copy()},
    ]
    payload["subAssemblies"] = [
        {
            "documentId": "document",
            "elementId": "nested",
            "documentMicroversion": "ancestor",
            "configuration": "default",
            "instances": [leaf],
        }
    ]
    return payload


async def observe(payload, args=None):
    reads()
    respx.get(BASE).respond(200, json=payload)
    respx.get(DONOR).respond(200, json={"microversionId": "pinned", "bodies": [part()]})
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    async with connector.http(Credentials(token="fixture")) as client:
        return await _Mate.observe(connector, client, args or ARGS, "mateConnector", circle=True)


@respx.mock
async def test_nested_preview_and_query_bind_full_path_ancestors_and_world_transform():
    mate = await observe(nested())
    query = next(p for p in mate.parameters() if p["parameterId"] == "originQuery")["queries"][0]
    assert query["path"] == PATH and query["inferenceType"] == "CENTER"
    assert mate.selected["frame"]["origin"] == [1, 2, 3]
    assert mate.selected["ancestors"] == (("document", "nested", "ancestor"),)
    assert all(len(row["after"]) <= 400 for row in mate.preview())


@pytest.mark.parametrize("path", [[], ["x"] * 9, [""], ["bad\n"], ["x" * 129]])
def test_invalid_nested_paths_are_rejected(path):
    with pytest.raises(ValidationError):
        CircleConnectorArgs.model_validate(
            {k: v for k, v in {**ARGS, "occurrence_path": path}.items() if k != "_documents"}
        )


def test_root_alias_and_full_path_are_mutually_exclusive():
    with pytest.raises(ValidationError):
        CircleConnectorArgs.model_validate(
            {
                "document_id": "document",
                "element_id": "assembly",
                "name": "Fixture",
                "instance_id": "part+1",
                "occurrence_path": ["part+1"],
                "edge_id": "circle+/",
            }
        )


@pytest.mark.parametrize(
    "fault",
    [
        "untracked",
        "revision",
        "duplicate",
        "configured",
        "suppressed",
        "missing_pose",
        "invalid_pose",
    ],
)
@respx.mock
async def test_nested_authority_and_revision_faults_refuse_before_write(fault):
    payload = nested()
    parent = payload["rootAssembly"]["instances"][0]
    if fault == "untracked":
        parent["documentId"] = "foreign"
    elif fault == "revision":
        payload["subAssemblies"][0]["documentMicroversion"] = "wrong"
    elif fault == "duplicate":
        payload["subAssemblies"].append(copy.deepcopy(payload["subAssemblies"][0]))
    elif fault == "configured":
        parent["configuration"] = "custom"
    elif fault == "suppressed":
        parent["suppressed"] = True
    elif fault == "missing_pose":
        payload["rootAssembly"]["occurrences"].pop()
    else:
        payload["rootAssembly"]["occurrences"][-1]["transform"][0] = True
    with pytest.raises(ConnectorError):
        await observe(payload)
    assert not any(request.request.method == "POST" for request in respx.calls)


@pytest.mark.parametrize("fault", [None, "path", "ancestor", "donor", "pose"])
@respx.mock
async def test_created_nested_connector_requires_exact_actual_path_readback(fault):
    payload = nested()
    await observe(payload)

    def post(request):
        feature = json.loads(request.content)["feature"]
        feature["featureId"] = "created"
        after = tree()
        after["features"].append(feature)
        after["featureStates"]["created"] = {"featureStatus": "OK"}
        respx.get(f"{BASE}/features").respond(200, json=after)
        root = copy.deepcopy(payload)
        actual = roots()[1]["features"][0]
        actual["featureData"]["occurrence"] = [PATH[-1]] if fault == "path" else PATH.copy()
        if fault == "ancestor":
            root["rootAssembly"]["instances"][0]["documentMicroversion"] = "changed"
            root["subAssemblies"][0]["documentMicroversion"] = "changed"
        elif fault == "donor":
            root["subAssemblies"][0]["instances"][0]["documentMicroversion"] = "changed"
        elif fault == "pose":
            root["rootAssembly"]["occurrences"][-1]["transform"][3] += 0.001
        root["rootAssembly"]["features"] = [actual]
        respx.get(BASE).respond(200, json=root)
        return httpx.Response(200, json={"feature": feature})

    route = respx.post(f"{BASE}/features").mock(side_effect=post)
    index = next(
        i
        for i, op in enumerate(MATE_OPERATIONS)
        if op.name == "onshape.create_circle_mate_connector"
    )
    if fault:
        with pytest.raises(ConnectorError) as error:
            await call(index, args=ARGS)
        assert error.value.code == "mutation_unverified"
    else:
        assert (await call(index, args=ARGS))["world_origin_m"] == [1, 2, 3]
    assert route.call_count == 1


@respx.mock
async def test_same_leaf_identity_in_other_branch_is_not_aliased():
    payload = nested()
    root = payload["rootAssembly"]
    other = {**root["instances"][0], "id": "other"}
    root["instances"].append(other)
    shifted = TRANSFORM.copy()
    shifted[3] = 9
    root["occurrences"].extend(
        [
            {"path": ["other"], "transform": TRANSFORM.copy()},
            {"path": ["other", PATH[-1]], "transform": shifted},
        ]
    )
    mate = await observe(payload, {**ARGS, "occurrence_path": ["other", PATH[-1]]})
    assert mate.selected["frame"]["origin"] == [9, 2, 3]


@respx.mock
async def test_depth_eight_long_identity_preview_remains_complete():
    payload = nested()
    leaf = payload["subAssemblies"][0]["instances"][0]
    path = [str(i) + "x" * 127 for i in range(8)]
    leaf["id"] = path[-1]
    ancestors = [
        {
            "id": path[i],
            "type": "Assembly",
            "suppressed": False,
            "configuration": "default",
            "documentId": "document",
            "elementId": f"nested{i}",
            "documentMicroversion": f"rev{i}",
        }
        for i in range(7)
    ]
    payload["rootAssembly"]["instances"] = [ancestors[0]]
    payload["rootAssembly"]["occurrences"] = [
        {"path": path[: i + 1], "transform": TRANSFORM.copy()} for i in range(8)
    ]
    payload["subAssemblies"] = [
        {
            "documentId": "document",
            "elementId": f"nested{i}",
            "documentMicroversion": f"rev{i}",
            "configuration": "default",
            "instances": [ancestors[i + 1] if i < 6 else leaf],
        }
        for i in range(7)
    ]
    mate = await observe(payload, {**ARGS, "occurrence_path": path})
    rows = mate.preview()
    assert all(len(row["after"]) <= 400 for row in rows)
    assert all(segment in [row["after"] for row in rows] for segment in path)


def test_feature_page_reads_nested_connector_frame():
    from solus_api.connectors.onshape_assembly_read import AssemblyFeaturePage
    from test_onshape_assembly_read import fixture

    payload, tree = fixture()
    root = payload["rootAssembly"]
    root["features"][0]["featureData"]["occurrence"] = PATH.copy()
    root["occurrences"] = nested()["rootAssembly"]["occurrences"]
    item = AssemblyFeaturePage(view="features").select(payload, tree)["items"][0]
    assert item["occurrence_path"] == PATH and item["world_origin_m"] == [1, 2, 3]


@respx.mock
async def test_changed_ancestor_invalidates_bound_preview_before_post():
    from solus_api.connectors.onshape_confirmation import PreviewBinding

    payload = nested()
    mate = await observe(payload)
    binding = PreviewBinding()
    binding.remember(ARGS, mate.preview())
    payload["rootAssembly"]["instances"][0]["documentMicroversion"] = "changed"
    payload["subAssemblies"][0]["documentMicroversion"] = "changed"
    respx.get(BASE).respond(200, json=payload)
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    operation = next(
        op for op in MATE_OPERATIONS if op.name == "onshape.create_circle_mate_connector"
    )
    async with connector.http(Credentials(token="fixture")) as client:
        with binding.execution(ARGS), pytest.raises(ConnectorError) as error:
            await operation.run(connector, client, ARGS)
    assert error.value.code == "stale_state"
    assert not any(row.request.method == "POST" for row in respx.calls)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "foreign",
        "unanchored",
        "wrong_post",
        "element",
        "body",
        "foreign_ancestor",
        "unanchored_ancestor",
    ],
)
@respx.mock
async def test_postwrite_same_document_revisions_follow_only_anchored_root(fault):
    from dataclasses import replace

    mate = await observe(nested())
    before = copy.deepcopy(mate.root)
    before["documentMicroversion"] = "before"
    donor_doc = "donor" if fault == "foreign" else "document"
    prior_revision = "pinned" if fault == "unanchored" else "before"
    ancestor_doc = "donor" if fault == "foreign_ancestor" else "document"
    ancestor_revision = "pinned" if fault == "unanchored_ancestor" else "before"
    mate = replace(
        mate,
        root=before,
        selected={
            **mate.selected,
            "ancestors": ((ancestor_doc, "nested", ancestor_revision),),
            "donor": (donor_doc, "studio", prior_revision, "body+/"),
        },
    )
    payload = nested()
    root = payload["rootAssembly"]
    root["documentMicroversion"] = "after"
    root["instances"][0]["documentMicroversion"] = "after"
    root["instances"][0]["documentId"] = ancestor_doc
    sub = payload["subAssemblies"][0]
    sub["documentMicroversion"] = "after"
    sub["documentId"] = ancestor_doc
    leaf = sub["instances"][0]
    leaf.update(documentId=donor_doc, elementId="studio", documentMicroversion="after")
    if fault == "wrong_post":
        leaf["documentMicroversion"] = "unrelated"
    elif fault == "element":
        leaf["elementId"] = "different"
    elif fault == "body":
        leaf["partId"] = "different"
    actual = roots()[1]["features"][0]
    actual["featureData"]["occurrence"] = PATH.copy()
    root["features"] = [actual]
    respx.get(BASE).respond(200, json=payload)
    after = {**tree(), "sourceMicroversion": "after"}
    connector = OnshapeConnector(client_id="fixture", client_secret="fixture")
    async with connector.http(Credentials(token="fixture")) as client:
        if fault:
            with pytest.raises(ConnectorError) as error:
                await mate.verify_coordinates(connector, client, after, "created")
            assert error.value.code == "mutation_unverified"
        else:
            result = await mate.verify_coordinates(connector, client, after, "created")
            assert result["world_origin_m"] == [1, 2, 3]
