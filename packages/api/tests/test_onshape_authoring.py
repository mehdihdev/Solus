"""Published, bounded part reads and confirmed assembly insertion (SOLUSDEV-261)."""

import json
from typing import Any

import httpx
import pytest
import respx
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_ops import operation_by_name

ARGS = {
    "document_id": "target",
    "workspace_id": "workspace",
    "element_id": "assembly",
    "source_document_id": "donor",
    "source_element_id": "studio",
    "part_id": "part1",
    "source_microversion_id": "micro1",
}
TARGET = f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/target/w/workspace/e/assembly"
DONOR = f"{ONSHAPE_API_BASE}/api/v6/parts/d/donor/m/micro1/e/studio"
PART = {"partId": "part1", "name": "Bracket", "microversionId": "micro1"}
INSTANCE = {
    "id": "instance1",
    "documentId": "donor",
    "elementId": "studio",
    "partId": "part1",
    "documentMicroversion": "micro1",
    "type": "Part",
}


async def run(name: str, args: dict[str, Any], *, preview: bool = False) -> Any:
    operation = operation_by_name(f"onshape.{name}")
    assert operation is not None, f"missing operation {name}"
    connector = OnshapeConnector(client_id="c", client_secret="s")
    async with connector.http(Credentials(token="token")) as client:
        step = operation.preview if preview else operation.run
        assert step is not None
        return await step(connector, client, args)


def assembly(instances: list[Any], microversion: str = "targetBefore") -> dict[str, Any]:
    return {"rootAssembly": {"instances": instances, "documentMicroversion": microversion}}


@respx.mock
async def test_list_parts_returns_live_part_ids_and_microversion() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/parts/d/target/w/workspace/e/studio").respond(
        200, json=[PART]
    )
    result = await run(
        "list_parts", {"document_id": "target", "workspace_id": "workspace", "element_id": "studio"}
    )
    assert result == {"parts": [PART]}


@respx.mock
async def test_get_part_bounds_reads_exact_part() -> None:
    bounds = {"lowX": 0, "lowY": 0, "lowZ": 0, "highX": 1, "highY": 2, "highZ": 3}
    respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/parts/d/target/w/workspace/e/studio/partid/part1/boundingboxes"
    ).respond(200, json=bounds)
    result = await run(
        "get_part_bounds",
        {
            "document_id": "target",
            "workspace_id": "workspace",
            "element_id": "studio",
            "part_id": "part1",
        },
    )
    assert result == bounds


@pytest.mark.parametrize("invalid", [None, True, "1", float("inf"), float("nan"), 4])
@respx.mock
async def test_bounds_refuse_missing_non_numeric_nonfinite_or_reversed_values(invalid: Any) -> None:
    bounds = {"lowX": invalid, "lowY": 0, "lowZ": 0, "highX": 1, "highY": 2, "highZ": 3}
    respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/parts/d/target/w/workspace/e/studio/partid/part1/boundingboxes"
    ).respond(200, content=json.dumps(bounds))
    with pytest.raises(ConnectorError, match="invalid part bounds"):
        await run("get_part_bounds", {**ARGS, "element_id": "studio"})


@pytest.mark.parametrize("body", [{}, {"error": "failed"}, []])
@respx.mock
async def test_bounds_refuse_malformed_vendor_shape(body: Any) -> None:
    respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/parts/d/target/w/workspace/e/studio/partid/part1/boundingboxes"
    ).respond(200, json=body)
    with pytest.raises(ConnectorError, match="invalid part bounds"):
        await run("get_part_bounds", {**ARGS, "element_id": "studio"})


@respx.mock
async def test_insert_pins_one_part_and_reads_back_real_instance_id() -> None:
    respx.get(DONOR).respond(200, json=[PART])
    respx.get(TARGET).mock(
        side_effect=[
            httpx.Response(200, json=assembly([])),
            httpx.Response(200, json=assembly([])),
            httpx.Response(200, json=assembly([INSTANCE], "targetAfter")),
        ]
    )
    posted = respx.post(f"{TARGET}/instances").respond(200, json={})
    result = await bound_insert(ARGS)
    assert result == {"instance_ids": ["instance1"]}
    assert json.loads(posted.calls[0].request.content) == {
        "documentId": "donor",
        "elementId": "studio",
        "partId": "part1",
        "microversionId": "micro1",
        "isAssembly": False,
        "isWholePartStudio": False,
        "isHidden": False,
        "isSuppressed": False,
    }


@respx.mock
async def test_preview_names_donor_and_target_and_changes_with_target_fingerprint() -> None:
    respx.get(DONOR).respond(200, json=[PART])
    respx.get(TARGET).mock(
        side_effect=[
            httpx.Response(200, json=assembly([], "before")),
            httpx.Response(200, json=assembly([], "changed")),
        ]
    )
    before = await run("insert_part", ARGS, preview=True)
    after = await run("insert_part", ARGS, preview=True)
    assert before != after
    assert all(
        text in str(before)
        for text in ("target", "assembly", "donor", "studio", "part1", "micro1", "Bracket")
    )
    assert all(call.request.method == "GET" for call in respx.calls)


