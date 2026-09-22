"""Onshape WRITE operations — SOLUS-ONS-A3.

What these tests hold in place, in order of how much damage the alternative does:

1. **Setting one variable never destroys the others.** `POST .../variables`
   replaces the whole table, so the operation reads first and merges. A naive
   implementation silently deletes every other variable in the studio.
2. **No BTM payload is ever invented.** The concrete value fields of
   `BTMParameterQuantity-147` and friends are NOT published in Onshape's OpenAPI
   spec (verified: every subtype is a `btType`-only stub). So a feature's
   parameters are built from the LIVE `featurespecs` default, and anything that
   cannot be derived that way is refused rather than guessed.
3. **A write is un-dispatchable until a human approves the concrete diff**, and
   the diff shown is the diff that runs.

Fixture provenance is recorded per constant in `fixtures/onshape_sample.py`.
Everything here is respx-mocked; no network, no live tenant.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fixtures.onshape_sample import (
    ADD_FEATURE_RESPONSE,
    FEATURE_SPECS_ALT_VALUE_FIELD,
    FEATURE_SPECS_WITH_DEFAULTS,
    VARIABLES,
    WORKSPACE_INFO,
)
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_confirmation import PreviewBinding
from solus_api.connectors.onshape_ops import (
    READ_OPERATIONS,
    WRITE_OPERATIONS,
    operation_by_name,
)

DID, WID, EID = "d1", "w1", "e1"
_VARS_PATH = f"/api/v6/variables/d/{DID}/w/{WID}/e/{EID}/variables"
_SPECS_PATH = f"/api/v6/partstudios/d/{DID}/m/mvabc/e/{EID}/featurespecs"
_FEATURES_PATH = f"/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}/features"


def _conn() -> OnshapeConnector:
    return OnshapeConnector(client_id="cid", client_secret="csecret")


async def _run(name: str, args: dict[str, Any]) -> Any:
    operation = operation_by_name(name)
    assert operation is not None
    connector = _conn()
    async with connector.http(Credentials(token="t")) as client:
        if name == "onshape.set_variable":
            assert operation.preview is not None
            binding = PreviewBinding()
            binding.remember(args, await operation.preview(connector, client, args))
            with binding.execution(args):
                return await operation.run(connector, client, args)
        return await operation.run(connector, client, args)


async def _preview(name: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    operation = operation_by_name(name)
    assert operation is not None and operation.preview is not None
    connector = _conn()
    async with connector.http(Credentials(token="t")) as client:
        return await operation.preview(connector, client, args)


def _mock_variables(router: respx.MockRouter) -> None:
    router.get(f"{ONSHAPE_API_BASE}/api/v6/documents/{DID}").mock(
        httpx.Response(200, json=WORKSPACE_INFO)
    )

    def observed(request):
        writes = [
            call
            for call in router.calls
            if call.request.method == "POST" and call.request.url.path == _VARS_PATH
        ]
        variables = json.loads(writes[-1].request.content) if writes else VARIABLES[0]["variables"]
        return httpx.Response(200, json=[{"variables": variables}])

    router.get(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(side_effect=observed)


# ------------------------------------------------------------- registration


def test_writes_are_confirmation_gated_and_reads_are_not() -> None:
    assert WRITE_OPERATIONS, "A3 ships write operations"
    assert all(op.requires_confirmation for op in WRITE_OPERATIONS)
    assert not any(op.requires_confirmation for op in READ_OPERATIONS)


def test_every_write_can_describe_its_own_change() -> None:
    """A user approving a bare action name is not meaningful consent."""
    assert all(op.preview is not None for op in WRITE_OPERATIONS)


def test_writes_are_tagged_so_the_grant_check_has_something_to_key_off() -> None:
    assert all("write" in op.tags for op in WRITE_OPERATIONS)
    assert not any("write" in op.tags for op in READ_OPERATIONS)


# ---------------------------------------------------------- set_variable


@respx.mock
async def test_set_variable_merges_rather_than_replacing_the_table() -> None:
    """The endpoint replaces the whole studio. Writing one variable must not
    delete the rest — this is the data-loss case."""
    _mock_variables(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=[]))

    await _run(
        "onshape.set_variable",
        {"document_id": DID, "element_id": EID, "name": "width", "expression": "150 mm"},
    )

    body = posted.calls[0].request.read().decode()
    import json

    sent = json.loads(body)
    assert {v["name"] for v in sent} == {"width", "count"}
    assert next(v for v in sent if v["name"] == "width")["expression"] == "150 mm"
    # The untouched variable keeps its own definition, not a fabricated one.
    assert next(v for v in sent if v["name"] == "count")["expression"] == "4"


@respx.mock
async def test_set_variable_creates_one_that_does_not_exist_yet() -> None:
    _mock_variables(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=[]))

    result = await _run(
        "onshape.set_variable",
        {
            "document_id": DID,
            "element_id": EID,
            "name": "height",
            "expression": "40 mm",
            "type": "LENGTH",
        },
    )

    import json

    sent = json.loads(posted.calls[0].request.read().decode())
    assert next(v for v in sent if v["name"] == "height")["expression"] == "40 mm"
    assert result["created"] is True


@respx.mock
async def test_set_variable_rejects_a_name_onshape_would_reject() -> None:
    """`BTVariableParams.name` is `^[a-zA-Z_][a-zA-Z0-9_]*$`. Validating here
    turns a confusing 400 into a usable message — and stops a crafted name from
    reaching the payload."""
    _mock_variables(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.set_variable",
            {"document_id": DID, "element_id": EID, "name": "1 bad", "expression": "1"},
        )

    assert exc.value.code == "config_invalid"


@respx.mock
async def test_new_variable_defaults_to_a_type_rather_than_failing() -> None:
    """`type` is required by Onshape but a model rarely supplies it; ANY is the
    honest default because it accepts whatever the expression evaluates to."""
    _mock_variables(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=[]))

    await _run(
        "onshape.set_variable",
        {"document_id": DID, "element_id": EID, "name": "depth", "expression": "5 mm"},
    )

    import json

    sent = json.loads(posted.calls[0].request.read().decode())
    assert next(v for v in sent if v["name"] == "depth")["type"] == "ANY"


@respx.mock
async def test_set_variable_preview_shows_before_and_after() -> None:
    _mock_variables(respx.mock)

    rows = await _preview(
        "onshape.set_variable",
        {"document_id": DID, "element_id": EID, "name": "width", "expression": "150 mm"},
    )

    assert len(rows) == 2
    by_name = {row["label"]: row for row in rows}
    assert json.loads(by_name["width"]["before"])["expression"] == "120 mm"
    assert json.loads(by_name["width"]["after"])["expression"] == "150 mm"
    assert by_name["count"]["before"] == by_name["count"]["after"]
    assert json.loads(by_name["count"]["after"])["type"] == "NUMBER"


@respx.mock
async def test_preview_of_a_new_variable_has_no_before() -> None:
    _mock_variables(respx.mock)

    rows = await _preview(
        "onshape.set_variable",
        {"document_id": DID, "element_id": EID, "name": "height", "expression": "40 mm"},
    )

    assert len(rows) == 3
    added = next(row for row in rows if row["label"] == "height")
    assert added["before"] is None
    assert json.loads(added["after"]) == {"name": "height", "type": "ANY", "expression": "40 mm"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        [None],
        [{}],
        [{"variables": {}}],
        [{"variables": [None]}],
        [{"variables": [{"name": "x", "expression": "1"}]}],
        [{"variables": [{"name": "x", "type": "NUMBER", "expression": 1}]}],
        [{"variables": [{"name": "x", "type": "NUMBER", "expression": "1", "description": False}]}],
        [
            {"variables": [{"name": "x", "type": "NUMBER", "expression": "1"}]},
            {"variables": [{"name": "x", "type": "NUMBER", "expression": "2"}]},
        ],
    ],
)
@pytest.mark.parametrize("action", ["read", "preview", "write"])
@respx.mock
async def test_variable_malformed_table_never_drops_entries(body, action):
    _mock_variables(respx.mock)
    respx.get(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=body))
    posted = respx.post(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=[]))
    args = {"document_id": DID, "element_id": EID, "name": "width", "expression": "150 mm"}
    with pytest.raises(ConnectorError):
        if action == "read":
            await _run("onshape.get_variables", args)
        elif action == "preview":
            await _preview("onshape.set_variable", args)
        else:
            await _run("onshape.set_variable", args)
    assert not posted.called


@pytest.mark.parametrize("readback", [VARIABLES, {}, [{"variables": []}]])
@respx.mock
async def test_variable_postwrite_mismatch_is_uncertain(readback):
    _mock_variables(respx.mock)
    respx.get(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(
        side_effect=[
            httpx.Response(200, json=VARIABLES),
            httpx.Response(200, json=VARIABLES),
            httpx.Response(200, json=readback),
        ]
    )
    posted = respx.post(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=[]))
    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.set_variable",
            {"document_id": DID, "element_id": EID, "name": "width", "expression": "150 mm"},
        )
    assert posted.call_count == 1
    assert exc.value.code == "mutation_unverified"


@respx.mock
async def test_variable_complete_preview_binds_type_and_empty_description():
    _mock_variables(respx.mock)
    body = [
        {
            "variables": [
                {"name": "width", "type": "LENGTH", "expression": "120 mm", "description": ""}
            ]
        }
    ]
    respx.get(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=body))
    rows = await _preview(
        "onshape.set_variable",
        {
            "document_id": DID,
            "element_id": EID,
            "name": "width",
            "expression": "150 mm",
            "type": "ANY",
        },
    )
    assert json.loads(rows[0]["before"])["type"] == "LENGTH"
    assert json.loads(rows[0]["after"]) == {
        "name": "width",
        "type": "ANY",
        "expression": "150 mm",
        "description": "",
    }


@pytest.mark.parametrize("count,expression", [(41, "1"), (1, "1" * 401)])
@respx.mock
async def test_variable_preview_refuses_incomplete_card(count, expression):
    _mock_variables(respx.mock)
    body = [
        {
            "variables": [
                {"name": f"v{i}", "type": "NUMBER", "expression": expression} for i in range(count)
            ]
        }
    ]
    respx.get(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=body))
    with pytest.raises(ConnectorError):
        await _preview(
            "onshape.set_variable",
            {"document_id": DID, "element_id": EID, "name": "v0", "expression": "2"},
        )


@respx.mock
async def test_variable_failed_postwrite_read_is_uncertain():
    _mock_variables(respx.mock)
    respx.get(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(
        side_effect=[
            httpx.Response(200, json=VARIABLES),
            httpx.Response(200, json=VARIABLES),
            httpx.Response(503, json={"message": "unavailable"}),
        ]
    )
    respx.post(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=[]))
    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.set_variable",
            {"document_id": DID, "element_id": EID, "name": "width", "expression": "150 mm"},
        )
    assert exc.value.code == "mutation_unverified"


@pytest.mark.parametrize("bound", [False, True])
@respx.mock
async def test_variable_requires_unchanged_active_binding_before_post(bound):
    _mock_variables(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=[]))
    args = {"document_id": DID, "element_id": EID, "name": "width", "expression": "150 mm"}
    operation = operation_by_name("onshape.set_variable")
    connector = _conn()
    async with connector.http(Credentials(token="t")) as client:
        if bound:
            binding = PreviewBinding()
            binding.remember(args, await operation.preview(connector, client, args))
            changed = [{"variables": [{"name": "width", "type": "LENGTH", "expression": "121 mm"}]}]
            respx.get(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=changed))
            with binding.execution(args), pytest.raises(ConnectorError) as exc:
                await operation.run(connector, client, args)
        else:
            with pytest.raises(ConnectorError) as exc:
                await operation.run(connector, client, args)
    assert exc.value.code == "stale_state"
    assert not posted.called


# ------------------------------------------------------------ add_feature


#: The write envelope `GET /features` hands back for a write to echo.
_ENVELOPE = {
    "features": [],
    "serializationVersion": "1.2.7",
    "sourceMicroversion": "mvabc",
    "libraryVersion": 2522,
}


def _mock_specs(
    router: respx.MockRouter, specs: dict[str, Any] = FEATURE_SPECS_WITH_DEFAULTS
) -> None:
    router.get(f"{ONSHAPE_API_BASE}/api/v6/documents/{DID}").mock(
        httpx.Response(200, json=WORKSPACE_INFO)
    )
    router.get(f"{ONSHAPE_API_BASE}{_SPECS_PATH}").mock(httpx.Response(200, json=specs))

    def tree(request):
        import copy

        result = copy.deepcopy(_ENVELOPE)
        if any(call.request.method == "POST" for call in router.calls):
            result["features"] = [copy.deepcopy(ADD_FEATURE_RESPONSE["feature"])]
            result["featureStates"] = {"F9": {"featureStatus": "OK"}}
        return httpx.Response(200, json=result)

    router.get(f"{ONSHAPE_API_BASE}{_FEATURES_PATH}").mock(side_effect=tree)


@respx.mock
async def test_add_feature_builds_parameters_from_the_live_spec_default() -> None:
    """The BTM value fields are unpublished, so the shape is CLONED from the
    spec's own default parameter object and only its value is replaced."""
    _mock_specs(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_FEATURES_PATH}").mock(
        httpx.Response(200, json=ADD_FEATURE_RESPONSE)
    )

    await _run(
        "onshape.add_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_type": "extrude",
            "name": "Boss",
            "parameters": {"depth": "12 mm"},
        },
    )

    import json

    sent = json.loads(posted.calls[0].request.read().decode())
    depth = next(p for p in sent["feature"]["parameters"] if p["parameterId"] == "depth")
    assert depth["btType"] == "BTMParameterQuantity-147"
    assert depth["expression"] == "12 mm"


