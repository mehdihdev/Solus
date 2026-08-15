"""Geometry references and surgical edits — SOLUS-ONS-A4.

The invariant this whole module exists to hold: **a deterministic id is never a
tool argument.** Onshape's face/edge ids are microversion-scoped, and a model
that saw one in a previous turn WILL reuse it — silently reattaching an edit to
whatever occupies that id now. So the model names geometry with a DECLARATIVE
selector, and the selector is evaluated against the live document at the moment
the write happens. Ids exist only inside one request.

Second invariant: nothing here invents a payload. A query parameter's inner
shape is unpublished (`BTMParameterQueryList-148` is a `btType`-only stub in
Onshape's OpenAPI spec), so an edit clones the query object the feature ALREADY
carries and swaps its id list. A feature with no example to copy is refused.

Everything is respx-mocked; no network, no live tenant.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fixtures.onshape_sample import (
    BODY_DETAILS_RICH,
    FEATURE_TREE_WITH_PARAMETERS,
    WORKSPACE_INFO,
)
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_ops import operation_by_name

DID, WID, EID = "d1", "w1", "e1"
_BASE = f"/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}"


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


def _mock(router: respx.MockRouter) -> None:
    router.get(f"{ONSHAPE_API_BASE}/api/v6/documents/{DID}").mock(
        httpx.Response(200, json=WORKSPACE_INFO)
    )
    router.get(f"{ONSHAPE_API_BASE}{_BASE}/bodydetails").mock(
        httpx.Response(200, json=BODY_DETAILS_RICH)
    )
    router.get(f"{ONSHAPE_API_BASE}{_BASE}/features").mock(
        httpx.Response(200, json=FEATURE_TREE_WITH_PARAMETERS)
    )


# --------------------------------------------------------- resolve_reference


@respx.mock
async def test_resolve_reference_never_returns_a_deterministic_id() -> None:
    """The whole point. A model that can see an id can reuse a stale one."""
    _mock(respx.mock)

    result = await _run(
        "onshape.resolve_reference",
        {"document_id": DID, "element_id": EID, "selector": {"entity": "face", "largest": True}},
    )

    assert "JBIG" not in json.dumps(result)
    assert "id" not in result


@respx.mock
async def test_resolve_reference_describes_what_it_matched() -> None:
    """A user confirming an edit has to be able to tell WHICH face it means."""
    _mock(respx.mock)

    result = await _run(
        "onshape.resolve_reference",
        {"document_id": DID, "element_id": EID, "selector": {"entity": "face", "largest": True}},
    )

    assert result["matched"] == 1
    assert "plane" in result["description"]


@respx.mock
async def test_a_selector_matching_nothing_is_an_honest_failure() -> None:
    _mock(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.resolve_reference",
            {
                "document_id": DID,
                "element_id": EID,
                "selector": {"entity": "face", "surface": "torus"},
            },
        )

    assert exc.value.code == "not_found"


@respx.mock
async def test_an_ambiguous_selector_refuses_rather_than_picking_one() -> None:
    """Silently choosing among equal candidates is how an edit lands on the wrong
    face. The refusal names how many matched so the caller can narrow it."""
    _mock(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.resolve_reference",
            {
                "document_id": DID,
                "element_id": EID,
                "selector": {"entity": "face", "surface": "plane"},
            },
        )

    assert exc.value.code == "config_invalid"
    assert "3" in exc.value.message


@respx.mock
async def test_nearest_to_disambiguates_by_position() -> None:
    _mock(respx.mock)

    result = await _run(
        "onshape.resolve_reference",
        {
            "document_id": DID,
            "element_id": EID,
            "selector": {"entity": "face", "surface": "plane", "nearest_to": [0, 0, 0.05]},
        },
    )

    assert result["matched"] == 1
    assert "0.05" in result["description"]


@respx.mock
async def test_edges_resolve_by_length() -> None:
    _mock(respx.mock)

    result = await _run(
        "onshape.resolve_reference",
        {"document_id": DID, "element_id": EID, "selector": {"entity": "edge", "largest": True}},
    )

    assert result["matched"] == 1
    assert "line" in result["description"]


@respx.mock
async def test_resolve_reference_is_a_read_and_needs_no_confirmation() -> None:
    operation = operation_by_name("onshape.resolve_reference")
    assert operation is not None
    assert operation.requires_confirmation is False
    assert "write" not in operation.tags


# ----------------------------------------------------------- update_feature


@respx.mock
async def test_update_feature_changes_only_the_named_parameter() -> None:
    _mock(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_BASE}/features/featureid/F2").mock(
        httpx.Response(200, json={"feature": {"featureId": "F2"}})
    )

    await _run(
        "onshape.update_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_id": "F2",
            "parameters": {"depth": "30 mm"},
        },
    )

    sent = json.loads(posted.calls[0].request.read().decode())
    by_id = {p["parameterId"]: p for p in sent["feature"]["parameters"]}
    assert by_id["depth"]["expression"] == "30 mm"
    # Everything else survives untouched — an edit is surgical, not a rewrite.
    assert by_id["oppositeDirection"]["value"] is False


@respx.mock
async def test_update_feature_repoints_geometry_through_a_selector() -> None:
    """A selector resolves at WRITE time, against the live microversion — so a
    reference cannot go stale between the model proposing it and it applying."""
    _mock(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_BASE}/features/featureid/F2").mock(
        httpx.Response(200, json={"feature": {"featureId": "F2"}})
    )

    await _run(
        "onshape.update_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_id": "F2",
            "parameters": {"entities": {"entity": "face", "largest": True}},
        },
    )

    sent = json.loads(posted.calls[0].request.read().decode())
    entities = next(p for p in sent["feature"]["parameters"] if p["parameterId"] == "entities")
    # The id list is replaced; the query object's own shape is the feature's own.
    assert entities["queries"][0]["deterministicIds"] == ["JBIG"]
    assert entities["queries"][0]["btType"] == "BTMIndividualQuery-138"


@respx.mock
async def test_a_geometry_parameter_with_no_example_to_clone_is_refused() -> None:
    """The inner query shape is unpublished. With nothing live to copy, guessing
    it would be inventing a payload — so the edit refuses instead."""
    _mock(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.update_feature",
            {
                "document_id": DID,
                "element_id": EID,
                "feature_id": "F3",
                "parameters": {"entities": {"entity": "face", "largest": True}},
            },
        )

    assert exc.value.code == "config_invalid"


@respx.mock
async def test_update_feature_refuses_a_raw_deterministic_id() -> None:
    """Closing the loophole: a model must not be able to smuggle an id in as if
    it were a plain value."""
    _mock(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.update_feature",
            {
                "document_id": DID,
                "element_id": EID,
                "feature_id": "F2",
                "parameters": {"entities": "JBIG"},
            },
        )

    assert exc.value.code == "config_invalid"


@respx.mock
async def test_update_feature_refuses_an_unknown_feature() -> None:
    _mock(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.update_feature",
            {
                "document_id": DID,
                "element_id": EID,
                "feature_id": "F404",
                "parameters": {"depth": "1 mm"},
            },
        )

    assert exc.value.code == "not_found"


@respx.mock
async def test_update_feature_refuses_a_parameter_the_feature_does_not_have() -> None:
    _mock(respx.mock)

    with pytest.raises(ConnectorError) as exc:
        await _run(
            "onshape.update_feature",
            {
                "document_id": DID,
                "element_id": EID,
                "feature_id": "F2",
                "parameters": {"nonsense": "1"},
            },
        )

    assert exc.value.code == "config_invalid"


@respx.mock
async def test_update_feature_echoes_the_envelope_and_rejects_skew() -> None:
    _mock(respx.mock)
    posted = respx.post(f"{ONSHAPE_API_BASE}{_BASE}/features/featureid/F2").mock(
        httpx.Response(200, json={"feature": {"featureId": "F2"}})
    )

    await _run(
        "onshape.update_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_id": "F2",
            "parameters": {"depth": "30 mm"},
        },
    )

    sent = json.loads(posted.calls[0].request.read().decode())
    assert sent["sourceMicroversion"] == "mv-abc"
    assert sent["rejectMicroversionSkew"] is True


# -------------------------------------------------------------- the diff


@respx.mock
async def test_the_preview_is_the_diff_the_user_approves() -> None:
    """Which feature, which parameter, before → after. Approving "update_feature"
    tells a user nothing."""
    _mock(respx.mock)

    rows = await _preview(
        "onshape.update_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_id": "F2",
            "parameters": {"depth": "30 mm"},
        },
    )

    assert {"label": "Extrude 1 · depth", "before": "10 mm", "after": "30 mm"} in rows


@respx.mock
async def test_the_diff_of_a_geometry_change_names_the_face_not_an_id() -> None:
    _mock(respx.mock)

    rows = await _preview(
        "onshape.update_feature",
        {
            "document_id": DID,
            "element_id": EID,
            "feature_id": "F2",
            "parameters": {"entities": {"entity": "face", "largest": True}},
        },
    )

    row = next(r for r in rows if "entities" in r["label"])
    assert "JBIG" not in json.dumps(row)
    assert "plane" in (row["after"] or "")


@respx.mock
async def test_update_feature_is_confirmation_gated() -> None:
    operation = operation_by_name("onshape.update_feature")
    assert operation is not None
    assert operation.requires_confirmation is True
    assert "write" in operation.tags
