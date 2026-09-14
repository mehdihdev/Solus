"""Compact inspection reports measured circles without deciding mechanical mates."""

import copy
import json
import math
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.httpcache import InMemoryCacheStore
from solus_api.connectors.integration_cache import IntegrationCache
from solus_api.connectors.onshape import OnshapeConnector
from solus_api.connectors.onshape_ops import operation_by_name

ARGS = {
    "document_id": "doc",
    "workspace_id": "ws",
    "element_id": "assembly",
    "_documents": ["doc", "donor"],
}
MATRIX = [1, 0, 0, 0.01, 0, 1, 0, 0.02, 0, 0, 1, 0.03, 0, 0, 0, 1]


def root() -> dict[str, Any]:
    return {
        "rootAssembly": {
            "documentMicroversion": "rev1",
            "configuration": "default",
            "instances": [
                {
                    "id": identity,
                    "type": "Part",
                    "suppressed": False,
                    "configuration": "default",
                    "documentId": "donor",
                    "elementId": "studio",
                    "documentMicroversion": "pinned",
                    "partId": "body",
                }
                for identity in ("instance+1", "instance/2")
            ],
            "occurrences": [
                {"path": [identity], "transform": MATRIX}
                for identity in ("instance+1", "instance/2")
            ],
        }
    }


def body() -> dict[str, Any]:
    return {
        "microversionId": "pinned",
        "errorEnum": "NO_ERROR",
        "bodies": [
            {
                "id": "body",
                "type": "SOLID",
                "edges": [
                    {
                        "id": "edge/1",
                        "curve": {
                            "type": "CIRCLE",
                            "radius": 0.002,
                            "origin": {"x": 0, "y": 0, "z": 0},
                            "normal": {"x": 0, "y": 0, "z": 1},
                        },
                        "geometry": {
                            "arcSweep": math.tau,
                            "length": math.tau * 0.002,
                            "startPoint": {"x": 0.002, "y": 0, "z": 0},
                            "endPoint": {"x": 0.002, "y": 0, "z": 0},
                        },
                    }
                ],
            }
        ],
    }


def setup(root_value=None, body_value=None, *, account="account", cache=None):
    subject = OnshapeConnector(
        client_id="id",
        client_secret="secret",
        account_ref=account,
        cache=cache or IntegrationCache(InMemoryCacheStore()),
    )
    r, b = root_value or root(), body_value or body()
    subject.get_json = AsyncMock(
        side_effect=lambda client, path, **kw: copy.deepcopy(
            b if path.endswith("/bodydetails") else r
        )
    )
    return subject


async def inspect(subject, **options):
    operation = operation_by_name("onshape.inspect_assembly_geometry")
    assert operation is not None, "Compact geometry must be exposed to SOL"
    async with httpx.AsyncClient() as client:
        return await operation.run(subject, client, {**ARGS, **options})


async def test_cold_deduplicates_donors_warm_keeps_root_fresh_and_reports_world_geometry():
    subject = setup()
    result = await inspect(subject)
    assert subject.get_json.await_count == 2
    assert result["total"] == 1
    assert result["items"][0]["center"] == [0.01, 0.02, 0.03]
    assert {member["instance_id"] for member in result["items"][0]["members"]} == {
        "instance+1",
        "instance/2",
    }
    assert all(member["edge_id"] == "edge/1" for member in result["items"][0]["members"])
    assert "mate_type" not in json.dumps(result)
    assert await inspect(subject) == result
    assert subject.get_json.await_count == 3


async def test_untracked_donor_refuses_before_any_body_request():
    subject = setup()
    with pytest.raises(ConnectorError, match="tracked"):
        await inspect(subject, _documents=["doc"])
    assert subject.get_json.await_count == 1


async def test_snapshot_binds_root_and_filters():
    r = root()
    subject = setup(r)
    first = await inspect(subject, view="circles", limit=1)
    assert first["next_offset"] == 1
    with pytest.raises(ConnectorError):
        await inspect(
            subject, view="circles", offset=1, expected_snapshot=first["snapshot"], min_radius=0.001
        )
    r["rootAssembly"]["documentMicroversion"] = "rev2"
    with pytest.raises(ConnectorError):
        await inspect(subject, view="circles", offset=1, expected_snapshot=first["snapshot"])


@pytest.mark.parametrize("damage", ["radius", "transform", "duplicate", "revision"])
async def test_malformed_geometry_or_identity_refuses(damage):
    r, b = root(), body()
    if damage == "radius":
        b["bodies"][0]["edges"][0]["curve"]["radius"] = float("nan")
    if damage == "transform":
        r["rootAssembly"]["occurrences"][0]["transform"] = [2] + MATRIX[1:]
    if damage == "duplicate":
        b["bodies"][0]["edges"] *= 2
    if damage == "revision":
        r["rootAssembly"].pop("documentMicroversion")
    with pytest.raises(ConnectorError):
        await inspect(setup(r, b))