@respx.mock
async def test_add_feature_follows_whatever_value_field_the_spec_default_uses() -> None:
    """The load-bearing property behind the fixtures: nothing here knows that a
    quantity carries `expression`. Change the live default's value field and the
    operation follows it — which is why an unpublished BTM shape is safe."""
    _mock_specs(respx.mock, FEATURE_SPECS_ALT_VALUE_FIELD)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_FEATURES_PATH}").mock(
        httpx.Response(200, json=ADD_FEATURE_RESPONSE)
    )

    await _run(
        "onshape.add_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_type": "extrude",
            "name": "Boss",
            "parameters": {"depth": "12 mm"},
        },
    )

    import json

    sent = json.loads(posted.calls[0].request.read().decode())
    depth = next(p for p in sent["feature"]["parameters"] if p["parameterId"] == "depth")
    assert depth["someOtherValueField"] == "12 mm"
    assert "expression" not in depth


@respx.mock
async def test_add_feature_echoes_the_write_envelope_and_rejects_skew() -> None:
    """A payload carrying resolved ids must fail loudly on a stale microversion
    rather than silently reattaching to the wrong geometry."""
    _mock_specs(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_FEATURES_PATH}").mock(
        httpx.Response(200, json=ADD_FEATURE_RESPONSE)
    )

    await _run(
        "onshape.add_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_type": "extrude",
            "name": "Boss",
            "parameters": {"depth": "12 mm"},
        },
    )

    import json

    sent = json.loads(posted.calls[0].request.read().decode())
    assert sent["serializationVersion"] == "1.2.7"
    assert sent["sourceMicroversion"] == "mvabc"
    assert sent["libraryVersion"] == 2522
    assert sent["rejectMicroversionSkew"] is True


