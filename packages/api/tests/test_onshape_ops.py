"""Transport-free Onshape operations (SOLUS-ONS-A1).

These are the operations an Onshape MCP server exposes. They are deliberately
*not* tools and *not* a transport: each takes an already-authenticated client and
returns a plain dict, so the same functions serve the in-process tool registry
today and a stdio/HTTP MCP server later — including, if it ever ships, sitting on
top of Onshape's own official server.

Everything here is respx-mocked; no network.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fixtures.onshape_sample import (
    ASSEMBLY_DEFINITION,
    BODY_DETAILS,
    DOCUMENT_LIST,
    ELEMENT_LIST,
    FEATURE_SPECS,
    FEATURE_TREE,
    MASS_PROPERTIES,
    VARIABLES,
    WORKSPACE_INFO,
)
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_ops import (
    READ_OPERATIONS,
    OnshapeOperation,
    operation_by_name,
)

FEATURE_TREE = {**FEATURE_TREE, "sourceMicroversion": "mvabc"}

DID, WID, EID = "d1", "w1", "e1"


def _spec_read_path(suffix: str) -> str:
    base = f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/d1/w/w1/e/e1"
    if suffix == "featurespecs":
        respx.get(f"{base}/features").respond(200, json=FEATURE_TREE)
        base = base.replace("/w/w1/", "/m/mvabc/")
    return f"{base}/{suffix}"


def _conn() -> OnshapeConnector:
    return OnshapeConnector(client_id="cid", client_secret="csecret")


async def _run(name: str, args: dict[str, Any]) -> Any:
    connector = _conn()
    operation = operation_by_name(name)
    assert operation is not None
    async with OnshapeConnector.http(Credentials(token="at")) as client:
        return await operation.run(connector, client, args)


def _mock_workspace() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}/features").respond(
        200, json=FEATURE_TREE
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/{DID}").mock(
        return_value=httpx.Response(200, json=WORKSPACE_INFO)
    )


# --------------------------------------------------------------- the catalog


def test_every_operation_has_a_namespaced_name_and_a_schema() -> None:
    assert READ_OPERATIONS
    for operation in READ_OPERATIONS:
        assert operation.name.startswith("onshape.")
        assert operation.description
        assert operation.params["type"] == "object"
        # The model must not be able to smuggle extra keys past validation.
        assert operation.params["additionalProperties"] is False


def test_operation_names_are_unique() -> None:
    names = [operation.name for operation in READ_OPERATIONS]

    assert len(names) == len(set(names))


def test_no_read_operation_declares_itself_destructive() -> None:
    """A1 ships reads only; writes arrive in A3 behind the confirmation gate."""
    assert all(operation.requires_confirmation is False for operation in READ_OPERATIONS)


def test_operation_lookup_is_by_exact_name() -> None:
    assert operation_by_name("onshape.list_documents") is not None
    assert operation_by_name("list_documents") is None
    assert operation_by_name("onshape.nope") is None


def test_operations_never_take_a_document_scope_the_caller_did_not_ask_for() -> None:
    """No operation may accept a tenant/project argument — scope is bound by
    Solus code at tool construction, never by the model (CLAUDE.md §7)."""
    forbidden = {"project_id", "team_id", "user_id", "source_id", "secret_ref"}
    for operation in READ_OPERATIONS:
        assert not forbidden & set(operation.params.get("properties", {}))


# --------------------------------------------------------------- reads


@respx.mock
async def test_list_documents_returns_only_what_the_project_tracks() -> None:
    """SOLUSDEV-168: this is the model's MENU, and it used to be every document
    the account could open — strictly wider than the project's scope, which is
    why "change this" resolved by guessing."""
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(200, json=DOCUMENT_LIST)
    )

    result = await _run("onshape.list_documents", {"_documents": ["dA"]})

    assert [d["id"] for d in result["documents"]] == ["dA"]
    assert result["documents"][0]["name"] == "Rover chassis"


@respx.mock
async def test_list_documents_refuses_rather_than_falling_back_to_the_account() -> None:
    """An absent tracked set is a WIRING error. Falling back to the account
    listing would silently restore the hole this closes."""
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(200, json=DOCUMENT_LIST)
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _run("onshape.list_documents", {})

    assert excinfo.value.code == "config_invalid"


@respx.mock
async def test_a_project_tracking_nothing_lists_nothing_without_calling_onshape() -> None:
    route = respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(200, json=DOCUMENT_LIST)
    )

    assert await _run("onshape.list_documents", {"_documents": []}) == {"documents": []}
    assert route.call_count == 0


@respx.mock
async def test_list_elements_resolves_the_default_workspace_when_omitted() -> None:
    """The model supplies a document; making it also know the workspace id would
    be a needless failure mode."""
    _mock_workspace()
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/elements").mock(
        return_value=httpx.Response(200, json=ELEMENT_LIST)
    )

    result = await _run("onshape.list_elements", {"document_id": DID})

    assert result["workspace_id"] == WID
    assert {e["type"] for e in result["elements"]} == {"ASSEMBLY", "PARTSTUDIO"}


@respx.mock
async def test_get_feature_tree_returns_features_and_the_write_envelope() -> None:
    """The envelope trio must travel back out: a later write echoes it so a stale
    reference fails loudly instead of silently reattaching to the wrong face."""
    _mock_workspace()
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}/features").mock(
        return_value=httpx.Response(200, json=FEATURE_TREE)
    )

    result = await _run("onshape.get_feature_tree", {"document_id": DID, "element_id": EID})

    assert [f["name"] for f in result["features"]] == ["Sketch 1", "Extrude 1"]
    assert result["envelope"] == {
        "serializationVersion": "1.2.7",
        "sourceMicroversion": "mvabc",
        "libraryVersion": 2522,
    }


@respx.mock
async def test_get_feature_specs_lists_addressable_feature_types() -> None:
    """This is how the write path discovers valid featureTypes and parameterIds
    instead of hardcoding a table that rots."""
    _mock_workspace()
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/{DID}/m/mvabc/e/{EID}/featurespecs").mock(
        return_value=httpx.Response(200, json=FEATURE_SPECS)
    )

    result = await _run("onshape.get_feature_specs", {"document_id": DID, "element_id": EID})

    assert "extrude" in {spec["featureType"] for spec in result["feature_specs"]}


@respx.mock
async def test_get_body_details_exposes_the_deterministic_ids() -> None:
    """These face/edge ids ARE the deterministic ids a feature parameter takes —
    the thing community servers never found."""
    _mock_workspace()
    route = respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}/bodydetails"
    ).mock(return_value=httpx.Response(200, json=BODY_DETAILS))

    result = await _run("onshape.get_body_details", {"document_id": DID, "element_id": EID})

    assert result["bodies"][0]["faces"][0]["id"] == "JCC"
    # Geometric data is what makes "which edge is on the left" answerable.
    assert route.calls[0].request.url.params["includeGeometricData"] == "true"


@respx.mock
async def test_get_mass_properties_reads_the_part_studio() -> None:
    _mock_workspace()
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}/massproperties").mock(
        return_value=httpx.Response(200, json=MASS_PROPERTIES)
    )

    result = await _run("onshape.get_mass_properties", {"document_id": DID, "element_id": EID})

    assert result["bodies"]["-all-"]["mass"][0] == pytest.approx(0.42)


@respx.mock
async def test_get_assembly_definition_opts_into_mates() -> None:
    """Onshape defaults every include flag to false; an assembly read that omits
    mates is silently useless for the graph."""
    _mock_workspace()
    route = respx.get(f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/w/{WID}/e/{EID}").mock(
        return_value=httpx.Response(200, json=ASSEMBLY_DEFINITION)
    )

    result = await _run("onshape.get_assembly_definition", {"document_id": DID, "element_id": EID})

    assert result["instances"][0]["name"] == "BasePlate <1>"
    assert route.calls[0].request.url.params["includeMateFeatures"] == "true"


@respx.mock
async def test_get_variables_reads_the_variable_studio() -> None:
    _mock_workspace()
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/variables/d/{DID}/w/{WID}/e/{EID}/variables").mock(
        return_value=httpx.Response(200, json=VARIABLES)
    )

    result = await _run("onshape.get_variables", {"document_id": DID, "element_id": EID})

    assert result["variables"][0]["name"] == "width"
    assert result["variables"][0]["expression"] == "120 mm"


# --------------------------------------------------------------- hardening


@pytest.mark.parametrize("bad", ["../etc", "d1/w1", "d 1", "d1?x=1", ""])
async def test_ids_are_validated_before_any_url_interpolation(bad: str) -> None:
    with pytest.raises(ConnectorError) as excinfo:
        await _run("onshape.list_elements", {"document_id": bad})

    assert excinfo.value.code == "config_invalid"


@respx.mock
async def test_an_expired_token_surfaces_as_invalid_credentials() -> None:
    """The exact code the runtime's refresh-and-retry seam keys off."""
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(return_value=httpx.Response(401))

    with pytest.raises(ConnectorError) as excinfo:
        await _run("onshape.list_documents", {"_documents": ["dA"]})

    assert excinfo.value.code == "invalid_credentials"


