"""`drive.step` (sol-drive.md §4): the ONE model-facing drive tool. Gated by the
ordinary confirmation card; its preview is built from the arguments alone (so
the card cannot go stale while the pill is in front); on approval it runs one
bounded loop, streams progress through the command-output channel, and records
ADR-011 events without typed text or pixels."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from solus_api.agent.command_output import STREAMING_TOOLS, current_output
from solus_api.agent.drive.executor import Budget, Progress, StepOutcome
from solus_api.agent.drive.tool import DRIVABLE_APPS, DriveStepTool, progress_line
from solus_api.agent.runtime import build_sol_registry
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.allowlist import load_allowlist, validate_inventory
from solus_api.bridge.frames import HelloData
from solus_api.bridge.registry import BridgeSession, InMemoryBridgeSessionRegistry
from solus_api.connectors.secrets import InMemorySecretStore
from sqlalchemy.ext.asyncio import async_sessionmaker

ARGS = {"app": "kicad", "intent": "Place a 10k resistor R1 above nSLEEP"}


def outcome(
    kind: str = "done", code: str | None = None, actions: int = 2, failed: int | None = None
) -> StepOutcome:
    return StepOutcome(
        outcome=kind,  # type: ignore[arg-type]
        code=code,
        actions=actions,
        seconds=12.0,
        summary="Placed R1.",
        app_name="KiCad",
        failed_action=failed,
    )


class Runner:
    def __init__(self, result: StepOutcome, progress: list[Progress] | None = None) -> None:
        self.result = result
        self.progress = progress or []
        self.calls: list[tuple[str, frozenset[str]]] = []

    async def __call__(
        self, intent: str, drivable: frozenset[str], on_progress: Any
    ) -> StepOutcome:
        self.calls.append((intent, drivable))
        for p in self.progress:
            on_progress(p)
        return self.result


class Events:
    def __init__(self) -> None:
        self.seen: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, event_type: str, payload: dict[str, Any]) -> None:
        self.seen.append((event_type, payload))


class Sink:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def append(self, stream: str, text: str) -> None:
        self.lines.append(text)

    def truncate(self) -> None:
        return None


def tool(runner: Runner, events: Events | None = None) -> DriveStepTool:
    return DriveStepTool(run_step=runner, record=events or Events(), budget=Budget())


def test_the_descriptor_is_gated_and_offers_only_allowlisted_apps() -> None:
    d = tool(Runner(outcome())).descriptor
    assert d.name == "drive.step"
    assert d.requires_confirmation is True
    assert d.consent_summary and "mouse" in d.consent_summary
    assert d.params["properties"]["app"]["enum"] == ["kicad"]
    assert d.params["additionalProperties"] is False
    assert d.timeout_seconds is not None and d.timeout_seconds > Budget().max_seconds
    assert DRIVABLE_APPS["kicad"] == frozenset({"org.kicad.kicad", "org.kicad.eeschema"})


def test_drive_step_streams_its_progress() -> None:
    assert "drive.step" in STREAMING_TOOLS


async def test_the_preview_is_built_from_the_arguments_alone() -> None:
    t = tool(Runner(outcome()))
    rows = await t.preview(ARGS)
    assert rows == await t.preview(dict(ARGS))  # deterministic: never stale on its own
    by_label = {r["label"]: r["after"] for r in rows}
    assert by_label["App"] == "KiCad"
    assert by_label["What SOL will do"] == ARGS["intent"]
    assert by_label["Budget"] == "up to 15 actions · 2 min"
    assert "mouse" in by_label["Heads up"]
    assert all(r["before"] is None for r in rows)


@pytest.mark.parametrize(
    "args",
    [
        {"app": "fusion", "intent": "x"},
        {"app": "kicad", "intent": ""},
        {"app": "kicad", "intent": "x" * 301},
        {"app": "kicad", "intent": "line one\nline two"},
        {"app": "kicad", "intent": "x", "budget": 99},
        {"app": "kicad", "intent": "Type password=hunter2hunter2 into the field"},
    ],
)
async def test_bad_arguments_never_run(args: dict[str, Any]) -> None:
    runner = Runner(outcome())
    with pytest.raises(ToolException):
        await tool(runner).invoke(args)
    assert runner.calls == []


async def test_a_finished_step_reports_what_happened() -> None:
    runner = Runner(outcome())
    value = await tool(runner).invoke(ARGS)
    assert runner.calls == [(ARGS["intent"], DRIVABLE_APPS["kicad"])]
    assert value == {
        "outcome": "done",
        "actions": 2,
        "seconds": 12.0,
        "summary": "Placed R1.",
    }


@pytest.mark.parametrize(
    ("kind", "code", "words"),
    [
        ("paused", "user_active", "you took over"),
        ("budget", "actions", "budget"),
        ("refused", "chord_denied", "chord_denied"),
        ("not_in_front", None, "in front"),
        ("declined", "model_refusal", "declined"),
        ("error", "no_credits", "out of credits"),
        ("error", "rate_limited", "wait a minute"),
        ("budget", "tokens", "model budget"),
        ("error", "helper_timeout", "helper_timeout"),
        ("saved", "design_saved", "saved the design"),
        ("refused", "outside_workspace", "stopped — the KiCad in front has a project outside"),
        ("refused", "not_bound", "not_bound"),
        ("refused", "caller_untrusted", "did not recognise the Solus companion; reinstall Solus"),
    ],
)
async def test_an_unfinished_step_fails_so_the_plan_stops(kind: str, code: str, words: str) -> None:
    with pytest.raises(ToolException) as caught:
        await tool(Runner(outcome(kind, code))).invoke(ARGS)
    assert words in caught.value.message
    assert "2 actions" in caught.value.message


async def test_progress_lines_go_to_the_command_output_channel() -> None:
    progress = [Progress(action=1, max_actions=15, verb="type", elapsed=3.0)]
    sink = Sink()
    token = current_output.set(sink)
    try:
        await tool(Runner(outcome(), progress)).invoke(ARGS)
    finally:
        current_output.reset(token)
    assert sink.lines == ["action 1/15 · type · 3.0 s\n"]


#: The pill parses these lines (sol-drive.md §4): changing them is desktop-visible.
PILL_PATTERN = re.compile(r"^action (\d+)/(\d+) · ([a-z]+) · (\d+\.\d) s$")


@pytest.mark.parametrize(
    ("progress", "groups"),
    [
        (
            Progress(action=3, max_actions=15, verb="click", elapsed=12.44),
            ("3", "15", "click", "12.4"),
        ),
        (
            Progress(action=1, max_actions=1, verb="unsupported", elapsed=0.0),
            ("1", "1", "unsupported", "0.0"),
        ),
        (
            Progress(action=15, max_actions=15, verb="key", elapsed=119.96),
            ("15", "15", "key", "120.0"),
        ),
    ],
)
def test_the_progress_line_format_is_pinned(progress: Progress, groups: tuple[str, ...]) -> None:
    line = progress_line(progress)
    assert line.endswith("\n") and line.count("\n") == 1
    match = PILL_PATTERN.match(line.removesuffix("\n"))
    assert match is not None and match.groups() == groups


async def test_events_record_verbs_and_outcomes_never_text() -> None:
    progress = [
        Progress(action=1, max_actions=15, verb="click", elapsed=1.0),
        Progress(action=2, max_actions=15, verb="key", elapsed=2.0),
    ]
    events = Events()
    with pytest.raises(ToolException):
        await tool(Runner(outcome("refused", "chord_denied", failed=2), progress), events).invoke(
            ARGS
        )
    kinds = [kind for kind, _ in events.seen]
    assert kinds == [
        "drive.session_started",
        "drive.action",
        "drive.action",
        "drive.aborted",
        "drive.session_ended",
    ]
    actions = [payload for kind, payload in events.seen if kind == "drive.action"]
    assert actions == [
        {"index": 1, "verb": "click", "result": "ok"},
        {"index": 2, "verb": "key", "result": "chord_denied"},
    ]
    ended = events.seen[-1][1]
    assert ended == {
        "app": "kicad",
        "actions": 2,
        "seconds": 12.0,
        "outcome": "refused",
        "code": "chord_denied",
    }
    assert ARGS["intent"] not in repr(events.seen)


async def test_a_failing_event_store_never_fails_the_step() -> None:
    async def broken(event_type: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("db down")

    value = await DriveStepTool(run_step=Runner(outcome()), record=broken, budget=Budget()).invoke(
        ARGS
    )
    assert value["outcome"] == "done"


# --- registration ---------------------------------------------------------------------


def _session(scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID], tools: list[str]) -> BridgeSession:
    root = Path(__file__).resolve().parents[3] / "integrations" / "mcp"
    hello = HelloData.model_validate(
        {
            "protocol_version": 1,
            "companion_version": "0.1.0",
            "companion_instance_id": "i-1",
            "servers": [
                {
                    "server": "drive",
                    "tools": [
                        {"name": n, "description": "d", "input_schema": {"type": "object"}}
                        for n in tools
                    ],
                }
            ],
        }
    )

    async def _noop(*_a: Any) -> None:
        return None

    return BridgeSession(
        session_id=uuid.uuid4().hex,
        user_id=scope[0],
        team_id=scope[1],
        project_id=scope[2],
        companion_instance_id="i-1",
        companion_version="0.1.0",
        protocol_version=1,
        connected_at=datetime.now(UTC),
        token_exp=datetime.now(UTC),
        inventory=validate_inventory(hello, load_allowlist(root)),
        send=_noop,
        close=_noop,
        max_inflight=8,
    )


def _registry_names(tools: list[str], *, keyed: bool = True) -> set[str]:
    scope = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    sessions = InMemoryBridgeSessionRegistry()
    sessions.bind(_session(scope, tools))
    registry = build_sol_registry(
        async_sessionmaker(),
        scope[2],
        bridge=sessions,
        user_id=scope[0],
        team_id=scope[1],
        secret_store=InMemorySecretStore() if keyed else None,
    )
    return {d.name for d in registry.list() if d.name.startswith("drive.")}


def test_drive_step_appears_only_with_the_full_internal_drive_inventory() -> None:
    assert _registry_names(["identify", "capture", "act"]) == {"drive.step"}
    assert _registry_names(["identify", "capture"]) == set()
    assert _registry_names([]) == set()
    assert _registry_names(["identify", "capture", "act"], keyed=False) == set()


def test_drive_step_is_never_auto_approved() -> None:
    from solus_api.agent.command_auto import auto_judge

    assert auto_judge("drive.step", ARGS) is False


async def test_a_second_step_on_the_same_machine_is_refused_while_one_runs() -> None:
    import asyncio

    from solus_api.agent.drive.wiring import drive_lease

    key = uuid.uuid4()
    gate = asyncio.Event()

    class Slow(Runner):
        async def __call__(self, *a: Any) -> StepOutcome:
            await gate.wait()
            return self.result

    first = DriveStepTool(
        run_step=Slow(outcome()), record=Events(), budget=Budget(), lease=lambda: drive_lease(key)
    )
    second_runner = Runner(outcome())
    second = DriveStepTool(
        run_step=second_runner, record=Events(), budget=Budget(), lease=lambda: drive_lease(key)
    )
    running = asyncio.create_task(first.invoke(ARGS))
    await asyncio.sleep(0)
    with pytest.raises(ToolException, match="already running"):
        await second.invoke(ARGS)
    assert second_runner.calls == []
    gate.set()
    assert (await running)["outcome"] == "done"
    # Released: the next step may run.
    assert (await second.invoke(ARGS))["outcome"] == "done"


async def test_a_cancelled_step_still_ends_its_audit_trail() -> None:
    import asyncio

    class Hang(Runner):
        async def __call__(self, *a: Any) -> StepOutcome:
            await asyncio.sleep(30)
            raise AssertionError

    events = Events()
    task = asyncio.create_task(tool(Hang(outcome()), events).invoke(ARGS))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [kind for kind, _ in events.seen] == [
        "drive.session_started",
        "drive.aborted",
        "drive.session_ended",
    ]
    assert events.seen[-1][1]["outcome"] == "cancelled"


async def test_the_summary_is_redacted() -> None:
    leaky = StepOutcome(
        outcome="done",
        code=None,
        actions=1,
        seconds=1.0,
        summary="Typed token=abcdef0123456789abcdef",
    )
    value = await tool(Runner(leaky)).invoke(ARGS)
    assert "abcdef0123456789abcdef" not in value["summary"]


def test_the_description_states_the_configured_budget() -> None:
    d = DriveStepTool(
        run_step=Runner(outcome()), record=Events(), budget=Budget(max_actions=8, max_seconds=90)
    ).descriptor
    assert "up to 8 actions · 1.5 min" in d.description