@respx.mock
async def test_add_feature_refuses_a_parameter_whose_shape_cannot_be_derived() -> None:
    """Guessing a payload for an unknown parameter kind is how a write corrupts a
    model. Refusing is the only honest answer."""
    _mock_specs(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.add_feature",
            {
                "document_id": DID,
                "element_id": EID,
                "feature_type": "extrude",
                "name": "Boss",
                "parameters": {"opaque": "anything"},
            },
        )

    assert exc.value.code == "config_invalid"
    assert "opaque" in exc.value.message


@respx.mock
async def test_add_feature_refuses_a_parameter_the_feature_does_not_have() -> None:
    _mock_specs(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.add_feature",
            {
                "document_id": DID,
                "element_id": EID,
                "feature_type": "extrude",
                "name": "Boss",
                "parameters": {"nonsense": "1"},
            },
        )

    assert exc.value.code == "config_invalid"


@respx.mock
async def test_add_feature_refuses_a_feature_type_this_studio_cannot_accept() -> None:
    """`featurespecs` is per-document and includes imported custom features, so it
    — not a hardcoded list — is the authority on what is valid here."""
    _mock_specs(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.add_feature",
            {
                "document_id": DID,
                "element_id": EID,
                "feature_type": "notAFeature",
                "name": "X",
                "parameters": {},
            },
        )

    assert exc.value.code == "config_invalid"


