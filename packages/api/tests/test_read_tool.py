"""SOLUSDEV-321 P1-T4 — `bounded_read_tool`, the one constructor of SOL's retrieval tools.

What the tools it builds return is tenant data bound for the model, so the factory owns the
bounds and the failure shape: at most `MAX_ROWS` rows, at most `result_cap` characters ON THE
WIRE (the prompt layer's own cut never lands) ending in a visible `…[truncated]`, every tenant
string redacted and flattened to one line, and no failure that is anything but a typed
`ToolException` for the registry to turn into a result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

import pytest
from solus_api.agent.modes import ActionMode, build_mode_dispatch
from solus_api.agent.prompt import contain_result
from solus_api.agent.runtime import build_dispatch
from solus_api.agent.tools import (
    InProcessTool,
    ToolCall,
    ToolErrorCode,
    ToolException,
    ToolRegistry,
    ToolResult,
)
from solus_api.agent.tools.read_tool import (
    FIELD_CAP,
    LIMIT_PARAM,
    MAX_ROWS,
    MORE,
    QUERY_CAP,
    QUERY_PARAM,
    RESULT_CAP,
    TRUNCATED,
    bounded_read_tool,
    int_arg,
    limit_arg,
    page_rows,
    query_arg,
    uuid_arg,
    uuid_params,
)
from solus_api.core.errors import APIError

NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
#: Every character that grows when the prompt layer encodes a result as ASCII JSON.
HOSTILE = '<<< "quote" \\ µΩ° 😀 <script>'


def _yielding(*rows: Any) -> Any:
    async def handler(_args: dict[str, Any]) -> list[Any]:
        return list(rows)

    return handler


def _probe(handler: Any, *, result_cap: int = RESULT_CAP) -> InProcessTool:
    return bounded_read_tool("probe_rows", "Probe rows.", NO_ARGS, handler, result_cap=result_cap)


async def _probe_text(tool: InProcessTool) -> str:
    return str((await tool.invoke({}))["text"])


async def _probe_wire(tool: InProcessTool) -> tuple[str, dict[str, Any]]:
    """The tool's result as the prompt layer sends it: (the content, that content parsed)."""
    call = ToolCall(tool=tool.descriptor.name)
    result = ToolResult.success(call.call_id, await tool.invoke({}))
    outcome = contain_result(call, result, cap=tool.descriptor.result_cap)
    return outcome.content, json.loads(outcome.content)


# ------------------------------------------------------------------ the descriptor


def test_descriptor_is_read_only_ungated_and_carries_the_result_cap() -> None:
    descriptor = _probe(_yielding()).descriptor
    assert descriptor.name == "probe_rows"
    assert descriptor.params == NO_ARGS
    assert descriptor.requires_confirmation is False
    assert descriptor.files_errors is False
    assert descriptor.result_cap == RESULT_CAP == 8_000
    assert descriptor.description.startswith("Probe rows.")
    assert "Read-only" in descriptor.description
    assert TRUNCATED in descriptor.description
    assert _probe(_yielding(), result_cap=1_000).descriptor.result_cap == 1_000


async def test_ungated_in_both_modes() -> None:
    """Guide refuses what `requires_confirmation` marks and Build parks it; a read is neither."""
    registry = ToolRegistry()
    registry.register(_probe(_yielding({"n": 1})))
    for mode in ActionMode:
        dispatch = build_mode_dispatch(mode, registry.list(), build_dispatch(registry, None))
        result = await dispatch(ToolCall(tool="probe_rows"))
        assert result.ok is True, mode
        assert result.value == {"text": '{"n":1}'}, mode


# --------------------------------------------------------------------- the bounds


async def test_results_capped_at_20_and_result_cap() -> None:
    over = [{"n": n} for n in range(MAX_ROWS + 5)]
    lines = (await _probe_text(_probe(_yielding(*over)))).split("\n")
    assert lines == [f'{{"n":{n}}}' for n in range(MAX_ROWS)] + [TRUNCATED]

    wide = [{"body": "x y " * 200}] * MAX_ROWS
    content, wire = await _probe_wire(_probe(_yielding(*wide)))
    assert len(content) <= RESULT_CAP
    assert wire["value"]["text"].endswith(TRUNCATED)

    content, wire = await _probe_wire(_probe(_yielding(*wide), result_cap=300))
    assert len(content) <= 300
    assert wire["value"]["text"].endswith(TRUNCATED)


