"""SOL streaming event protocol (SOLUS-SYS-01).

Unit — no DB. Proves the `AgentEvent` envelope and its SSE encoding: the four
constructors carry the right payloads, a `tool_result` rides as the W0-04
`ToolResult` DATA (never a traceback), and `format_sse` emits a well-formed,
deterministic SSE frame the transport can write verbatim.
"""

import json
import string

from solus_api.agent.stream import (
    ARTIFACT_TOOLS,
    AgentEvent,
    AgentEventType,
    format_sse,
    persisted_answer,
)
from solus_api.agent.tools import ToolCall, ToolError, ToolErrorCode, ToolResult
from solus_api.agent.tools.untrusted import REDACTED


def test_token_event_carries_text() -> None:
    event = AgentEvent.token("hello")
    assert event.type is AgentEventType.TOKEN
    assert event.data == {"text": "hello"}


def test_tool_call_event_carries_call_id_tool_and_args() -> None:
    call = ToolCall(tool="get_entity", args={"entity_id": "x"}, call_id="c1")
    event = AgentEvent.tool_call(call)
    assert event.type is AgentEventType.TOOL_CALL
    assert event.data == {"call_id": "c1", "tool": "get_entity", "args": {"entity_id": "x"}}


def test_tool_call_event_redacts_a_secret_named_arg_and_keeps_a_plain_one() -> None:
    """The desktop draws these args (SOLUSDEV-321 P1-T6), so this is the gate it relies on: a
    model-proposed call streams BEFORE it is validated, and `redact_value` runs first (SOLX-04
    SEC-H3). The value is built here, so no credential-looking literal lives in this file."""
    secret = "t" * 24
    call = ToolCall(tool="get_entity", args={"api_token": secret, "entity_id": "x"}, call_id="c1")
    event = AgentEvent.tool_call(call)
    assert event.data["args"] == {"api_token": REDACTED, "entity_id": "x"}
    assert secret not in json.dumps(event.data)


def test_tool_result_event_is_the_w004_envelope() -> None:
    result = ToolResult.success("c1", {"name": "LM358"})
    event = AgentEvent.tool_result(result)
    assert event.type is AgentEventType.TOOL_RESULT
    assert event.data["ok"] is True
    assert event.data["call_id"] == "c1"
    assert event.data["value"] == {"name": "LM358"}


def test_tool_result_failure_carries_structured_error_not_a_traceback() -> None:
    result = ToolResult.failure("c1", ToolError(code=ToolErrorCode.NOT_FOUND, message="nope"))
    event = AgentEvent.tool_result(result)
    assert event.data["ok"] is False
    assert event.data["error"]["code"] == "not_found"
    assert event.data["value"] is None


def test_message_and_error_events() -> None:
    msg = AgentEvent.message("done reasoning")
    assert msg.data == {"role": "assistant", "content": "done reasoning", "citations": []}
    cited = AgentEvent.message("grounded", citations=("[datasheet:x.pdf]",))
    assert cited.data["citations"] == ["[datasheet:x.pdf]"]
    err = AgentEvent.error("internal", "the turn failed")
    assert err.type is AgentEventType.ERROR
    assert err.data == {"code": "internal", "message": "the turn failed"}


def test_format_sse_is_a_wellformed_frame() -> None:
    frame = format_sse(AgentEvent.token("hi"))
    assert frame.startswith("event: token\n")
    assert frame.endswith("\n\n")
    body = frame.split("data: ", 1)[1].rstrip("\n")
    assert json.loads(body) == {"text": "hi"}


def test_format_sse_is_deterministic() -> None:
    event = AgentEvent.done(conversation_id="a", turn_id="b")
    assert format_sse(event) == format_sse(event)
    # keys are sorted → stable wire regardless of insertion order
    assert '"conversation_id":"a"' in format_sse(event)


# ---------------------------------------------------------------- artifact (S5)


def test_artifact_event_carries_the_reference_never_bytes() -> None:
    ref = {
        "artifact_id": "019f9a00-0000-7000-8000-000000000001",
        "uri": "/api/v1/projects/p/artifacts/a/content",
        "media_type": "image/svg+xml",
        "title": "Arm wiring",
        "source_tool": "make_diagram",
        "summary": "wiring diagram: 4 nodes",
    }
    event = AgentEvent.artifact(ref)
    assert event.type is AgentEventType.ARTIFACT and event.type.value == "artifact"
    assert event.data == ref