async def test_account_cache_isolation():
    cache = IntegrationCache(InMemoryCacheStore())
    a, b = setup(cache=cache), setup(account="other", cache=cache)
    await inspect(a)
    await inspect(b)
    assert a.get_json.await_count == b.get_json.await_count == 2


async def test_actual_model_containment_preserves_whole_observations():
    from solus_api.agent.prompt import contain_result
    from solus_api.agent.tools.shapes import ToolCall, ToolResult

    result = await inspect(setup(), view="circles", limit=10)
    outcome = contain_result(
        ToolCall(tool="onshape.inspect_assembly_geometry", args={}),
        ToolResult(call_id="inspection", ok=True, value=result),
    )
    assert len(outcome.content) < 3000
    assert json.loads(outcome.content)["value"] == result


async def test_caps_refuse_before_donor_reads():
    r = root()
    original = r["rootAssembly"]["instances"][0]
    r["rootAssembly"]["instances"] = [{**original, "id": f"instance{i}"} for i in range(65)]
    r["rootAssembly"]["occurrences"] = [
        {"path": [f"instance{i}"], "transform": MATRIX} for i in range(65)
    ]
    subject = setup(r)
    with pytest.raises(ConnectorError):
        await inspect(subject)
    assert subject.get_json.await_count == 1


async def test_nested_and_suppressed_instances_are_explicitly_excluded():
    r = root()
    r["rootAssembly"]["instances"][0]["type"] = "Assembly"
    r["rootAssembly"]["instances"][1]["suppressed"] = True
    subject = setup(r)
    result = await inspect(subject)
    assert result["coverage"]["excluded"] == {
        "nested": 1,
        "suppressed": 1,
        "configured": 0,
        "unsupported": 0,
    }
    assert result["total"] == 0
    assert subject.get_json.await_count == 1


@pytest.mark.parametrize(
    "options",
    [
        {"instance_ids": ["instance+1", "instance+1"]},
        {"instance_ids": ["../bad"]},
        {"instance_ids": []},
        {"min_radius": -1},
        {"min_radius": 0.01, "max_radius": 0.001},
        {"min_radius": True},
        {"min_radius": float("inf")},
        {"offset": 1},
        {"limit": 11},
        {"unknown": "field"},
        {"view": "mates"},
    ],
)
async def test_bad_arguments_do_not_fetch(options):
    subject = setup()
    with pytest.raises(ConnectorError):
        await inspect(subject, **options)
    assert subject.get_json.await_count == 0


async def test_four_donor_bound_is_checked_before_fetching_any_donor():
    r = root()
    original = r["rootAssembly"]["instances"][0]
    r["rootAssembly"]["instances"] = [
        {**original, "id": f"i{i}", "elementId": f"studio{i}"} for i in range(5)
    ]
    r["rootAssembly"]["occurrences"] = [{"path": [f"i{i}"], "transform": MATRIX} for i in range(5)]
    subject = setup(r)
    with pytest.raises(ConnectorError):
        await inspect(subject)
    assert subject.get_json.await_count == 1


async def test_filter_can_bound_work_and_radius_filters_do_not_invent_groups():
    subject = setup()
    result = await inspect(
        subject, instance_ids=["instance+1"], view="circles", min_radius=0.002, max_radius=0.002
    )
    assert result["total"] == 1
    assert result["coverage"]["inspected_instances"] == 1
    assert (await inspect(subject, min_radius=0.003))["total"] == 0
    assert (await inspect(subject, instance_ids=["instance+1"]))["total"] == 0


async def test_arc_is_excluded_but_full_circle_with_bad_endpoint_is_refused():
    b = body()
    b["bodies"][0]["edges"][0]["geometry"]["arcSweep"] = math.pi
    assert (await inspect(setup(body_value=b)))["total"] == 0
    b = body()
    b["bodies"][0]["edges"][0]["geometry"]["endPoint"]["x"] = 0.003
    with pytest.raises(ConnectorError):
        await inspect(setup(body_value=b))


async def test_large_complete_group_refuses_instead_of_truncating_members():
    r = root()
    original = r["rootAssembly"]["instances"][0]
    r["rootAssembly"]["instances"] = [{**original, "id": f"i{i}"} for i in range(16)]
    r["rootAssembly"]["occurrences"] = [{"path": [f"i{i}"], "transform": MATRIX} for i in range(16)]
    with pytest.raises(ConnectorError, match="complete observation"):
        await inspect(setup(r))