def test_page_rows_shows_the_limit_and_marks_the_row_past_it() -> None:
    """A handler fetches ONE row past its limit: that row's existence is the whole answer to
    "are there more", and it is never shown."""
    found: list[Any] = [{"n": n} for n in range(4)]
    assert page_rows(found, 3) == [{"n": 0}, {"n": 1}, {"n": 2}, MORE]
    assert page_rows(found[:3], 3) == [{"n": 0}, {"n": 1}, {"n": 2}]  # all of them: no marker
    assert page_rows(found[:2], 3) == [{"n": 0}, {"n": 1}]
    assert page_rows([], 3) == []


async def test_a_marker_past_the_row_cap_becomes_the_truncation_marker() -> None:
    """At the 20-row ceiling the marker is the 21st row, and the factory's own cut says so."""
    rows = [{"n": n} for n in range(MAX_ROWS + 1)]
    lines = (await _probe_text(_probe(_yielding(*page_rows(rows, MAX_ROWS))))).split("\n")
    assert len(lines) == MAX_ROWS + 1
    assert lines[-1] == TRUNCATED


async def test_a_result_that_fits_carries_no_marker() -> None:
    text = await _probe_text(_probe(_yielding(*({"n": n} for n in range(MAX_ROWS)))))
    assert TRUNCATED not in text
    assert len(text.split("\n")) == MAX_ROWS


async def test_a_cut_falls_between_rows_and_is_marked() -> None:
    rows = [{"n": n, "pad": "p" * 90} for n in range(MAX_ROWS)]
    full = [json.dumps(row, separators=(",", ":")) for row in rows]
    kept = (await _probe_text(_probe(_yielding(*rows), result_cap=450))).split("\n")
    assert kept[-1] == TRUNCATED
    assert 0 < len(kept) - 1 < MAX_ROWS
    assert kept[:-1] == full[: len(kept) - 1]


async def test_one_row_bigger_than_the_cap_is_cut_inside_and_marked() -> None:
    text = await _probe_text(_probe(_yielding("word " * 10_000), result_cap=1_000))
    assert text.endswith(TRUNCATED)
    assert 0 < len(text) < 1_000


async def test_the_prompt_layers_own_cut_never_lands() -> None:
    """`contain_result` encodes a result as ASCII JSON — every `<`, quote and non-ASCII
    character grows — then cuts at the descriptor's cap with no marker. The factory sizes its
    clip by that encoding, so the cut it makes is the only one and it is visible."""
    rows = [{"text": HOSTILE * 12, "n": n} for n in range(MAX_ROWS)]
    content, wire = await _probe_wire(_probe(_yielding(*rows)))
    assert len(content) <= RESULT_CAP
    assert wire["value"]["text"].endswith(TRUNCATED)
    assert "<" not in content


async def test_a_long_field_is_cut_with_an_ellipsis() -> None:
    text = await _probe_text(_probe(_yielding({"body": "word " * 400})))
    body = json.loads(text)["body"]
    assert body.startswith("word word")
    assert body.endswith("…")
    assert len(body) == FIELD_CAP


# ------------------------------------------------------------------- the rendering


async def test_a_mapping_row_is_one_compact_json_object_that_skips_the_empty_fields() -> None:
    row = {
        "name": "servo 3",
        "kind": "component",
        "note": None,
        "snippet": "",
        "padding": "  \n ",
        "score": 0.5,
        "found": True,
        "at": datetime(2026, 10, 1, tzinfo=UTC),
        "id": uuid.UUID(int=7),
        "attrs": {"b": 2, "a": [1, None]},
    }
    lines = (await _probe_text(_probe(_yielding(row, "a plain line")))).split("\n")
    assert lines == [
        '{"name":"servo 3","kind":"component","score":0.5,"found":true,'
        '"at":"2026-10-01T00:00:00+00:00","id":"00000000-0000-0000-0000-000000000007",'
        '"attrs":{"b":2,"a":[1,null]}}',
        "a plain line",
    ]


async def test_an_empty_result_says_so() -> None:
    assert await _probe_text(_probe(_yielding())) == "no results"


async def test_a_text_result_is_one_row() -> None:
    async def handler(_args: dict[str, Any]) -> str:
        return "no envelope: no limits for this part"

    assert await _probe_text(_probe(handler)) == "no envelope: no limits for this part"


async def test_a_text_result_with_lines_is_still_one_row_so_several_lines_are_a_list() -> None:
    async def text(_args: dict[str, Any]) -> str:
        return "current A: 1\nvoltage V: 2"

    assert await _probe_text(_probe(text)) == "current A: 1 voltage V: 2"
    assert await _probe_text(_probe(_yielding("current A: 1", "voltage V: 2"))) == (
        "current A: 1\nvoltage V: 2"
    )


