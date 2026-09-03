"""Building hosted tools from the PERSISTED inventory (SOLUSDEV-168).

`build_sol_registry` is synchronous and does zero I/O, and it is rebuilt on every
message, every confirmation decision and every `GET /sol/tools`. So the hosted
server is discovered live at CONNECT time and replayed from the Source here.
What that has to preserve is everything the live discovery decided — exposure,
gating, consent — plus the `preview` hook the destructive gate needs.
"""

import uuid
from typing import Any, cast

import pytest
from solus_api.agent.tools.hosted_tools import build_hosted_tools
from solus_api.agent.tools.remote_mcp import FS_MCP
from solus_api.agent.tools.tool import ToolException
from solus_api.connectors.secrets import InMemorySecretStore
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SERVER = FS_MCP.name
GET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"documentId": {"type": "string"}, "elementId": {"type": "string"}},
}
PUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "documentId": {"type": "string"},
        "elementId": {"type": "string"},
        "contents": {"type": "string"},
    },
}


def _row(remote: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": f"{SERVER}.{remote}",
        "remote_name": remote,
        "description": "vendor prose",
        "params": schema,
        "returns": {"type": "object"},
        "requires_confirmation": FS_MCP.requires_confirmation(remote),
        "consent_summary": FS_MCP.consent_summary(remote),
    }


def _inventory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {SERVER: {"tools": rows, "account_ref": "acct-1"}}


#: Never opened: these tests BUILD tools, they do not invoke them, and the
#: session factory is only reached when a tool resolves its credentials.
_NO_SESSIONS = cast("async_sessionmaker[AsyncSession]", None)


def _build(inventory: dict[str, Any] | None, *, store: Any = None) -> list[Any]:
    return build_hosted_tools(
        _NO_SESSIONS,
        uuid.uuid4(),
        secret_store=store if store is not None else InMemorySecretStore(),
        inventory=inventory,
    )


def test_no_secret_store_means_no_tools_rather_than_tools_that_always_fail() -> None:
    """The same fail-closed rule `build_onshape_tools` follows."""
    assert (
        build_hosted_tools(
            _NO_SESSIONS,
            uuid.uuid4(),
            secret_store=None,
            inventory=_inventory([_row("get_featurescript", GET_SCHEMA)]),
        )
        == []
    )


def test_an_empty_or_absent_inventory_registers_nothing() -> None:
    assert _build(None) == []
    assert _build({}) == []


def test_descriptors_round_trip_through_the_json_column() -> None:
    tools = _build(
        _inventory([_row("get_featurescript", GET_SCHEMA), _row("put_featurescript", PUT_SCHEMA)])
    )
    by_name = {t.descriptor.name: t for t in tools}
    assert set(by_name) == {f"{SERVER}.get_featurescript", f"{SERVER}.put_featurescript"}
    put = by_name[f"{SERVER}.put_featurescript"].descriptor
    assert put.requires_confirmation is True
    assert put.description_trusted is False, "a vendor's prose never phrases a consent sentence"
    assert put.consent_summary is not None
    assert put.consent_summary.startswith("Replace the whole contents")
    assert by_name[f"{SERVER}.get_featurescript"].descriptor.requires_confirmation is False


def test_gating_is_re_read_from_the_live_policy_not_trusted_from_storage() -> None:
    """A stored row is data on a JSON column. If it claimed a destructive tool
    needed no confirmation, the live spec must win."""
    tampered = _row("put_featurescript", PUT_SCHEMA)
    tampered["requires_confirmation"] = False
    tampered["consent_summary"] = "Totally safe, definitely a read"
    tool = _build(_inventory([tampered]))[0]
    assert tool.descriptor.requires_confirmation is True
    assert tool.descriptor.consent_summary == FS_MCP.consent_summary("put_featurescript")


def test_a_tool_dropped_from_the_allowlist_stops_working_without_a_re_sync() -> None:
    """An inventory captured before a tool was un-classified must not keep it
    alive — exposure is decided by the live registry, every build."""
    assert _build(_inventory([_row("logout", GET_SCHEMA)])) == []
    assert _build(_inventory([_row("some_new_vendor_tool", GET_SCHEMA)])) == []


def test_an_unknown_server_in_a_stored_grant_is_ignored() -> None:
    """The registry shrank between releases; a stale grant must not resurrect it."""
    assert _build({"a_server_we_removed": {"tools": [_row("whoami", GET_SCHEMA)]}}) == []