@respx.mock
async def test_upstream_error_text_is_never_echoed() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(500, text="secret upstream detail")
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _run("onshape.list_documents", {})

    assert "secret upstream detail" not in excinfo.value.message


@respx.mock
async def test_a_missing_element_is_not_found_not_a_generic_error() -> None:
    _mock_workspace()
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}/features").mock(
        return_value=httpx.Response(404)
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _run("onshape.get_feature_tree", {"document_id": DID, "element_id": EID})

    assert excinfo.value.code == "not_found"


@respx.mock
async def test_list_documents_is_bounded_by_onshapes_own_page_ceiling() -> None:
    route = respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(200, json=DOCUMENT_LIST)
    )

    await _run("onshape.list_documents", {"_documents": ["dA"]})

    assert int(route.calls[0].request.url.params["limit"]) <= 20


def test_operations_are_frozen_so_a_caller_cannot_rewrite_the_catalog() -> None:
    operation: OnshapeOperation = READ_OPERATIONS[0]

    with pytest.raises((AttributeError, TypeError)):
        operation.name = "onshape.evil"  # type: ignore[misc]


@respx.mock
async def test_feature_tree_preserves_live_parameter_values() -> None:
    parameters = [
        {"btType": "BTMParameterQuantity-147", "parameterId": "depth", "expression": "10 mm"},
        {"parameterId": "oppositeDirection", "value": False},
    ]
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/d1/w/w1/e/e1/features").respond(
        200,
        json={
            "features": [{"featureId": "f1", "featureType": "extrude", "parameters": parameters}]
        },
    )
    result = await _run(
        "onshape.get_feature_tree", {"document_id": DID, "workspace_id": WID, "element_id": EID}
    )
    assert result["features"][0]["parameters"] == parameters


