"""Complete, stable geometry pages through the existing read operation."""

import json
from typing import Any

import pytest
import respx
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_ops import operation_by_name

URL = f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/d1/w/w1/e/e1/bodydetails"
BASE = {"document_id": "d1", "workspace_id": "w1", "element_id": "e1"}
PAGE = {"body_id": "b1", "collection": "faces"}


async def run(extra: dict[str, Any]) -> dict[str, Any]:
    operation = operation_by_name("onshape.get_body_details")
    assert operation is not None
    connector = OnshapeConnector(client_id="cid", client_secret="csecret")
    async with OnshapeConnector.http(Credentials(token="at")) as client:
        return await operation.run(connector, client, {**BASE, **extra})


def vendor(faces: Any = None) -> dict[str, Any]:
    return {
        "bodies": [
            {
                "id": "b1",
                "faces": faces if faces is not None else [{"id": "f1"}, {"id": "f2"}],
                "edges": [{"id": "e1"}],
                "vertices": [],
            }
        ]
    }


@respx.mock
async def test_pages_preserve_whole_items_and_require_stable_body() -> None:
    body = vendor()
    route = respx.get(URL).respond(200, json=body)
    first = await run(PAGE)
    assert first["items"] == [{"id": "f1"}]
    assert first["next_offset"] == 1
    assert first["total"] == 2
    fingerprint = first["fingerprint"]
    assert len(fingerprint.split(":")) == 4
    second = await run({**PAGE, "offset": 1, "expected_fingerprint": fingerprint})
    assert second["items"] == [{"id": "f2"}]
    assert second["next_offset"] is None
    body["bodies"][0]["edges"].append({"id": "e2"})
    route.respond(200, json=body)
    with pytest.raises(ConnectorError) as error:
        await run({**PAGE, "offset": 1, "expected_fingerprint": fingerprint})
    assert error.value.code == "stale_state"


@respx.mock
async def test_geometry_tokens_are_not_resource_path_ids() -> None:
    body = vendor([{"id": "face+/"}])
    body["bodies"][0].update(id="body+/", edges=[{"id": "edge+/"}], vertices=[{"id": "vertex+/"}])
    body["bodies"].insert(0, {"id": "unrelated/"})
    route = respx.get(URL).respond(200, json=body)
    result = await run({"body_id": "body+/", "collection": "faces"})
    assert result["items"] == [{"id": "face+/"}]
    assert result["body_id"] == "body+/"
    assert str(route.calls[0].request.url).startswith(URL)


@pytest.mark.parametrize("identity", ["", "bad id", "bad\n", "x" * 129, "bad?", "bad%2F"])
@respx.mock
async def test_geometry_token_validation_remains_bounded(identity: str) -> None:
    respx.get(URL).respond(200, json=vendor([{"id": identity}]))
    with pytest.raises(ConnectorError):
        await run(PAGE)


@pytest.mark.parametrize(
    "extra",
    [
        {"offset": 0},
        {"body_id": "b1"},
        {"collection": "faces"},
        {**PAGE, "offset": 1},
        {**PAGE, "offset": True},
        {**PAGE, "limit": "2"},
        {**PAGE, "limit": 11},
        {**PAGE, "collection": "url"},
        {**PAGE, "body_id": "../bad"},
        {**PAGE, "expected_fingerprint": "bad"},
    ],
)
@respx.mock
async def test_invalid_paging_refused_before_request(extra: dict[str, Any]) -> None:
    with pytest.raises(ConnectorError) as error:
        await run(extra)
    assert error.value.code == "config_invalid"
    assert not respx.calls


@pytest.mark.parametrize("body", [{"bodies": []}, {"bodies": [{"id": "b1"}]}])
@respx.mock
async def test_missing_body_or_collection_is_not_found(body: dict[str, Any]) -> None:
    respx.get(URL).respond(200, json=body)
    with pytest.raises(ConnectorError) as error:
        await run(PAGE)
    assert error.value.code == "not_found"


@pytest.mark.parametrize(
    "body",
    [
        {"bodies": "bad"},
        {"bodies": [{"id": "b1"}, {"id": "b1"}]},
        vendor([{"id": "f1"}, {"id": "f1"}]),
        vendor([None]),
        vendor([{}]),
        vendor("bad"),
    ],
)
@respx.mock
async def test_malformed_vendor_records_are_not_silently_dropped(body: dict[str, Any]) -> None:
    respx.get(URL).respond(200, json=body)
    with pytest.raises(ConnectorError) as error:
        await run(PAGE)
    assert error.value.code == "api_error"


