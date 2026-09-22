"""Observed occurrence labels stay truthful, bounded and snapshot-bound."""

import pytest
from solus_api.connectors.contracts import ConnectorError
from test_onshape_assembly_geometry import inspect, root, setup
from test_onshape_nested_inspection import nested_root


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize(
    "name,expected",
    [
        ("Servo housing", "Servo housing"),
        ("x" * 200, "x" * 200),
        (None, None),
        ("", None),
        ("   ", None),
        (False, None),
        ("x" * 201, None),
        ("bad\nlabel", None),
    ],
)
async def test_names_are_exact_vendor_labels_or_null(nested, name, expected):
    payload = nested_root() if nested else root()
    leaf = (
        payload["subAssemblies"][0]["instances"][0]
        if nested
        else payload["rootAssembly"]["instances"][0]
    )
    leaf["name"] = name
    result = await inspect(setup(payload), include_nested=nested, view="circles")
    path = ["sub", leaf["id"]] if nested else [leaf["id"]]
    selected = next(item for item in result["items"] if item["occurrence_path"] == path)
    assert selected["occurrence_name"] == expected


async def test_observed_rename_invalidates_continuation():
    payload = root()
    payload["rootAssembly"]["instances"][0]["name"] = "Original"
    first = await inspect(setup(payload), view="circles", limit=1)
    payload["rootAssembly"]["instances"][0]["name"] = "Renamed"
    with pytest.raises(ConnectorError, match="changed"):
        await inspect(
            setup(payload), view="circles", limit=1, offset=1, expected_snapshot=first["snapshot"]
        )