@respx.mock
async def test_feature_specs_reads_live_parameter_collection() -> None:
    respx.get(_spec_read_path("featurespecs")).respond(
        200,
        json={
            "featureSpecs": [
                {
                    "featureType": "extrude",
                    "parameters": [
                        {"parameterId": "depth", "defaultValue": {"expression": "25 mm"}},
                        {"parameterId": "entities"},
                    ],
                }
            ]
        },
    )
    result = await _run(
        "onshape.get_feature_specs", {"document_id": DID, "workspace_id": WID, "element_id": EID}
    )
    assert result["feature_specs"][0]["parameter_ids"] == ["depth", "entities"]


@pytest.mark.parametrize(
    "operation,key,suffix",
    [
        ("get_feature_tree", "features", "features"),
        ("get_feature_specs", "featureSpecs", "featurespecs"),
    ],
)
@pytest.mark.parametrize(
    "parameters",
    [None, {}, [None], [{"expression": "5 mm"}], [{"parameterId": "x"}, {"parameterId": "x"}]],
)
@respx.mock
async def test_malformed_feature_parameters_fail_closed(
    operation: str, key: str, suffix: str, parameters: Any
) -> None:
    respx.get(_spec_read_path(suffix)).respond(
        200, json={key: [{"featureType": "extrude", "parameters": parameters}]}
    )
    with pytest.raises(ConnectorError) as error:
        await _run(
            f"onshape.{operation}", {"document_id": DID, "workspace_id": WID, "element_id": EID}
        )
    assert error.value.code == "api_error"


