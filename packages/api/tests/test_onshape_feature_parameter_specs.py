"""Live and legacy parameter specifications share the existing narrow write validator."""

import copy
from typing import Any

import pytest
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.onshape_ops import _feature_parameters


def _spec(identity: str = "enabled") -> dict[str, Any]:
    return {
        "parameterId": identity,
        "defaultValue": {"btType": "BTMParameterBoolean-144", "value": False},
    }


@pytest.mark.parametrize("wrapped", [False, True])
def test_live_parameter_specs_preserve_existing_payload_rules(wrapped: bool) -> None:
    parameter = _spec()
    spec = {"parameters": [{"message": parameter} if wrapped else parameter]}
    before = copy.deepcopy(spec)
    assert _feature_parameters(spec, {"enabled": True}) == [
        {"btType": "BTMParameterBoolean-144", "parameterId": "enabled", "value": True}
    ]
    assert spec == before


def test_legacy_parameter_specs_remain_supported() -> None:
    parameter = _spec()
    parameter.pop("parameterId")
    assert _feature_parameters({"parameterIdToSpec": {"enabled": parameter}}, {"enabled": True})


@pytest.mark.parametrize(
    "spec",
    [
        {"parameters": None},
        {"parameters": {}},
        {"parameters": [None]},
        {"parameters": [{}]},
        {"parameters": [_spec("")]},
        {"parameters": [_spec(), _spec()]},
        {"parameters": [{"message": None}]},
        {"parameterIdToSpec": None},
        {"parameterIdToSpec": []},
        {"parameterIdToSpec": {"": _spec()}},
        {"parameterIdToSpec": {"enabled": None}},
        {"parameterIdToSpec": {"enabled": _spec("different")}},
        {"parameters": [_spec()], "parameterIdToSpec": {"enabled": _spec()}},
    ],
)
@pytest.mark.parametrize("supplied", [None, {}])
def test_malformed_or_ambiguous_complete_collection_refuses_even_without_values(
    spec: dict[str, Any], supplied: Any
) -> None:
    with pytest.raises(ConnectorError) as error:
        _feature_parameters(spec, supplied)
    assert error.value.code == "api_error"


@pytest.mark.parametrize(
    "template",
    [
        {"btType": "BTMParameterQueryList-148", "queries": []},
        {"btType": "BTMParameterQuantity-147", "expression": "1 mm", "value": 0.001},
        None,
    ],
)
def test_live_specs_do_not_widen_accepted_parameter_payloads(template: Any) -> None:
    spec = {"parameters": [{"parameterId": "field", "defaultValue": template}]}
    with pytest.raises(ConnectorError) as error:
        _feature_parameters(spec, {"field": "2 mm"})
    assert error.value.code == "config_invalid"


def test_unknown_parameter_and_non_scalar_value_remain_refused() -> None:
    for supplied in ({"unknown": True}, {"enabled": {"value": True}}):
        with pytest.raises(ConnectorError) as error:
            _feature_parameters({"parameters": [_spec()]}, supplied)
        assert error.value.code == "config_invalid"


def test_observed_empty_or_absent_collections_allow_no_parameters() -> None:
    specs: tuple[dict[str, Any], ...] = ({}, {"parameters": []}, {"parameterIdToSpec": {}})
    for spec in specs:
        assert _feature_parameters(spec, None) == []
        assert _feature_parameters(spec, {}) == []