def test_an_unusable_stored_row_is_dropped_not_crashed_on() -> None:
    rows = [_row("get_featurescript", GET_SCHEMA), {"name": "junk"}, "not even a dict"]
    tools = _build(_inventory(rows))  # type: ignore[arg-type]
    assert [t.descriptor.name for t in tools] == [f"{SERVER}.get_featurescript"]


# --------------------------------------------------------------- the preview


def test_only_the_overwrite_tool_gets_a_preview_hook() -> None:
    """The gate duck-types `preview`. A tool that cannot describe a before → after
    must NOT advertise one, or the card silently degrades to argument rows."""
    tools = _build(
        _inventory([_row("get_featurescript", GET_SCHEMA), _row("put_featurescript", PUT_SCHEMA)])
    )
    by_name = {t.descriptor.name: t for t in tools}
    assert hasattr(by_name[f"{SERVER}.put_featurescript"], "preview")
    assert not hasattr(by_name[f"{SERVER}.get_featurescript"], "preview")


def test_the_overwrite_gets_no_preview_when_the_read_tool_is_missing() -> None:
    """Without `get_featurescript` there is nothing to diff against. Better to
    advertise no preview than one that cannot resolve a `before`."""
    tools = _build(_inventory([_row("put_featurescript", PUT_SCHEMA)]))
    assert not hasattr(tools[0], "preview")


async def test_the_preview_fails_closed_when_the_content_argument_cannot_be_found() -> None:
    """FAIL CLOSED. `_build_preview` swallows every exception and degrades to
    ARGUMENT rows — which are derived from the stored args and therefore cannot
    drift, so the R1 staleness check would pass and a whole-Feature-Studio
    overwrite would execute against a card showing a mangled truncation. The
    refusal has to happen where the swallow cannot reach it: the tool.
    """
    tools = _build(
        _inventory([_row("get_featurescript", GET_SCHEMA), _row("put_featurescript", PUT_SCHEMA)])
    )
    put = next(t for t in tools if t.descriptor.name.endswith("put_featurescript"))
    with pytest.raises(ToolException) as caught:
        # No argument the read schema does not also declare → no resolvable content.
        await put.preview({"documentId": "d", "elementId": "e"})
    assert "will not show you a diff" in caught.value.message


# ------------------------------------------------------- the loader and its ratchet


def test_only_one_place_in_the_app_builds_a_sol_registry() -> None:
    """The structural fix for the defect this file's neighbours now cover.

    `hosted_inventory` was an optional keyword on a function with three call
    sites, and every one of them omitted it — so the FeatureScript tools were
    unreachable and a fourth caller would have got it wrong too. Registry
    construction now happens in exactly one dependency; this asserts it stays
    that way, because a reviewer will not notice the fourth call site either.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "solus_api"
    callers = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if not str(path.relative_to(root)).startswith("agent/")
        and re.search(r"(?<!import )\bbuild_sol_registry\(", path.read_text("utf-8"))
    )
    assert callers == ["deps.py"], f"a registry is built outside deps.py: {callers}"


def test_a_hosted_read_may_return_more_than_the_shared_cap() -> None:
    """A Feature Studio truncated to the shared 4 000 characters is not a Feature
    Studio: SOL would reason about a prefix and confidently propose an overwrite
    built on the part it could see."""
    from solus_api.agent.prompt import TOOL_RESULT_CAP
    from solus_api.agent.tools.hosted_tools import HOSTED_READ_RESULT_CAP

    tools = _build(
        _inventory([_row("get_featurescript", GET_SCHEMA), _row("put_featurescript", PUT_SCHEMA)])
    )
    by_name = {t.descriptor.name: t.descriptor for t in tools}

    assert by_name[f"{SERVER}.get_featurescript"].result_cap == HOSTED_READ_RESULT_CAP
    assert HOSTED_READ_RESULT_CAP > TOOL_RESULT_CAP
    # A WRITE returns a status, not a payload, so it keeps the default — a
    # mutating tool has no business putting 60KB in front of the model.
    assert by_name[f"{SERVER}.put_featurescript"].result_cap is None


def test_the_cap_is_actually_applied_to_the_outcome() -> None:
    """The descriptor field is inert unless the runner passes it through."""
    from solus_api.agent.prompt import TOOL_RESULT_CAP, contain_result
    from solus_api.agent.tools.shapes import ToolCall, ToolResult

    big = ToolResult.success("c", {"contents": "x" * 40_000})
    call = ToolCall(tool="onshape_fs.get_featurescript", call_id="c")

    assert len(contain_result(call, big).content) <= TOOL_RESULT_CAP
    assert len(contain_result(call, big, cap=50_000).content) > TOOL_RESULT_CAP