@pytest.mark.parametrize(
    "operation,key,suffix",
    [
        ("get_feature_tree", "features", "features"),
        ("get_feature_specs", "featureSpecs", "featurespecs"),
    ],
)
@pytest.mark.parametrize("collection", [None, {}, [None], [{"message": None}]])
@respx.mock
async def test_malformed_feature_collections_fail_closed(
    operation: str, key: str, suffix: str, collection: Any
) -> None:
    respx.get(_spec_read_path(suffix)).respond(200, json={key: collection})
    with pytest.raises(ConnectorError) as error:
        await _run(
            f"onshape.{operation}", {"document_id": DID, "workspace_id": WID, "element_id": EID}
        )
    assert error.value.code == "api_error"


@respx.mock
async def test_legacy_feature_parameter_envelopes_preserve_values() -> None:
    parameter = {"parameterId": "depth", "expression": "10 mm"}
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/d1/w/w1/e/e1/features").respond(
        200,
        json={
            "features": [{"message": {"featureId": "f1", "parameters": [{"message": parameter}]}}]
        },
    )
    result = await _run(
        "onshape.get_feature_tree", {"document_id": DID, "workspace_id": WID, "element_id": EID}
    )
    assert result["features"][0]["parameters"] == [parameter]


@pytest.mark.parametrize(
    "operation,suffix,key,filter_key,filter_value,identity",
    [
        ("get_feature_tree", "features", "features", "feature_id", "Feature_2", "featureId"),
        (
            "get_feature_specs",
            "featurespecs",
            "featureSpecs",
            "feature_type",
            "extrude",
            "featureType",
        ),
    ],
)
@respx.mock
async def test_exact_feature_filter_returns_complete_selected_record(
    operation: str, suffix: str, key: str, filter_key: str, filter_value: str, identity: str
) -> None:
    respx.get(_spec_read_path(suffix)).respond(
        200,
        json={
            key: [
                {identity: "other", "parameters": []},
                {
                    identity: filter_value,
                    "parameters": [{"parameterId": "depth", "expression": "2 mm"}],
                },
            ],
            "sourceMicroversion": "micro",
        },
    )
    result = await _run(
        f"onshape.{operation}",
        {
            "document_id": DID,
            "workspace_id": WID,
            "element_id": EID,
            filter_key: filter_value,
        },
    )
    rows = result["features" if operation == "get_feature_tree" else "feature_specs"]
    assert len(rows) == 1
    if operation == "get_feature_tree":
        assert rows[0]["parameters"][0]["expression"] == "2 mm"
        assert result["envelope"] == {"sourceMicroversion": "micro"}
    else:
        assert rows[0]["parameter_ids"] == ["depth"]


@pytest.mark.parametrize(
    "operation,suffix,key,filter_key",
    [
        ("get_feature_tree", "features", "features", "feature_id"),
        ("get_feature_specs", "featurespecs", "featureSpecs", "feature_type"),
    ],
)
@respx.mock
async def test_missing_exact_feature_filter_is_explicit(
    operation: str, suffix: str, key: str, filter_key: str
) -> None:
    respx.get(_spec_read_path(suffix)).respond(200, json={key: []})
    with pytest.raises(ConnectorError) as error:
        await _run(
            f"onshape.{operation}",
            {"document_id": DID, "workspace_id": WID, "element_id": EID, filter_key: "missing"},
        )
    assert error.value.code == "not_found"


@pytest.mark.parametrize(
    "operation,filter_key",
    [("get_feature_tree", "feature_id"), ("get_feature_specs", "feature_type")],
)
@pytest.mark.parametrize("value", [None, "", "../bad", "a/b", "a?b", "a#b", 1])
@respx.mock
async def test_invalid_feature_filter_refused_before_vendor(
    operation: str, filter_key: str, value: Any
) -> None:
    with pytest.raises(ConnectorError) as error:
        await _run(
            f"onshape.{operation}",
            {"document_id": DID, "workspace_id": WID, "element_id": EID, filter_key: value},
        )
    assert error.value.code == "config_invalid"
    assert not respx.calls