def test_artifact_from_result_keys_on_the_allowlisted_tool_and_the_shape() -> None:
    value = {
        "artifact_id": "019f9a00-0000-7000-8000-000000000001",
        "uri": "/api/v1/projects/p/artifacts/a/content",
        "media_type": "image/svg+xml",
        "title": "Arm wiring",
        "summary": "s",
        "unknown_pins": ["x"],
        "bytes": "never-forwarded",
    }
    event = AgentEvent.artifact_from_result("make_diagram", ToolResult.success("c1", value))
    assert event is not None
    assert event.data == {
        "artifact_id": value["artifact_id"],
        "uri": value["uri"],
        "media_type": "image/svg+xml",
        "title": "Arm wiring",
        "source_tool": "make_diagram",
        "summary": "s",
    }
    # Not allowlisted → no event, even with the right shape.
    assert AgentEvent.artifact_from_result("get_entity", ToolResult.success("c1", value)) is None
    # Allowlisted but the shape is missing → no event (nothing to reference).
    assert (
        AgentEvent.artifact_from_result("make_diagram", ToolResult.success("c1", {"x": 1})) is None
    )
    failed = ToolResult.failure("c1", ToolError(code=ToolErrorCode.TOOL_ERROR, message="no"))
    assert AgentEvent.artifact_from_result("make_diagram", failed) is None


def test_a_non_mapping_tool_value_is_never_an_artifact() -> None:
    """Defence in depth. `ToolResult` already rejects a non-mapping `value` at
    construction, so this can only arise if a handler bypasses validation — and
    then the artifact event must be absent, not an AttributeError inside the SSE
    loop. Built with `model_construct` precisely because the validated path
    cannot express it."""
    from solus_api.agent.tools.shapes import ToolResult

    tool = next(iter(ARTIFACT_TOOLS))
    for bad in ("artifact_id", 7, ["artifact_id"], None):
        result = ToolResult.model_construct(call_id="call-1", ok=True, value=bad)
        assert AgentEvent.artifact_from_result(tool, result) is None
    # A mapping that simply lacks the required keys is equally not an artifact.
    partial = ToolResult.model_construct(call_id="call-1", ok=True, value={"uri": "/a"})
    assert AgentEvent.artifact_from_result(tool, partial) is None


def test_a_render_shown_on_request_is_a_card_and_an_unshown_one_is_not() -> None:
    """SOLUSDEV-321 P5: `render_view` with `show` returns the picture's reference, so the chat
    shows it as a card; without `show` there is no reference, and nothing is emitted."""
    shown = {
        "rendered": True,
        "view": "face:front",
        "read": "A front view of the arm.",
        "artifact_id": "019f9a00-0000-7000-8000-000000000002",
        "uri": "/api/v1/projects/p/artifacts/b/content",
        "media_type": "image/png",
        "title": "servo 2 (joint 2) (face:front)",
        "summary": "A labelled face:front render by the scene renderer.",
    }
    event = AgentEvent.artifact_from_result("render_view", ToolResult.success("c2", shown))
    assert event is not None
    assert (event.data["source_tool"], event.data["media_type"]) == ("render_view", "image/png")
    assert "read" not in event.data
    unshown = {k: v for k, v in shown.items() if k not in ("artifact_id", "uri", "media_type")}
    assert AgentEvent.artifact_from_result("render_view", ToolResult.success("c3", unshown)) is None


def test_answer_source_event_carries_who_answered_and_from_what() -> None:
    """SOLUSDEV-321: the first tier's envelope; its tuples ride as JSON lists."""
    event = AgentEvent.answer_source("graph", sources=("config",), citations=("[config:p1]",))
    assert event.type is AgentEventType.ANSWER_SOURCE
    assert event.data == {"source": "graph", "sources": ["config"], "citations": ["[config:p1]"]}
    assert format_sse(event).startswith("event: answer_source\ndata: ")
    assert AgentEvent.answer_source("graph").data == {
        "source": "graph",
        "sources": [],
        "citations": [],
    }


def test_budget_reached_event_names_the_ceiling_and_what_the_turn_used() -> None:
    """SOLUSDEV-321 P1-T3: counts only — which ceiling, what was used, the cap — on a frame the
    route streams and stores on the assistant turn."""
    event = AgentEvent.budget_reached("tool_calls", 24, 24)
    assert event.type is AgentEventType.BUDGET_REACHED
    assert event.data == {"limit": "tool_calls", "used": 24, "cap": 24}
    assert format_sse(event) == (
        'event: budget_reached\ndata: {"cap":24,"limit":"tool_calls","used":24}\n\n'
    )
    assert persisted_answer(event) == {
        "budget_reached": {"limit": "tool_calls", "used": 24, "cap": 24}
    }


def test_research_sources_event_names_what_the_turn_spent_and_the_sources_it_read() -> None:
    """SOLUSDEV-321 P1-T5: the desktop never receives a tool's value, so a turn's web research
    reaches the pills on a frame of its own — the (redacted) query, whether the cache answered, what
    this turn spent, and each source's url, title and whether its page was read."""
    sources = [
        {"url": "https://docs.example.com/ov9281", "title": "OV9281 datasheet", "fetched": True},
        {"url": "https://blog.example.com/ov9281", "title": "A blog", "fetched": False},
    ]
    event = AgentEvent.research_sources(
        call_id="c1", question="OV9281 supply", cached=False, searches=1, pages=2, sources=sources
    )
    assert event.type is AgentEventType.RESEARCH_SOURCES
    assert event.data == {
        "call_id": "c1",
        "question": "OV9281 supply",
        "cached": False,
        "searches": 1,
        "pages": 2,
        "sources": sources,
    }
    assert format_sse(event).startswith("event: research_sources\ndata: ")
    # The route stores the whole payload on the assistant turn, so a reload shows the same pills.
    assert persisted_answer(event) == {"research_sources": event.data}