@respx.mock
async def test_add_feature_refuses_a_geometry_reference() -> None:
    """Raw deterministic ids are microversion-scoped and a model WILL reuse a
    stale one. Query parameters are A4's resolver, not a free-text argument."""
    _mock_specs(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.add_feature",
            {
                "document_id": DID,
                "element_id": EID,
                "feature_type": "extrude",
                "name": "Boss",
                "parameters": {"entities": "JCC"},
            },
        )

    assert exc.value.code == "config_invalid"


@respx.mock
async def test_add_feature_preview_names_the_feature_and_its_parameters() -> None:
    _mock_specs(respx.mock)

    rows = await _preview(
        "onshape.add_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_type": "extrude",
            "name": "Boss",
            "parameters": {"depth": "12 mm"},
        },
    )

    labels = {row["label"] for row in rows}
    assert "Boss" in labels
    assert any(row["after"] and "12 mm" in row["after"] for row in rows)
    # Adding a feature creates something: there is no before.
    assert all(row["before"] is None for row in rows)


@respx.mock
async def test_add_feature_returns_the_new_feature_id() -> None:
    _mock_specs(respx.mock)
    respx.post(f"{ONSHAPE_API_BASE}{_FEATURES_PATH}").mock(
        httpx.Response(200, json=ADD_FEATURE_RESPONSE)
    )

    result = await _run(
        "onshape.add_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_type": "extrude",
            "name": "Boss",
            "parameters": {"depth": "12 mm"},
        },
    )

    assert result["feature_id"] == "F9"
    assert result["verified"] is True
    assert respx.calls[-1].request.method == "GET"


