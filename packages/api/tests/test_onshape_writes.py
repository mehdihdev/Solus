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
from solus_api.connectors.onshape_ops import (
    READ_OPERATIONS,
    WRITE_OPERATIONS,
    operation_by_name,
)

DID, WID, EID = "d1", "w1", "e1"
_VARS_PATH = f"/api/v6/variables/d/{DID}/w/{WID}/e/{EID}/variables"
_SPECS_PATH = f"/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}/featurespecs"
_FEATURES_PATH = f"/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}/features"


def _conn() -> OnshapeConnector:
    return OnshapeConnector(client_id="cid", client_secret="csecret")


async def _run(name: str, args: dict[str, Any]) -> Any:
    operation = operation_by_name(name)
    assert operation is not None
    connector = _conn()
    async with connector.http(Credentials(token="t")) as client:
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
    router.get(f"{ONSHAPE_API_BASE}{_VARS_PATH}").mock(httpx.Response(200, json=VARIABLES))


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

    assert rows == [{"label": "width", "before": "120 mm", "after": "150 mm"}]


@respx.mock
async def test_preview_of_a_new_variable_has_no_before() -> None:
    _mock_variables(respx.mock)

    rows = await _preview(
        "onshape.set_variable",
        {"document_id": DID, "element_id": EID, "name": "height", "expression": "40 mm"},
    )

    assert rows == [{"label": "height", "before": None, "after": "40 mm"}]


# ------------------------------------------------------------ add_feature


#: The write envelope `GET /features` hands back for a write to echo.
_ENVELOPE = {
    "features": [],
    "serializationVersion": "1.2.7",
    "sourceMicroversion": "mv-abc",
    "libraryVersion": 2522,
}


def _mock_specs(
    router: respx.MockRouter, specs: dict[str, Any] = FEATURE_SPECS_WITH_DEFAULTS
) -> None:
    router.get(f"{ONSHAPE_API_BASE}/api/v6/documents/{DID}").mock(
        httpx.Response(200, json=WORKSPACE_INFO)
    )
    router.get(f"{ONSHAPE_API_BASE}{_SPECS_PATH}").mock(httpx.Response(200, json=specs))
    router.get(f"{ONSHAPE_API_BASE}{_FEATURES_PATH}").mock(httpx.Response(200, json=_ENVELOPE))


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
    assert sent["sourceMicroversion"] == "mv-abc"
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