def test_research_sources_frame_is_redacted_on_the_way_out() -> None:
    """Page titles are written by other people: a secret-shaped one is masked, like a tool value."""
    entropic = string.ascii_letters + string.digits  # 62 distinct characters, one token
    event = AgentEvent.research_sources(
        call_id="c1",
        question="OV9281",
        cached=True,
        searches=0,
        pages=0,
        sources=[{"url": "https://docs.example.com/a", "title": entropic, "fetched": False}],
    )
    (source,) = event.data["sources"]
    assert source["title"] == "[REDACTED]" and source["url"] == "https://docs.example.com/a"


def test_research_sources_frame_masks_a_secret_inside_a_sentence_and_in_a_url() -> None:
    """`redact_value` judges a string whole, so a credential inside a title or a question that
    has spaces in it went through: the prose fields are masked token by token first, and a URL
    that carries a provider-shaped key is masked whole."""
    key = "AKIA" + "AB12" * 4
    event = AgentEvent.research_sources(
        call_id="c1",
        question="why does password=hunter2 fail",
        cached=False,
        searches=1,
        pages=1,
        sources=[
            {
                "url": "https://docs.example.com/a",
                "title": "Set token=abc123 first",
                "fetched": True,
            },
            {"url": f"https://example.com/{key}", "title": "A page", "fetched": False},
        ],
    )
    assert event.data["question"] == "why does password=[REDACTED] fail"
    first, second = event.data["sources"]
    assert first == {
        "url": "https://docs.example.com/a",
        "title": "Set token=[REDACTED] first",
        "fetched": True,
    }
    assert second["url"] == "[REDACTED]" and second["title"] == "A page"


def test_research_sources_frame_cuts_after_it_masks_so_the_desktop_bounds_hold() -> None:
    """The loop cuts a title at 160 characters, which can leave it ending mid-mask
    (`…token=[RED`). Masking it again completes the mask (`token=[REDACTED]`, six characters
    longer), and the desktop validator drops the WHOLE payload for a title past 160 or a query
    past 400 (researchSources.ts) — so the frame cuts AFTER its own masking."""
    tail = "token=[RED"  # a value cut mid-mask, not a key
    title = "x" * (160 - len(tail)) + tail
    question = "x" * (400 - len(tail)) + tail
    assert (len(title), len(question)) == (160, 400)

    event = AgentEvent.research_sources(
        call_id="c1",
        question=question,
        cached=False,
        searches=1,
        pages=1,
        sources=[{"url": "https://docs.example.com/a", "title": title, "fetched": True}],
    )

    (source,) = event.data["sources"]
    assert len(source["title"]) <= 160 and len(event.data["question"]) <= 400
    assert source["title"].startswith("x" * 150 + "token=")  # masked, then cut: nothing else moved


def test_reasoning_event_carries_what_sol_weighed_masked_then_cut() -> None:
    """SOLUSDEV-321 P7: what SOL considered, what it ruled out and why, and what it proposes —
    model text, so every string is masked token by token and cut to its bound AFTER masking (the
    desktop drops a frame past its bounds); the frame persists nothing on the turn."""
    event = AgentEvent.reasoning(
        considered=["raise the lid", "password=hunter2 in the config"],
        ruled_out=[{"what": "a thinner wall", "why": "x" * 195 + " token=ab"}],
        proposing="Set WIDTH to 120 mm.",
    )
    assert event.type is AgentEventType.REASONING
    assert event.data == {
        "considered": ["raise the lid", "password=[REDACTED] in the config"],
        "ruled_out": [{"what": "a thinner wall", "why": ("x" * 195 + " token=[REDACTED]")[:200]}],
        "proposing": "Set WIDTH to 120 mm.",
    }
    assert persisted_answer(event) == {}
    assert format_sse(event).startswith("event: reasoning\ndata: ")


def test_persisted_answer_reads_only_the_answer_source_budget_and_research_frames() -> None:
    """The assistant-turn attrs come from three frames alone — `answer_source` (P1-T2),
    `budget_reached` (P1-T3) and `research_sources` (P1-T5): every other frame, the message that
    repeats the citations among them, persists nothing."""
    event = AgentEvent.answer_source("graph", sources=("telemetry",), citations=("[entity:x]",))
    assert persisted_answer(event) == {
        "answer_source": "graph",
        "sources": ["telemetry"],
        "citations": ["[entity:x]"],
    }
    others = (
        AgentEvent.token("hi"),
        AgentEvent.message("hi", citations=("[entity:x]",)),
        AgentEvent.error("internal", "boom"),
        AgentEvent.done(),
    )
    assert [persisted_answer(other) for other in others] == [{}, {}, {}, {}]
