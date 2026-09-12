"""SOLUSDEV-251 / I4 — Onshape READ → OPERATION → WRITE → read-back against a LIVE
document through the real operations layer (`connectors/onshape_ops.py`). `-m live`
and env-gated: needs a customer OAuth access token and a scratch document.

    SOLUS_LIVE_ONSHAPE_TOKEN      an Onshape OAuth access token (never committed)
    SOLUS_LIVE_ONSHAPE_DOCUMENT   the scratch document id
    SOLUS_LIVE_ONSHAPE_ELEMENT    a Part Studio element id in it
    SOLUS_LIVE_ONSHAPE_VARIABLE   the variable to round-trip (default: solus_i4_probe)

The write goes through `onshape.set_variable`'s read-merge-write (the whole table
travels — the trap the ticket names); the read-back is `onshape.get_variables`."""

from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = pytest.mark.live

TOKEN = os.environ.get("SOLUS_LIVE_ONSHAPE_TOKEN")
DOCUMENT = os.environ.get("SOLUS_LIVE_ONSHAPE_DOCUMENT")
ELEMENT = os.environ.get("SOLUS_LIVE_ONSHAPE_ELEMENT")
VARIABLE = os.environ.get("SOLUS_LIVE_ONSHAPE_VARIABLE", "solus_i4_probe")

skip_without_env = pytest.mark.skipif(
    not (TOKEN and DOCUMENT and ELEMENT),
    reason="SOLUS_LIVE_ONSHAPE_TOKEN / _DOCUMENT / _ELEMENT unset",
)


def _names(table: Any) -> dict[str, str]:
    """`get_variables`' answer → {name: expression}, tolerant of the nested shape."""
    out: dict[str, str] = {}
    rows = table if isinstance(table, list) else (table or {}).get("variables", [])
    for row in rows:
        if isinstance(row, dict):
            for var in row.get("variables", [row]):
                if isinstance(var, dict) and var.get("name"):
                    out[str(var["name"])] = str(var.get("expression", ""))
    return out


@skip_without_env
async def test_onshape_read_operate_write_read_back() -> None:
    from solus_api.connectors.contracts import Credentials
    from solus_api.connectors.onshape import OnshapeConnector
    from solus_api.connectors.onshape_ops import operation_by_name

    connector = OnshapeConnector(client_id="", client_secret="")
    creds = Credentials(token=str(TOKEN))
    scope = {"document_id": DOCUMENT, "element_id": ELEMENT, "_documents": [DOCUMENT]}

    async def run(name: str, args: dict[str, Any]) -> Any:
        operation = operation_by_name(name)
        assert operation is not None, name
        async with connector.http(creds) as client:
            return await operation.run(connector, client, dict(args))

    # READ — the variable table.
    before = _names(await run("onshape.get_variables", scope))

    # OPERATION — a real computation on the studio.
    mass = await run("onshape.get_mass_properties", scope)
    assert isinstance(mass, dict)

    # WRITE — preview shows before → after; then the read-merge-write lands ONE entry
    # while every other variable travels back untouched.
    op = operation_by_name("onshape.set_variable")
    assert op is not None
    assert op.requires_confirmation and op.preview is not None
    args = {**scope, "name": VARIABLE, "expression": "42 mm"}
    async with connector.http(creds) as client:
        rows = await op.preview(connector, client, dict(args))
    assert rows and rows[0]["after"] == "42 mm"
    await run("onshape.set_variable", args)
    try:
        # READ BACK — the value landed and nothing else moved.
        after = _names(await run("onshape.get_variables", scope))
        assert after.get(VARIABLE) == "42 mm"
        for name, expression in before.items():
            if name != VARIABLE:
                assert after.get(name) == expression, name
    finally:
        # Leave the scratch studio as found (a probe value is not a design change).
        previous = before.get(VARIABLE)
        if previous is not None:
            await run("onshape.set_variable", {**scope, "name": VARIABLE, "expression": previous})