@respx.mock
async def test_variable_empty_204_requires_fresh_complete_readback():
    _mock_variables(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_VARS_PATH}").respond(204)
    result = await _run(
        "onshape.set_variable",
        {"document_id": DID, "element_id": EID, "name": "width", "expression": "150 mm"},
    )
    assert result["expression"] == "150 mm"
    assert posted.call_count == 1
    calls = [(call.request.method, call.request.url.path) for call in respx.calls]
    assert calls[-2:] == [("POST", _VARS_PATH), ("GET", _VARS_PATH)]


@respx.mock
@pytest.mark.parametrize("readback_status", [200, 401])
async def test_variable_204_mismatch_or_failed_readback_is_uncertain(readback_status):
    _mock_variables(respx.mock)
    reads = respx.get(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(
        side_effect=[
            httpx.Response(200, json=VARIABLES),
            httpx.Response(200, json=VARIABLES),
            httpx.Response(readback_status, json=VARIABLES),
        ]
    )
    posted = respx.post(f"{ONSHAPE_API_BASE}{_VARS_PATH}").respond(204)
    with pytest.raises(ConnectorError) as error:
        await _run(
            "onshape.set_variable",
            {"document_id": DID, "element_id": EID, "name": "width", "expression": "150 mm"},
        )
    assert error.value.code == "mutation_unverified"
    assert posted.call_count == 1
    assert reads.call_count == 3


@respx.mock
async def test_unrelated_post_json_still_refuses_empty_204():
    respx.post(f"{ONSHAPE_API_BASE}{_FEATURES_PATH}").respond(204)
    connector = _conn()
    async with connector.http(Credentials(token="t")) as client:
        with pytest.raises(ConnectorError, match="malformed JSON"):
            await connector.post_json(client, _FEATURES_PATH, {}, what="feature creation")


@respx.mock
@pytest.mark.parametrize(
    "failure",
    [
        "missing_id",
        "missing",
        "duplicate",
        "name",
        "type",
        "unhealthy",
        "suppressed",
        "unauthorized",
        "post_error",
    ],
)
async def test_add_feature_requires_authoritative_healthy_readback(failure):
    import copy

    _mock_specs(respx.mock)
    created = copy.deepcopy(ADD_FEATURE_RESPONSE)
    actual = copy.deepcopy(created["feature"])
    readback = {"features": [actual], "featureStates": {"F9": {"featureStatus": "OK"}}}
    if failure == "missing_id":
        created["feature"].pop("featureId")
    elif failure == "missing":
        readback["features"] = []
    elif failure == "duplicate":
        readback["features"].append(actual)
    elif failure == "name":
        actual["name"] = "Other"
    elif failure == "type":
        actual["featureType"] = "Other"
    elif failure == "unhealthy":
        readback["featureStates"]["F9"]["featureStatus"] = "ERROR"
    elif failure == "suppressed":
        actual["suppressed"] = True
    respx.get(f"{ONSHAPE_API_BASE}{_FEATURES_PATH}").mock(
        side_effect=[
            httpx.Response(200, json=_ENVELOPE),
            httpx.Response(401 if failure == "unauthorized" else 200, json=readback),
        ]
    )
    posted = respx.post(f"{ONSHAPE_API_BASE}{_FEATURES_PATH}").respond(
        401 if failure == "post_error" else 200, json=created
    )
    with pytest.raises(ConnectorError) as error:
        await _run(
            "onshape.add_feature",
            {
                "document_id": DID,
                "element_id": EID,
                "feature_type": "extrude",
                "name": "Boss",
                "parameters": {"depth": "12 mm"},
            },
        )
    assert error.value.code == "mutation_unverified"
    assert posted.call_count == 1