async def test_primitive_cap_precedes_radius_filter():
    b = body()
    edge = b["bodies"][0]["edges"][0]
    b["bodies"][0]["edges"] = [{**edge, "id": f"e{i}"} for i in range(1001)]
    with pytest.raises(ConnectorError, match="2000"):
        await inspect(setup(body_value=b), min_radius=100)


async def test_coincidence_uses_signed_world_normals_and_position_tolerance():
    r = root()
    matrix = list(MATRIX)
    matrix[3] += 2e-8
    r["rootAssembly"]["occurrences"][1]["transform"] = matrix
    assert (await inspect(setup(r)))["total"] == 0
    matrix[3] = MATRIX[3]
    matrix[5] = -1
    matrix[10] = -1
    result = await inspect(setup(r))
    assert result["total"] == 1
    assert result["items"][0]["members"][1]["normal"] == [0, 0, -1]


@pytest.mark.parametrize("where", ["root", "donor"])
async def test_incomplete_vendor_envelope_never_reports_empty_or_complete_inspection(where):
    r, b = root(), body()
    (r if where == "root" else b)["incomplete"] = True
    with pytest.raises(ConnectorError):
        await inspect(setup(r, b))


async def test_incomplete_donor_is_not_cached_as_a_verified_revision():
    b = body()
    b["incomplete"] = True
    subject = setup(body_value=b)
    with pytest.raises(ConnectorError):
        await inspect(subject)
    b.pop("incomplete")
    assert (await inspect(subject))["total"] == 1
    assert subject.get_json.await_count == 4


async def test_continuation_binds_effective_default_workspace():
    subject = setup()
    subject.default_workspace = AsyncMock(side_effect=["firstws", "otherws"])
    first = await inspect(subject, workspace_id=None, view="circles", limit=1)
    with pytest.raises(ConnectorError):
        await inspect(
            subject,
            workspace_id=None,
            view="circles",
            offset=1,
            expected_snapshot=first["snapshot"],
        )


async def test_legacy_incomplete_cache_hit_cannot_bypass_inspection_validation():
    from solus_api.connectors.onshape_read_cache import OnshapeReadCache

    cache = IntegrationCache(InMemoryCacheStore())
    incomplete = body()
    incomplete["incomplete"] = True
    await OnshapeReadCache(cache, "account").fetch(
        document_id="donor",
        element_id="studio",
        revision_kind="m",
        revision_id="pinned",
        kind="donor_geometry",
        fetch=AsyncMock(return_value=incomplete),
    )
    subject = setup(cache=cache)
    with pytest.raises(ConnectorError):
        await inspect(subject)
    assert subject.get_json.await_count == 1


async def test_pagination_ignores_unrelated_donor_face_metadata_drift():
    payload = body()
    payload["bodies"][0]["faces"] = [{"id": "face", "area": 2.956461901243658e-05}]
    subject = setup()
    subject.immutable_body_details = AsyncMock(side_effect=lambda *a, **kw: copy.deepcopy(payload))
    first = await inspect(subject, view="circles", limit=1)
    payload["bodies"][0]["faces"][0]["area"] = 2.9564619012436748e-05
    second = await inspect(subject, view="circles", offset=1, expected_snapshot=first["snapshot"])
    assert second["snapshot"] == first["snapshot"]
    assert second["items"][0]["instance_id"] == "instance/2"


@pytest.mark.parametrize("change", ["circle", "pose", "donor_revision"])
async def test_pagination_retains_geometry_pose_and_donor_revision_binding(change):
    assembly, payload = root(), body()
    subject = setup(assembly)
    subject.immutable_body_details = AsyncMock(side_effect=lambda *a, **kw: copy.deepcopy(payload))
    first = await inspect(subject, view="circles", limit=1)
    if change == "circle":
        edge = payload["bodies"][0]["edges"][0]
        edge["curve"]["radius"] = 0.003
        edge["geometry"]["length"] = math.tau * 0.003
        for key in ("startPoint", "endPoint"):
            edge["geometry"][key]["x"] = 0.003
    elif change == "pose":
        assembly["rootAssembly"]["occurrences"][0]["transform"] = [*MATRIX]
        assembly["rootAssembly"]["occurrences"][0]["transform"][3] += 0.001
    else:
        for instance in assembly["rootAssembly"]["instances"]:
            instance["documentMicroversion"] = "newrevision"
        payload["microversionId"] = "newrevision"
    with pytest.raises(ConnectorError, match="changed"):
        await inspect(subject, view="circles", offset=1, expected_snapshot=first["snapshot"])