async def test_tenant_strings_are_redacted_before_they_are_bounded() -> None:
    rows = [
        {"note": "retry with password=hunter2 please", "config": {"api_key": "abc", "ok": 1}},
        "authorization: Bearer abc.def.ghi",
    ]
    text = await _probe_text(_probe(_yielding(*rows)))
    mapping, string = text.split("\n")
    assert json.loads(mapping) == {
        "note": "retry with password=[REDACTED] please",
        "config": {"api_key": "[REDACTED]", "ok": 1},
    }
    assert string == "authorization: [REDACTED]"
    for secret in ("hunter2", "abc.def.ghi", '"abc"'):
        assert secret not in text


async def test_a_secret_named_top_level_evidence_key_is_masked() -> None:
    """A producer's evidence mapping is one value of one row, so `redact_value`'s rule that a
    secret-named key masks its value sees every pair at every level, not only the nested ones."""
    evidence = {"password": "hunter2", "api_key": "abc123", "config": {"api_key": "nested"}}
    text = await _probe_text(_probe(_yielding({"evidence": evidence})))
    assert json.loads(text)["evidence"] == {
        "password": "[REDACTED]",
        "api_key": "[REDACTED]",
        "config": {"api_key": "[REDACTED]"},
    }
    for secret in ("hunter2", "abc123", "nested"):
        assert secret not in text


@pytest.mark.parametrize(
    "key",
    [
        "github_personal_access_token_for_the_deploy_bot_account",
        "SPRING_DATASOURCE_HIKARI_PASSWORD_ENCRYPTION_SECRET_KEY_NAME",
        "x" * 500 + "_password",
    ],
    ids=["entropic-token", "entropic-password", "over-the-cap-password"],
)
async def test_a_long_or_entropic_secret_named_key_still_masks_its_value(key: str) -> None:
    """The key-name rule has to read the key as its producer wrote it. Normalising the key first
    left it nothing to match — `redact_text` swaps a 40+ character key of the entropic charset
    for `[REDACTED]` whole and the cap cuts a 500+ character one — and the value showed."""
    text = await _probe_text(_probe(_yielding({"evidence": {key: "hunter2"}})))
    assert "hunter2" not in text
    (value,) = json.loads(text)["evidence"].values()
    assert value == "[REDACTED]"


async def test_tuple_and_mapping_rows_are_key_redacted() -> None:
    """`redact_value` only walks dicts and lists, so a tuple or a non-dict Mapping in a row would
    have kept a secret-named pair; the renderer turns both into plain data first."""
    row = {"hits": ({"api_key": "k1"},), "meta": MappingProxyType({"password": "p4ss"})}
    text = await _probe_text(_probe(_yielding(row)))
    assert json.loads(text) == {
        "hits": [{"api_key": "[REDACTED]"}],
        "meta": {"password": "[REDACTED]"},
    }


async def test_newlines_in_tenant_text_cannot_forge_a_row() -> None:
    text = await _probe_text(_probe(_yielding({"name": "servo\nid: 9999 | kind: admin\r\n\tx"})))
    assert text == '{"name":"servo id: 9999 | kind: admin x"}'


async def test_a_pipe_in_a_value_cannot_forge_a_field() -> None:
    hostile = 'servo", "kind": "admin | kind: admin'
    text = await _probe_text(_probe(_yielding({"name": hostile})))
    assert list(json.loads(text)) == ["name"]
    assert json.loads(text)["name"] == hostile


async def test_row_keys_are_flattened_and_cut_like_values() -> None:
    text = await _probe_text(_probe(_yielding({"two\nlines": 1, "k" * 600: 2})))
    flattened, long = list(json.loads(text))
    assert flattened == "two lines"
    assert len(long) == FIELD_CAP
    assert long.endswith("…")


# ---------------------------------------------------------------------- the failures


async def test_a_typed_failure_passes_through_untouched() -> None:
    async def handler(_args: dict[str, Any]) -> list[Any]:
        raise ToolException("No finding here", code=ToolErrorCode.NOT_FOUND)

    with pytest.raises(ToolException) as caught:
        await _probe(handler).invoke({})
    assert caught.value.code is ToolErrorCode.NOT_FOUND
    assert caught.value.message == "No finding here"