@pytest.mark.parametrize(
    "body", [{"error": "failed"}, {"success": False}, {"errorStatus": "Failure"}]
)
@respx.mock
async def test_http_success_with_vendor_failure_is_not_reported_as_inserted(
    body: dict[str, Any],
) -> None:
    respx.get(DONOR).respond(200, json=[PART])
    respx.get(TARGET).respond(200, json=assembly([]))
    respx.post(f"{TARGET}/instances").respond(200, json=body)
    with pytest.raises(ConnectorError):
        await bound_insert(ARGS)


@pytest.mark.parametrize(
    "instances",
    [
        [],
        [{**INSTANCE, "partId": "wrong"}],
        [INSTANCE, {**INSTANCE, "id": "instance2"}],
        [{**INSTANCE, "status": "DeletedElement"}],
    ],
)
@respx.mock
async def test_ambiguous_or_failed_readback_is_nonretryable(instances: list[Any]) -> None:
    respx.get(DONOR).respond(200, json=[PART])
    respx.get(TARGET).mock(
        side_effect=[
            httpx.Response(200, json=assembly([])),
            httpx.Response(200, json=assembly([])),
            httpx.Response(200, json=assembly(instances, "after")),
        ]
    )
    respx.post(f"{TARGET}/instances").respond(200, json={})
    with pytest.raises(ConnectorError) as error:
        await bound_insert(ARGS)
    assert error.value.code == "mutation_unverified"


@respx.mock
async def test_auth_failure_after_post_cannot_trigger_whole_operation_refresh_retry() -> None:
    respx.get(DONOR).respond(200, json=[PART])
    respx.get(TARGET).mock(
        side_effect=[
            httpx.Response(200, json=assembly([])),
            httpx.Response(200, json=assembly([])),
            httpx.Response(401),
        ]
    )
    post = respx.post(f"{TARGET}/instances").respond(200, json={})
    with pytest.raises(ConnectorError) as error:
        await bound_insert(ARGS)
    assert error.value.code == "mutation_unverified"
    assert post.call_count == 1


@respx.mock
async def test_missing_donor_part_refuses_before_post() -> None:
    respx.get(DONOR).respond(200, json=[])
    respx.get(TARGET).respond(200, json=assembly([]))
    with pytest.raises(ConnectorError):
        await bound_insert(ARGS)
    assert all(call.request.method == "GET" for call in respx.calls)


@pytest.mark.parametrize("key", list(ARGS))
@respx.mock
async def test_invalid_insertion_ids_never_reach_vendor(key: str) -> None:
    with pytest.raises(ConnectorError) as error:
        await bound_insert({**ARGS, key: "../bad"})
    assert error.value.code == "config_invalid"
    assert len(respx.calls) == 0


async def bound_insert(args: dict[str, Any]) -> Any:
    from solus_api.connectors.onshape_confirmation import PreviewBinding

    binding = PreviewBinding()
    binding.remember(args, await run("insert_part", args, preview=True))
    with binding.execution(args):
        return await run("insert_part", args)


@respx.mock
async def test_insert_requires_bound_preview_before_post() -> None:
    respx.get(DONOR).respond(200, json=[PART])
    respx.get(TARGET).respond(200, json=assembly([]))
    post = respx.post(f"{TARGET}/instances").respond(200, json={})
    with pytest.raises(ConnectorError) as error:
        await run("insert_part", ARGS)
    assert error.value.code == "stale_state"
    assert post.call_count == 0


@respx.mock
async def test_insert_refuses_changed_target_after_preview() -> None:
    from solus_api.connectors.onshape_confirmation import PreviewBinding

    respx.get(DONOR).respond(200, json=[PART])
    respx.get(TARGET).mock(
        side_effect=[
            httpx.Response(200, json=assembly([], "original")),
            httpx.Response(200, json=assembly([], "changed")),
        ]
    )
    post = respx.post(f"{TARGET}/instances").respond(200, json={})
    binding = PreviewBinding()
    binding.remember(ARGS, await run("insert_part", ARGS, preview=True))
    with binding.execution(ARGS), pytest.raises(ConnectorError) as error:
        await run("insert_part", ARGS)
    assert error.value.code == "stale_state"
    assert post.call_count == 0


@pytest.mark.parametrize(
    "instances", [[{}], [None], [{"id": "same"}, {"id": "same"}], [{"id": "../bad"}]]
)
@respx.mock
async def test_insert_refuses_malformed_instance_identity_before_write(
    instances: list[Any],
) -> None:
    respx.get(DONOR).respond(200, json=[PART])
    respx.get(TARGET).respond(200, json=assembly(instances))
    post = respx.post(f"{TARGET}/instances").respond(200, json={})
    with pytest.raises(ConnectorError) as error:
        await bound_insert(ARGS)
    assert error.value.code == "api_error"
    assert post.call_count == 0


@pytest.mark.parametrize("flag", ["isHidden", "isSuppressed"])
@respx.mock
async def test_insert_does_not_claim_hidden_or_suppressed_readback(flag: str) -> None:
    respx.get(DONOR).respond(200, json=[PART])
    respx.get(TARGET).mock(
        side_effect=[
            httpx.Response(200, json=assembly([])),
            httpx.Response(200, json=assembly([])),
            httpx.Response(200, json=assembly([{**INSTANCE, flag: True}], "after")),
        ]
    )
    respx.post(f"{TARGET}/instances").respond(200, json={})
    with pytest.raises(ConnectorError) as error:
        await bound_insert(ARGS)
    assert error.value.code == "mutation_unverified"