@respx.mock
async def test_adaptive_pages_and_oversize_refusal() -> None:
    items = [{"id": f"f{i}", "surface": "x" * 1100} for i in range(3)]
    route = respx.get(URL).respond(200, json=vendor(items))
    result = await run({**PAGE, "limit": 10})
    assert result["items"] == items[:2]
    assert result["next_offset"] == 2
    assert len(json.dumps(result)) < 3000
    route.respond(200, json=vendor([{"id": "huge", "surface": "x" * 3000}]))
    with pytest.raises(ConnectorError) as error:
        await run(PAGE)
    assert error.value.code == "result_too_large"


@respx.mock
async def test_empty_observed_collection_and_legacy_response() -> None:
    body = vendor([])
    respx.get(URL).respond(200, json=body)
    assert await run({}) == body
    result = await run(PAGE)
    assert result["items"] == []
    assert result["total"] == 0
    assert result["next_offset"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_geometry_is_refused_without_echoing_values(value: float) -> None:
    from solus_api.connectors.onshape_geometry import GeometryPage

    page = GeometryPage.model_validate(PAGE)
    with pytest.raises(ConnectorError) as error:
        page.select(vendor([{"id": "f1", "radius": value}]))
    assert error.value.code == "api_error"
    assert error.value.message == "The body contains invalid geometry data"


@respx.mock
async def test_edge_and_vertex_collections_and_out_of_range_offset() -> None:
    respx.get(URL).respond(200, json=vendor())
    edge = await run({"body_id": "b1", "collection": "edges"})
    assert edge["items"] == [{"id": "e1"}]
    vertices = await run({"body_id": "b1", "collection": "vertices"})
    assert vertices["items"] == []
    assert vertices["fingerprint"] == edge["fingerprint"]
    with pytest.raises(ConnectorError) as error:
        await run({**PAGE, "offset": 3, "expected_fingerprint": edge["fingerprint"]})
    assert error.value.code == "config_invalid"


@respx.mock
async def test_malformed_unrequested_geometry_is_not_hidden_by_filter() -> None:
    body = vendor()
    body["bodies"][0]["edges"] = [{"id": "same"}, {"id": "same"}]
    respx.get(URL).respond(200, json=body)
    with pytest.raises(ConnectorError) as error:
        await run(PAGE)
    assert error.value.code == "api_error"


def test_prompt_escaping_is_included_in_whole_item_size_budget() -> None:
    from solus_api.agent.prompt import contain_result
    from solus_api.agent.tools.shapes import ToolCall, ToolResult
    from solus_api.connectors.onshape_geometry import GeometryPage

    page = GeometryPage.model_validate({**PAGE, "limit": 10})
    with pytest.raises(ConnectorError) as error:
        page.select(vendor([{"id": "f1", "surface": "<" * 1000}]))
    assert error.value.code == "result_too_large"

    items = [{"id": f"f{i}", "surface": "<" * 200} for i in range(3)]
    result = page.select(vendor(items))
    assert result["items"] == items[:2]
    assert result["next_offset"] == 2
    outcome = contain_result(
        ToolCall(tool="onshape.get_body_details", args={}, call_id="geometry"),
        ToolResult.success("geometry", result),
    )
    assert json.loads(outcome.content) == {"ok": True, "value": result}


def test_redaction_expansion_is_included_in_whole_item_size_budget() -> None:
    from solus_api.agent.prompt import contain_result
    from solus_api.agent.tools.shapes import ToolCall, ToolResult
    from solus_api.connectors.onshape_geometry import GeometryPage

    item = {"id": "f1", **{f"token{i}": 0 for i in range(170)}}
    page = GeometryPage.model_validate(PAGE)
    with pytest.raises(ConnectorError) as error:
        page.select(vendor([item]))
    assert error.value.code == "result_too_large"
    small = {"id": "f1", **{f"token{i}": 0 for i in range(20)}}
    result = page.select(vendor([small]))
    outcome = contain_result(
        ToolCall(tool="onshape.get_body_details", args={}, call_id="geometry"),
        ToolResult.success("geometry", result),
    )
    encoded = json.loads(outcome.content)
    assert encoded["value"]["items"] == [
        {"id": "f1", **{f"token{i}": "[REDACTED]" for i in range(20)}}
    ]