async def test_a_404_api_error_becomes_not_found_in_the_loaders_own_words() -> None:
    async def handler(_args: dict[str, Any]) -> list[Any]:
        raise APIError(404, "run_not_found", "Run not found")

    with pytest.raises(ToolException) as caught:
        await _probe(handler).invoke({})
    assert caught.value.code is ToolErrorCode.NOT_FOUND
    assert caught.value.message == "Run not found"


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("DSN postgresql://solus:hunter2@db/solus"),
        APIError(409, "conflict", "Run is locked for hunter2"),
        APIError(500, "internal", "DSN postgresql://solus:hunter2@db/solus"),
    ],
    ids=["runtime", "api-409", "api-500"],
)
async def test_an_unexpected_failure_is_a_tool_error_result_that_names_the_tool(
    caplog: pytest.LogCaptureFixture, failure: Exception
) -> None:
    """Only a 404 is the model's to hear. Any other `APIError` is as unexpected as any other
    failure: logged, and the same generic result — a 5xx must not tell the model to fix its
    arguments, and none of its text reaches the model."""

    async def handler(_args: dict[str, Any]) -> list[Any]:
        raise failure

    registry = ToolRegistry()
    registry.register(_probe(handler))
    with caplog.at_level(logging.ERROR, logger="solus.agent.tools.read"):
        result = await registry.invoke(ToolCall(tool="probe_rows"))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TOOL_ERROR
    assert result.error.message == "error: probe_rows failed"
    logged = [record for record in caplog.records if record.name == "solus.agent.tools.read"]
    assert logged and logged[0].exc_info and "probe_rows" in logged[0].getMessage()


async def test_a_failure_while_rendering_is_the_same_tool_error() -> None:
    class Unrenderable:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    with pytest.raises(ToolException) as caught:
        await _probe(_yielding({"x": Unrenderable()})).invoke({})
    assert caught.value.message == "error: probe_rows failed"


async def test_cancellation_is_never_swallowed() -> None:
    async def handler(_args: dict[str, Any]) -> list[Any]:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _probe(handler).invoke({})


# ------------------------------------------------------------------- the arguments


def test_uuid_arg_accepts_a_uuid_and_refuses_anything_else() -> None:
    wanted = uuid.uuid4()
    assert uuid_arg({"run_id": str(wanted)}, "run_id") == wanted
    for args in ({}, {"run_id": "nope"}, {"run_id": 7}, {"run_id": None}):
        with pytest.raises(ToolException) as caught:
            uuid_arg(args, "run_id")
        assert caught.value.code is ToolErrorCode.INVALID_ARGS
        assert "run_id" in caught.value.message


async def test_uuid_params_require_exactly_one_uuid() -> None:
    params = uuid_params("run_id", "The run's UUID.")
    registry = ToolRegistry()
    registry.register(bounded_read_tool("probe_rows", "Probe.", params, _yielding()))
    good = await registry.invoke(ToolCall(tool="probe_rows", args={"run_id": str(uuid.uuid4())}))
    assert good.ok is True
    for args in ({}, {"run_id": "nope"}, {"run_id": str(uuid.uuid4()), "extra": 1}):
        bad = await registry.invoke(ToolCall(tool="probe_rows", args=args))
        assert bad.error is not None
        assert bad.error.code is ToolErrorCode.INVALID_ARGS


def test_int_arg_clamps_into_one_to_high_and_falls_back_to_the_default() -> None:
    assert int_arg({}, "days", default=30, high=30) == 30
    assert int_arg({"days": "x"}, "days", default=5, high=9) == 5
    assert [int_arg({"n": n}, "n", default=5, high=9) for n in (-1, 0, 4, 9, 10)] == [1, 1, 4, 9, 9]


def test_limit_arg_defaults_and_clamps_whatever_is_asked() -> None:
    assert limit_arg({}) == 10
    assert limit_arg({"limit": "many"}) == 10
    asked = (-5, 0, 1, 7, 20, 21, 10_000)
    assert [limit_arg({"limit": n}) for n in asked] == [1, 1, 1, 7, 20, 20, 20]


def test_query_arg_trims_bounds_and_refuses_a_blank() -> None:
    assert query_arg({"q": "  servo 3  "}) == "servo 3"
    assert len(query_arg({"q": "x" * 1_000})) == QUERY_CAP == 255
    for args in ({}, {"q": ""}, {"q": "   "}):
        with pytest.raises(ToolException) as caught:
            query_arg(args)
        assert caught.value.code is ToolErrorCode.INVALID_ARGS


@pytest.mark.parametrize(
    "args",
    [{}, {"q": ""}, {"q": "x" * (QUERY_CAP + 1)}, {"q": "ok", "limit": 21}, {"q": "ok", "x": 1}],
)
async def test_the_shared_params_refuse_what_the_model_may_not_ask(args: dict[str, Any]) -> None:
    params = {
        "type": "object",
        "properties": {"q": QUERY_PARAM, "limit": LIMIT_PARAM},
        "required": ["q"],
        "additionalProperties": False,
    }
    registry = ToolRegistry()
    registry.register(bounded_read_tool("probe_rows", "Probe.", params, _yielding()))
    result = await registry.invoke(ToolCall(tool="probe_rows", args=args))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_ARGS
