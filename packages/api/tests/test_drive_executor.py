"""The ADR-041 drive loop (sol-drive.md §4): bind before any model sees a pixel,
then capture → propose ONE action → map → act, within N actions / T wall-clock
seconds. The helper's refusal ends the step; physical input pauses it."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from solus_api.agent.drive.actions import TOOLSET, ActRequest, Frame
from solus_api.agent.drive.executor import Budget, DriveExecutor, Progress
from solus_api.agent.drive.port import ActDone, DriveRefusal, Identity, Shot
from solus_api.orchestration.providers import ToolUse

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
FRAME = Frame(image_width=1280, image_height=800, points_width=640, points_height=400)
KICAD = frozenset({"org.kicad.kicad"})


def kicad(now: float = 100.0) -> Identity:
    return Identity(
        allowed=True,
        bundle_id="org.kicad.kicad",
        app_name="KiCad",
        window_id=7,
        now=now,
        accessibility=True,
        screen_recording=True,
    )


ELSEWHERE = Identity(
    allowed=False,
    bundle_id=None,
    app_name=None,
    window_id=None,
    now=1.0,
    accessibility=True,
    screen_recording=True,
)


@dataclass
class FakePort:
    identities: list[Identity] = field(default_factory=lambda: [kicad()])
    refuse_act: DriveRefusal | None = None
    #: The companion reports that the act saved a design file (ADR-041 M3).
    saves: bool = False
    #: Captures from this index on report a save (KiCad wrote after the act).
    saved_from_capture: int | None = None
    acts: list[dict[str, Any]] = field(default_factory=list)
    captures: int = 0
    finished: float = 200.0

    async def identify(self) -> Identity:
        return self.identities.pop(0) if len(self.identities) > 1 else self.identities[0]

    async def capture(self, bundle: str, window: int, *, max_edge: int) -> Shot:
        self.captures += 1
        late = self.saved_from_capture is not None and self.captures >= self.saved_from_capture
        return Shot(png=PNG, frame=FRAME, design_saved=late)

    async def act(self, bundle: str, window: int, request: ActRequest, **kw: Any) -> ActDone:
        self.acts.append({"bundle": bundle, "window": window, **request.args(), **kw})
        if self.refuse_act is not None:
            raise self.refuse_act
        self.finished += 1
        return ActDone(finished_at=self.finished, design_saved=self.saves)


@dataclass
class Round:
    tool_calls: tuple[ToolUse, ...] = ()
    provider_items: tuple[dict[str, Any], ...] = ()
    stop_reason: str | None = "tool_use"
    text: str = ""
    tokens_in: int = 1000


class FakeModel:
    def __init__(self, rounds: list[Round]) -> None:
        self.rounds = rounds
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self, *, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> Round:
        self.calls.append(
            {"system": system, "messages": [dict(m) for m in messages], "tools": list(tools)}
        )
        if not self.rounds:
            return Round(stop_reason="end_turn", text="Done.")
        return self.rounds.pop(0)


def click(at: tuple[int, int], uid: str = "t1") -> Round:
    use = ToolUse(id=uid, name="left_click", args={"coordinate": list(at)})
    return Round(tool_calls=(use,), provider_items=({"type": "tool_use", "id": uid},))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def no_sleep(_seconds: float) -> None:
    return None


def executor(
    port: FakePort, model: FakeModel, *, budget: Budget | None = None, clock: Clock | None = None
) -> tuple[DriveExecutor, list[Progress]]:
    seen: list[Progress] = []
    return (
        DriveExecutor(
            port,
            model,
            budget=budget or Budget(),
            clock=clock or Clock(),
            sleep=no_sleep,
            on_progress=seen.append,
        ),
        seen,
    )


async def test_binds_captures_and_runs_one_mapped_action_then_finishes() -> None:
    port, model = (
        FakePort(),
        FakeModel([click((200, 100)), Round(stop_reason="end_turn", text="Placed R1.")]),
    )
    ex, progress = executor(port, model)
    outcome = await ex.run("Place R1 above nSLEEP", KICAD)

    assert outcome.outcome == "done"
    assert outcome.actions == 1
    assert outcome.summary == "Placed R1."
    # One act, in points, chained to the helper clock and the captured size.
    assert port.acts == [
        {
            "bundle": "org.kicad.kicad",
            "window": 7,
            "verb": "click",
            "x": 100,
            "y": 50,
            "button": "left",
            "count": 1,
            "since": 100.0,
            "expect_width": 640,
            "expect_height": 400,
        }
    ]
    first = model.calls[0]
    assert first["tools"] == [TOOLSET]
    content = first["messages"][0]["content"]
    assert content[0]["type"] == "text" and "Place R1 above nSLEEP" in content[0]["text"]
    assert content[1]["type"] == "image"  # the instruction comes before the screenshot
    # The assistant's content replays verbatim, then the OK result.
    second = model.calls[1]["messages"]
    assert second[1] == {"role": "assistant", "content": [{"type": "tool_use", "id": "t1"}]}
    result = second[2]["content"][0]
    assert result["toolset_name"] == "computer"
    # The act's result carries a fresh capture: one round per action.
    assert [b["type"] for b in result["content"]] == ["text", "image"]
    assert port.captures == 3  # + the last look for a late save before "done"
    assert [p.verb for p in progress] == ["click"]
    assert outcome.code is None


async def test_the_next_act_is_chained_to_the_previous_finished_at() -> None:
    port, model = FakePort(), FakeModel([click((10, 10), "a"), click((20, 20), "b")])
    ex, _ = executor(port, model)
    await ex.run("x", KICAD)
    assert [a["since"] for a in port.acts] == [100.0, 201.0]


async def test_nothing_runs_until_an_allowlisted_app_is_in_front() -> None:
    port = FakePort(identities=[ELSEWHERE])
    model = FakeModel([click((1, 1))])
    clock = Clock()

    async def tick(seconds: float) -> None:
        clock.now += seconds

    ex = DriveExecutor(port, model, budget=Budget(), clock=clock, sleep=tick)
    outcome = await ex.run("x", KICAD)
    assert outcome.outcome == "not_in_front"
    assert model.calls == [] and port.captures == 0 and port.acts == []


async def test_it_waits_for_kicad_to_come_back_to_the_front() -> None:
    port = FakePort(identities=[ELSEWHERE, ELSEWHERE, kicad()])
    ex, _ = executor(port, FakeModel([]))
    assert (await ex.run("x", KICAD)).outcome == "done"


async def test_missing_os_permissions_end_the_step_before_capture() -> None:
    untrusted = Identity(**{**kicad().__dict__, "accessibility": False})
    port = FakePort(identities=[untrusted])
    ex, _ = executor(port, FakeModel([]))
    outcome = await ex.run("x", KICAD)
    assert (outcome.outcome, outcome.code) == ("refused", "not_trusted")
    assert port.captures == 0


async def test_physical_input_pauses_the_step() -> None:
    port = FakePort(refuse_act=DriveRefusal("user_active", "you moved the mouse"))
    model = FakeModel([click((1, 1)), click((2, 2))])
    ex, _ = executor(port, model)
    outcome = await ex.run("x", KICAD)
    assert (outcome.outcome, outcome.code) == ("paused", "user_active")
    assert len(port.acts) == 1 and len(model.calls) == 1
    assert outcome.failed_action == 1


async def test_any_helper_refusal_ends_the_step_with_its_code() -> None:
    port = FakePort(refuse_act=DriveRefusal("chord_denied", "that shortcut is not allowed"))
    model = FakeModel(
        [Round(tool_calls=(ToolUse(id="k", name="key", args={"text": "cmd+q"}),)), click((2, 2))]
    )
    ex, _ = executor(port, model)
    outcome = await ex.run("x", KICAD)
    assert (outcome.outcome, outcome.code) == ("refused", "chord_denied")
    assert len(model.calls) == 1


async def test_a_point_outside_the_window_ends_the_step_without_acting() -> None:
    port, model = FakePort(), FakeModel([click((5000, 5))])
    ex, _ = executor(port, model)
    outcome = await ex.run("x", KICAD)
    assert (outcome.outcome, outcome.code) == ("refused", "out_of_bounds")
    assert port.acts == []
    assert outcome.failed_action is None


async def test_an_unsupported_proposal_is_answered_and_costs_an_action() -> None:
    zoom = Round(tool_calls=(ToolUse(id="z", name="zoom", args={"region": [0, 0, 9, 9]}),))
    port, model = FakePort(), FakeModel([zoom])
    ex, _ = executor(port, model)
    outcome = await ex.run("x", KICAD)
    assert outcome.outcome == "done" and outcome.actions == 1
    answer = model.calls[1]["messages"][-1]["content"][0]
    assert answer["is_error"] is True and answer["toolset_name"] == "computer"


async def test_a_screenshot_proposal_recaptures_without_spending_an_action() -> None:
    shot = Round(tool_calls=(ToolUse(id="s", name="screenshot", args={}),))
    port, model = FakePort(), FakeModel([shot])
    ex, _ = executor(port, model)
    outcome = await ex.run("x", KICAD)
    assert outcome.actions == 0 and port.captures == 2  # the intro + the explicit one
    assert model.calls[1]["messages"][-1]["content"][0]["content"][0]["type"] == "image"


async def test_the_action_budget_is_never_exceeded() -> None:
    port = FakePort()
    model = FakeModel([click((i, i), f"t{i}") for i in range(10)])
    ex, _ = executor(port, model, budget=Budget(max_actions=3, max_seconds=120))
    outcome = await ex.run("x", KICAD)
    assert (outcome.outcome, outcome.actions) == ("budget", 3)
    assert len(port.acts) == 3


async def test_the_wall_clock_budget_counts_model_time() -> None:
    clock = Clock()
    port = FakePort()

    class SlowModel(FakeModel):
        async def __call__(self, **kw: Any) -> Round:
            clock.now += 50
            return await super().__call__(**kw)

    model = SlowModel([click((1, 1), "a"), click((2, 2), "b"), click((3, 3), "c")])
    ex, _ = executor(port, model, budget=Budget(max_actions=15, max_seconds=120), clock=clock)
    outcome = await ex.run("x", KICAD)
    assert outcome.outcome == "budget"
    assert len(port.acts) == 2  # the third proposal arrives after 150 s and never runs


async def test_screenshot_loops_are_bounded_by_rounds() -> None:
    shots = [
        Round(tool_calls=(ToolUse(id=f"s{i}", name="screenshot", args={}),)) for i in range(99)
    ]
    port, model = FakePort(), FakeModel(shots)
    ex, _ = executor(port, model, budget=Budget(max_actions=2, max_seconds=120))
    outcome = await ex.run("x", KICAD)
    assert outcome.outcome == "budget"
    assert len(model.calls) == Budget(max_actions=2).max_rounds


async def test_a_model_refusal_ends_the_step() -> None:
    port, model = FakePort(), FakeModel([Round(stop_reason="refusal")])
    ex, _ = executor(port, model)
    outcome = await ex.run("x", KICAD)
    assert outcome.outcome == "declined" and port.acts == []


async def test_extra_calls_in_one_round_are_answered_as_not_executed() -> None:
    both = Round(
        tool_calls=(
            ToolUse(id="a", name="left_click", args={"coordinate": [1, 1]}),
            ToolUse(id="b", name="left_click", args={"coordinate": [2, 2]}),
        )
    )
    port, model = FakePort(), FakeModel([both])
    ex, _ = executor(port, model)
    await ex.run("x", KICAD)
    assert len(port.acts) == 1
    results = model.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]
    assert results[1]["is_error"] is True


async def test_progress_never_carries_typed_text() -> None:
    typing = Round(tool_calls=(ToolUse(id="t", name="type", args={"text": "hunter2"}),))
    port, model = FakePort(), FakeModel([typing])
    ex, progress = executor(port, model)
    await ex.run("x", KICAD)
    assert "hunter2" not in repr(progress)
    assert progress[0].verb == "type" and progress[0].action == 1


@pytest.mark.parametrize("code", ["helper_timeout", "bridge", "agent_unavailable"])
async def test_helper_failures_end_the_step_as_errors(code: str) -> None:
    port = FakePort(refuse_act=DriveRefusal(code, "boom"))
    ex, _ = executor(port, FakeModel([click((1, 1))]))
    outcome = await ex.run("x", KICAD)
    assert (outcome.outcome, outcome.code) == ("error", code)


@pytest.mark.parametrize(
    "reason", ["max_tokens", "pause_turn", None, "model_context_window_exceeded"]
)
async def test_an_incomplete_reply_is_never_reported_as_done(reason: str | None) -> None:
    port, model = FakePort(), FakeModel([Round(stop_reason=reason, text="Placed R")])
    ex, _ = executor(port, model)
    outcome = await ex.run("x", KICAD)
    assert (outcome.outcome, outcome.code) == ("error", "model_incomplete")


async def test_a_model_round_is_cut_at_the_time_left() -> None:
    import asyncio

    port = FakePort()

    class StalledModel(FakeModel):
        async def __call__(self, **kw: Any) -> Round:
            await asyncio.sleep(30)
            return Round()

    ex = DriveExecutor(port, StalledModel([]), budget=Budget(max_seconds=0.2))
    outcome = await asyncio.wait_for(ex.run("x", KICAD), timeout=5)
    assert (outcome.outcome, outcome.code) == ("budget", "time")


async def test_a_stalled_helper_action_ends_as_a_timeout_naming_the_action() -> None:
    import asyncio

    class StalledPort(FakePort):
        async def act(self, *a: Any, **kw: Any) -> ActDone:
            await asyncio.sleep(30)
            raise AssertionError

    ex = DriveExecutor(
        StalledPort(), FakeModel([click((1, 1))]), budget=Budget(act_timeout_seconds=0.1)
    )
    outcome = await asyncio.wait_for(ex.run("x", KICAD), timeout=5)
    assert (outcome.outcome, outcome.code, outcome.failed_action) == ("error", "helper_timeout", 1)


async def test_the_input_token_cap_ends_the_step() -> None:
    port = FakePort()
    model = FakeModel([click((i, i), f"t{i}") for i in range(10)])
    ex, _ = executor(port, model, budget=Budget(max_input_tokens=2500))
    outcome = await ex.run("x", KICAD)
    assert (outcome.outcome, outcome.code) == ("budget", "tokens")
    assert len(model.calls) == 3  # 1000 tokens a round: the 4th never starts


async def test_unsupported_proposals_show_in_progress_too() -> None:
    zoom = Round(tool_calls=(ToolUse(id="z", name="zoom", args={}),))
    ex, progress = executor(FakePort(), FakeModel([zoom, click((1, 1))]))
    await ex.run("x", KICAD)
    assert [(p.action, p.verb) for p in progress] == [(1, "unsupported"), (2, "click")]


# --- ADR-041 amendment (M2/M3): project binding and saves ------------------------------


async def test_a_kicad_working_on_another_project_is_refused_before_any_capture() -> None:
    other = Identity(
        allowed=False,
        bundle_id=None,
        app_name=None,
        window_id=None,
        now=1.0,
        accessibility=True,
        screen_recording=True,
        outside_workspace=True,
    )
    port, model = FakePort(identities=[other]), FakeModel([click((10, 40))])
    result = await executor(port, model)[0].run("Place R1", KICAD)
    assert (result.outcome, result.code, result.actions) == ("refused", "outside_workspace", 0)
    assert port.captures == 0 and model.calls == []


async def test_an_action_that_saved_ends_the_step_as_saved_and_counts() -> None:
    port = FakePort(saves=True)
    model = FakeModel([click((10, 40)), click((20, 40), "t2")])
    result = await executor(port, model)[0].run("Place R1", KICAD)
    assert (result.outcome, result.code, result.actions) == ("saved", "design_saved", 1)
    assert result.failed_action is None  # the action ran; nothing was refused
    assert len(port.acts) == 1 and len(model.calls) == 1
    assert port.captures == 1  # no look after the save


async def test_a_save_seen_before_the_next_action_also_ends_as_saved() -> None:
    port = FakePort(refuse_act=DriveRefusal("design_saved", "a design file changed"))
    result = await executor(port, FakeModel([click((10, 40))]))[0].run("Place R1", KICAD)
    assert (result.outcome, result.code) == ("saved", "design_saved")


async def test_the_project_left_mid_step_is_refused() -> None:
    port = FakePort(refuse_act=DriveRefusal("outside_workspace", "another project"))
    result = await executor(port, FakeModel([click((10, 40))]))[0].run("Place R1", KICAD)
    assert (result.outcome, result.code) == ("refused", "outside_workspace")


async def test_a_save_that_lands_after_the_act_is_caught_by_the_next_capture() -> None:
    port = FakePort(saved_from_capture=2)  # 1: the first look; 2: after the act
    model = FakeModel([click((10, 40)), click((20, 40), "t2")])
    result = await executor(port, model)[0].run("Place R1", KICAD)
    assert (result.outcome, result.code, result.actions) == ("saved", "design_saved", 1)
    assert len(model.calls) == 1


async def test_a_save_noticed_only_at_the_end_is_not_reported_as_done() -> None:
    port = FakePort(saved_from_capture=3)  # after the act's look, before "done"
    model = FakeModel([click((10, 40))])
    result = await executor(port, model)[0].run("Place R1", KICAD)
    assert (result.outcome, result.code) == ("saved", "design_saved")
    assert port.captures == 3


async def test_a_step_with_no_actions_finishes_without_a_last_look() -> None:
    port, model = FakePort(), FakeModel([])
    result = await executor(port, model)[0].run("Place R1", KICAD)
    assert result.outcome == "done" and port.captures == 1
