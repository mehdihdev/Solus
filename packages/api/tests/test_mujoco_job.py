"""SOLUSDEV-321 P4-T3 — rung 3, mechanics in motion: the trajectory job (R87, Q6, R106, R107).

The job compiles only the engine's own XML. A URDF root is refused before livebench's guard runs,
and the guard runs on every text compiled. The parsed tree is then walked: no element, attribute
or value may name a file, a directory or a path, whatever the substring guard saw, and nothing
may multiply the model or size its memory. The engine runs only in a child of its own, under CPU
and memory limits and a hard kill. There it compiles through its virtual file system, under a
directory that does not exist, and refuses a model past any cap before any `MjData` is made. The
job follows a generic joint-target routine with forward dynamics, and derives the current from the
force and the torque constant. The physics is checked by hand: a 1 kg mass 0.5 m out on a hinge,
held level by a position servo, needs m g L = 4.905 N m.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any, Final
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError
from solus_api.graph import kinds
from solus_api.graph.live import LiveHub
from solus_api.models import GraphEntity
from solus_api.simulation.providers import mujoco_job
from solus_api.simulation.providers.mujoco_job import (
    JointTrajectory,
    RigidBodyTrajectory,
    TrajectoryOutcome,
    run_mujoco_sim,
)
from solus_api.simulation.sim_capability import (
    SimProvider,
    SimQuestion,
    SimResult,
    SimulationFailedError,
    SimulationRefusedError,
)
from solus_api.simulation.sim_facts import SimJobRequest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from test_sim_facts import _seed

ARM: Final = """<mujoco model="arm">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <worldbody>
    <body name="link" pos="0 0 1">
      <joint name="shoulder" type="hinge" axis="0 1 0"/>
      <geom type="sphere" size="0.01" pos="0.5 0 0" mass="1"/>
    </body>
  </worldbody>
  <actuator>
    <position name="servo" joint="shoulder" kp="2000" kv="60"/>
  </actuator>
</mujoco>"""
SERVO: Final = '<position name="servo" joint="shoulder" kp="2000" kv="60"/>'
SPHERE: Final = '<geom type="sphere" size="0.01" pos="0.5 0 0" mass="1"/>'
ROUTINE: Final = {
    "joints": ["shoulder"],
    "points": [{"t": 0.0, "positions": [0.0]}, {"t": 2.0, "positions": [0.0]}],
}
HELD: Final = JointTrajectory.model_validate(ROUTINE)
FACTS: Final = {"mjcf": ARM, "trajectory": ROUTINE, "torque_constants": {"shoulder": 0.5}}
#: An outcome as the child would hand it back for the arm: two samples, one hinge.
OUTCOME: Final = {
    "bodies": 2,
    "joints": 1,
    "actuators": 1,
    "timestep_s": 0.002,
    "hinges": [True],
    "times": [0.002, 2.0],
    "positions": [[0.0], [0.0]],
    "forces": [[1.0], [4.9]],
    "peaks": [5.4],
    "steps": 1000,
}
needs_engine = pytest.mark.skipif(
    not mujoco_job.engine_installed(), reason="the physics engine is not installed here"
)


class _Child:
    """The child's stand-in: it records every text it is handed and runs none of them."""

    def __init__(self) -> None:
        self.handed: list[str] = []

    def __call__(self, xml: str, routine: JointTrajectory) -> TrajectoryOutcome:
        self.handed.append(xml)
        raise SimulationRefusedError("the stand-in runs nothing")


@pytest.fixture
def child(monkeypatch: pytest.MonkeyPatch) -> _Child:
    """The child's stand-in, on a machine that has the engine."""
    stand_in = _Child()
    monkeypatch.setattr(mujoco_job, "engine_installed", lambda: True)
    monkeypatch.setattr(mujoco_job, "simulate_in_child", stand_in)
    return stand_in


class _Guard:
    """livebench's local module, as far as the job uses it: a guard that records what it saw."""

    def __init__(self) -> None:
        self.guarded: list[str] = []

    def _reject_file_referencing_mjcf(self, xml: str) -> None:
        self.guarded.append(xml)


def _engine() -> ModuleType:
    engine = mujoco_job.physics_engine()
    assert engine is not None
    return engine


class _Spy:
    """The real engine, counting the `MjData` a run makes and the steps it takes. Each step can
    pause, as on a slow machine."""

    def __init__(self, pause_s: float = 0.0) -> None:
        self.engine = _engine()
        self.pause_s = pause_s
        self.made = self.stepped = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.engine, name)

    def MjData(self, model: Any) -> Any:  # noqa: N802 — the engine's own name
        self.made += 1
        return self.engine.MjData(model)

    def mj_step(self, model: Any, data: Any) -> None:
        self.stepped += 1
        self.engine.mj_step(model, data)
        time.sleep(self.pause_s)


def _run(facts: dict[str, Any] = FACTS) -> SimResult:
    provider = RigidBodyTrajectory()
    return provider.run(provider.inputs_for(facts))


def _derived(result: SimResult, name: str) -> Any:
    entry = result.provenance.inputs[name]
    assert entry.source == "derived"
    return entry.value


def _question(quantity: str, facts: dict[str, Any]) -> SimQuestion:
    return SimQuestion(subject_id=uuid.uuid4(), quantity=quantity, facts=facts)


@pytest.mark.parametrize(
    "mjcf",
    [
        pytest.param('<mujoco><asset><mesh name="m" file="arm.stl"/></asset></mujoco>', id="mesh"),
        pytest.param('<mujoco><compiler meshdir="/etc"/></mujoco>', id="meshdir"),
        pytest.param('<mujoco><include file="/etc/passwd"/></mujoco>', id="include"),
        pytest.param('<mujoco><asset><texture name="t" file="t.png"/></asset></mujoco>', id="tex"),
        pytest.param('<mujoco><compiler assetdir="/"/></mujoco>', id="assetdir"),
    ],
)
async def test_file_referencing_mjcf_rejected(mjcf: str, child: _Child) -> None:
    # livebench's own guard refuses it
    with pytest.raises(SimulationRefusedError, match="may not reference files"):
        _run({**FACTS, "mjcf": mjcf})
    # the job refuses it too, and says why
    request = {"project_id": str(uuid.uuid4()), "subject_id": str(uuid.uuid4())}
    status = await run_mujoco_sim({}, {**request, "facts": {**FACTS, "mjcf": mjcf}})
    assert status["status"] == "refused"
    assert "may not reference files" in str(status["reason"])
    assert child.handed == []


@pytest.mark.parametrize(
    ("mjcf", "why"),
    [
        pytest.param(
            '<mujoco><asset><texture name="t" type="cube" fileup="up.png"/></asset></mujoco>',
            "no file or directory (`fileup`)",
            id="a-file-attribute-the-regex-misses",
        ),
        pytest.param(
            '<mujoco><compiler fontdir="fonts"/></mujoco>',
            "no file or directory (`fontdir`)",
            id="a-dir-attribute-the-regex-misses",
        ),
        pytest.param(
            '<mujoco><worldbody><body name="&#47;etc"/></worldbody></mujoco>',
            "`name` holds a path",
            id="a-path-behind-a-character-reference",
        ),
        pytest.param(
            '<mujoco><worldbody><body name="up..there"/></worldbody></mujoco>',
            "`name` holds a path",
            id="a-parent-directory",
        ),
        pytest.param(
            '<mujoco><worldbody><body name="c:x"/></worldbody></mujoco>',
            "`name` holds a path",
            id="a-drive-or-a-scheme",
        ),
        pytest.param(
            '<mujoco><worldbody><body name="a\\b"/></worldbody></mujoco>',
            "`name` holds a path",
            id="a-backslash",
        ),
        pytest.param(
            '<mujoco><asset><model name="m"/></asset></mujoco>', "no `model` element", id="model"
        ),
        pytest.param(
            '<mujoco xmlns:x="u"><asset><mesh name="m" x:file="arm.stl"/></asset></mujoco>',
            "no XML namespace",
            id="a-namespaced-file-attribute",
        ),
        pytest.param(
            '<mujoco><asset><mesh name="m"\n  file\n  =\n  "/etc/passwd"/></asset></mujoco>',
            "no file or directory (`file`)",
            id="an-absolute-file-split-across-lines",
        ),
        pytest.param(
            '<mujoco><asset><mesh name="m" &#102;ile="arm.stl"/></asset></mujoco>',
            "not well-formed",
            id="a-character-reference-in-a-name",
        ),
    ],
)
def test_a_guard_bypass_is_refused_by_the_walk_over_the_parsed_tree(
    mjcf: str, why: str, child: _Child, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With livebench's substring guard refusing nothing, the walk alone refuses every one."""
    monkeypatch.setattr(mujoco_job, "load_local", _Guard)
    with pytest.raises(SimulationRefusedError) as refused:
        _run({**FACTS, "mjcf": mjcf})
    assert why in str(refused.value)
    assert child.handed == []


@needs_engine
def test_the_walk_refuses_every_attribute_the_engine_reads_a_file_through() -> None:
    """The engine's own schema names every attribute it knows. Those that name a file all start
    `file` or end `dir`; an engine that adds another fails here, for a person to look at."""
    words = set(re.findall(r"[a-z_]+", _engine().mj_printSchema(False, False)))
    fileish = {word for word in words if "file" in word or "path" in word or word.endswith("dir")}
    assert fileish == {
        *("file", "fileback", "filedown", "filefront", "fileleft", "fileright", "fileup"),
        *("assetdir", "meshdir", "texturedir"),
        *("dir", "strippath"),  # a light's direction and a flag: neither names a file
    }
    for name in sorted(fileish - {"dir", "strippath"}):
        assert mujoco_job.element_error(ElementTree.Element("x", {name: "a"})) is not None
    assert mujoco_job.element_error(ElementTree.Element("x", {"dir": "0 0 -1"})) is None


@pytest.mark.parametrize(
    ("mjcf", "tag"),
    [
        pytest.param(
            ARM.replace(
                SPHERE,
                SPHERE
                + '<replicate count="100000" offset="0 0 0.1"><geom size="0.1"/></replicate>',
            ),
            "replicate",
            id="replicate-a-hundred-thousand-times",
        ),
        pytest.param(
            ARM.replace(
                "<worldbody>",
                '<worldbody><composite type="particle" count="100 100 100" spacing="0.01">'
                '<geom size="0.01"/></composite>',
            ),
            "composite",
            id="a-million-particle-composite",
        ),
        pytest.param(
            ARM.replace(
                "<worldbody>",
                '<worldbody><flexcomp name="f" type="grid" count="1000 1000 1" '
                'spacing="0.01 0.01 0.01" dim="2"/>',
            ),
            "flexcomp",
            id="a-million-vertex-flexcomp",
        ),
        pytest.param(
            ARM.replace("<worldbody>", '<size memory="10G"/><worldbody>'),
            "size",
            id="a-ten-gigabyte-arena",
        ),
    ],
)
def test_a_model_that_multiplies_or_sizes_itself_is_refused_before_any_mjdata(
    mjcf: str, tag: str, child: _Child
) -> None:
    """Each states, in a few bytes, a model or an arena far past its text (R106). The walk refuses
    it, so no child starts, nothing compiles and no `MjData` is made."""
    with pytest.raises(SimulationRefusedError, match=f"no `{tag}` element"):
        _run({**FACTS, "mjcf": mjcf})
    assert child.handed == []


@pytest.mark.parametrize(
    ("text", "why"),
    [
        pytest.param(
            '<robot name="r"><link name="a"><visual><geometry><mesh filename="/etc/passwd"/>'
            "</geometry></visual></link></robot>",
            "root element",
            id="a-urdf-root",
        ),
        pytest.param('<!DOCTYPE m [<!ENTITY a "b">]><mujoco/>', "no DTD", id="a-dtd"),
        pytest.param("<mujoco><!-- a comment --></mujoco>", "no DTD", id="a-comment"),
        pytest.param("<mujoco><worldbody>", "well-formed", id="broken-xml"),
    ],
)
def test_a_urdf_or_a_dtd_is_refused_before_the_guard_ever_runs(
    text: str, why: str, child: _Child, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = _Guard()
    monkeypatch.setattr(mujoco_job, "load_local", lambda: guard)
    with pytest.raises(SimulationRefusedError, match=why):
        _run({**FACTS, "mjcf": text})
    assert guard.guarded == [] and child.handed == []


def test_the_guard_runs_on_every_text_and_only_a_checked_one_reaches_the_child(
    child: _Child, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = _Guard()
    monkeypatch.setattr(mujoco_job, "load_local", lambda: guard)
    plugged = '<mujoco><extension><plugin plugin="a.b"/></extension></mujoco>'
    with pytest.raises(SimulationRefusedError, match="no `extension` element"):
        _run({**FACTS, "mjcf": plugged})
    with pytest.raises(SimulationRefusedError, match="the stand-in runs nothing"):
        _run()
    # the guard saw both texts before anything else could; only the arm reached the child
    assert guard.guarded == [plugged, ARM]
    assert child.handed == [ARM]


@needs_engine
def test_the_engine_reads_no_relative_file_even_past_every_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A text that names a file in the working directory, handed to the compile directly as if
    every guard had missed it. A compile from a string would open it (the engine's message would
    be the decoder's); through the VFS it resolves under a directory that does not exist, and is
    never opened. An absolute path the engine still opens from the disk, which is why the walk
    refuses every one before the engine sees the text (the bypass test above)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "beside.stl").write_text("solid beside\nendsolid beside\n")
    reach = (
        '<mujoco><asset><mesh name="m" file="beside.stl"/></asset>'
        '<worldbody><geom type="mesh" mesh="m"/></worldbody></mujoco>'
    )
    with (
        caplog.at_level(logging.WARNING, logger=mujoco_job.__name__),
        pytest.raises(SimulationRefusedError, match="does not compile"),
    ):
        mujoco_job.compiled(_engine(), reach)
    assert "Error opening file" in caplog.text
    assert "decoder" not in caplog.text


@needs_engine
@pytest.mark.parametrize("count", sorted(mujoco_job.MODEL_CAPS))
def test_a_model_past_any_cap_is_refused_before_any_mjdata(
    count: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each cap, set just below the arm's own count, refuses the compiled arm before the run
    makes any `MjData` (R106)."""
    spy = _Spy()
    below = int(getattr(mujoco_job.compiled(spy.engine, ARM), count)) - 1
    noun = mujoco_job.MODEL_CAPS[count][1]
    monkeypatch.setattr(mujoco_job, "MODEL_CAPS", {**mujoco_job.MODEL_CAPS, count: (below, noun)})
    with pytest.raises(SimulationRefusedError, match=f"{noun}; a run takes at most {below:,}$"):
        mujoco_job.simulate(spy, ARM, HELD)
    assert spy.made == 0


@needs_engine
def test_derived_current_marked_derived_or_skips_without_mujoco() -> None:
    result = _run()
    forces = _derived(result, "actuator_force")["shoulder"]
    currents = _derived(result, "expected_current_a")["shoulder"]
    # at rest after the catch, the servo holds m g L = 1 kg * 9.81 m/s^2 * 0.5 m
    assert abs(forces[-1]) == pytest.approx(4.905, rel=1e-3)
    # the expected current is the force over the torque constant, sample for sample
    for force, current in zip(forces, currents, strict=True):
        assert current == pytest.approx(abs(force) / 0.5, rel=1e-5)
    torque = result.values["peak_joint_torque_nm"]
    current = result.values["peak_joint_current_a"]
    assert (torque.unit, current.unit) == ("N m", "A")
    assert torque.value >= abs(forces[-1])
    assert current.value == pytest.approx(torque.value / 0.5, rel=1e-12)
    assert "peak_joint_force_n" not in result.values  # the routine drives no slide joint
    # the expected trajectory: the arm sags a few milliradians and is held
    positions = _derived(result, "expected_trajectory")["positions"]["shoulder"]
    assert max(abs(q) for q in positions) < 0.01
    inputs = result.provenance.inputs
    assert inputs["trajectory"].source == inputs["torque_constants"].source == "known"
    assert _derived(result, "steps") == 1000
    assert inputs["mjcf"].value == {"bytes": len(ARM), "bodies": 2, "joints": 1, "actuators": 1}
    assert result.provenance.solver == "rigid_body_trajectory"
    assert any("torque constant" in line for line in result.provenance.leaves_out)


def test_the_result_is_built_from_what_the_child_hands_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the engine: the values and the provenance come from the child's outcome alone."""
    monkeypatch.setattr(mujoco_job, "engine_installed", lambda: True)
    handed = TrajectoryOutcome.model_validate(OUTCOME)
    monkeypatch.setattr(mujoco_job, "simulate_in_child", lambda xml, routine: handed)
    result = _run()
    assert result.values["peak_joint_torque_nm"].value == 5.4
    assert result.values["peak_joint_current_a"].value == pytest.approx(10.8)
    assert _derived(result, "expected_current_a") == {"shoulder": [2.0, 9.8]}
    assert _derived(result, "expected_trajectory") == {
        "t": [0.002, 2.0],
        "positions": {"shoulder": [0.0, 0.0]},
    }
    assert result.provenance.inputs["timestep_s"].value == 0.002
    assert result.provenance.inputs["mjcf"].value == {
        "bytes": len(ARM),
        "bodies": 2,
        "joints": 1,
        "actuators": 1,
    }


@needs_engine
@pytest.mark.parametrize(
    ("mjcf", "why"),
    [
        pytest.param(ARM.replace("shoulder", "elbow"), "no joint `shoulder`", id="no-such-joint"),
        pytest.param(ARM.replace(SERVO, ""), "no position actuator", id="no-actuator"),
        pytest.param(
            ARM.replace(SERVO, '<motor joint="shoulder" gear="10"/>'),
            "no position actuator",
            id="a-torque-motor",
        ),
        pytest.param(
            ARM.replace(SPHERE, '<geom type="mesh" mesh="ghost" mass="1"/>'),
            "does not compile",
            id="a-geom-naming-a-mesh-the-vfs-lacks",
        ),
    ],
)
def test_a_model_the_routine_cannot_drive_is_refused(mjcf: str, why: str) -> None:
    with pytest.raises(SimulationRefusedError, match=why):
        _run({**FACTS, "mjcf": mjcf})


@needs_engine
def test_the_engines_own_message_is_logged_and_never_returned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The child's compile fails; its message, which can echo the text, reaches the worker's log
    and never the reason the job returns."""
    bogus = ARM.replace("<worldbody>", "<worldbody><bogus/>")
    with (
        caplog.at_level(logging.WARNING, logger=mujoco_job.__name__),
        pytest.raises(SimulationRefusedError) as refused,
    ):
        _run({**FACTS, "mjcf": bogus})
    assert str(refused.value) == "the model does not compile"
    assert "bogus" in caplog.text


@needs_engine
def test_steps_and_wall_time_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mujoco_job, "MAX_STEPS", 100)
    with pytest.raises(SimulationRefusedError, match="needs 1,000 steps"):
        mujoco_job.simulate(_Spy(), ARM, HELD)
    monkeypatch.setattr(mujoco_job, "MAX_STEPS", 50_000)
    # the wall clock is read at every step: a slow machine stops within a few, not a thousand
    monkeypatch.setattr(mujoco_job, "MAX_WALL_SECONDS", 0.02)
    slow = _Spy(pause_s=0.01)
    with pytest.raises(SimulationFailedError, match="wall time"):
        mujoco_job.simulate(slow, ARM, HELD)
    assert slow.stepped <= 5


@needs_engine
@pytest.mark.skipif(sys.platform != "linux", reason="the address-space limit is Linux's")
def test_an_allocation_the_text_does_not_show_is_stopped_by_the_childs_limit() -> None:
    """A 30000 x 30000 height field passes every guard and asks the compile for 3.6 GB. The
    child's address-space limit refuses it, and the worker never allocates it (R106)."""
    bomb = ARM.replace(
        "<worldbody>",
        '<asset><hfield name="h" nrow="30000" ncol="30000" size="1 1 1 1"/></asset><worldbody>',
    )
    with pytest.raises(SimulationRefusedError, match="^the model does not compile$"):
        _run({**FACTS, "mjcf": bomb})


@needs_engine
def test_a_child_past_its_deadline_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mujoco_job, "CHILD_WALL_SECONDS", 0.05)
    started = time.monotonic()
    with pytest.raises(SimulationFailedError, match="went past 0.05 s of wall time"):
        _run()
    assert time.monotonic() - started < 5


@needs_engine
@pytest.mark.parametrize(
    ("mjcf", "engine_here", "status"),
    [
        pytest.param(ARM, True, "ran", id="the-arm"),
        pytest.param(ARM.replace("shoulder", "elbow"), True, "refused", id="no-such-joint"),
        pytest.param(ARM, False, "failed", id="no-engine"),
    ],
)
def test_the_child_writes_one_result_for_the_request_it_was_handed(
    mjcf: str, engine_here: bool, status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child's entry, run here with its limits stubbed (they would bind this test process):
    it reads the request beside it and writes one result."""
    monkeypatch.setattr(mujoco_job, "limit_child", lambda: None)
    if not engine_here:
        monkeypatch.setattr(mujoco_job, "physics_engine", lambda: None)
    monkeypatch.chdir(tmp_path)
    (tmp_path / mujoco_job.REQUEST).write_text(json.dumps({"mjcf": mjcf, "trajectory": ROUTINE}))
    mujoco_job.child_main()
    result = json.loads((tmp_path / mujoco_job.RESULT).read_text())
    assert result["status"] == status
    if status == "ran":
        outcome = TrajectoryOutcome.model_validate(result["outcome"])
        assert abs(outcome.forces[-1][0]) == pytest.approx(4.905, rel=1e-3)
    else:
        reasons = {
            "refused": "the model has no joint `shoulder`",
            "failed": mujoco_job.NOT_AVAILABLE,
        }
        assert result["reason"] == reasons[status]


def test_a_run_the_child_hands_back_is_read_whole(tmp_path: Path) -> None:
    (tmp_path / mujoco_job.RESULT).write_text(json.dumps({"status": "ran", "outcome": OUTCOME}))
    assert mujoco_job.outcome_of(tmp_path, 0) == TrajectoryOutcome.model_validate(OUTCOME)


STOPPED: Final = "stopped without a result"


@pytest.mark.parametrize(
    ("written", "code", "error", "match"),
    [
        pytest.param(None, 0, SimulationFailedError, STOPPED, id="no-result"),
        pytest.param(b"{not json", 0, SimulationFailedError, STOPPED, id="not-json"),
        pytest.param(
            b" " * (1024 * 1024 + 1), 0, SimulationFailedError, STOPPED, id="past-its-bound"
        ),
        pytest.param(
            {"status": "ran", "outcome": OUTCOME}, -9, SimulationFailedError, STOPPED, id="killed"
        ),
        pytest.param(
            {"status": "ran", "outcome": {**OUTCOME, "peaks": [5.4, 1.0]}},
            0,
            SimulationFailedError,
            STOPPED,
            id="a-ragged-recording",
        ),
        pytest.param(
            {"status": "ran", "outcome": {**OUTCOME, "forces": [[float("nan")], [4.9]]}},
            0,
            SimulationFailedError,
            STOPPED,
            id="a-diverged-run",
        ),
        pytest.param(
            {"status": "refused", "reason": "r" * 600},
            0,
            SimulationRefusedError,
            "^r{500}$",
            id="a-refusal-bounded",
        ),
        pytest.param(
            {"status": "failed", "reason": "the run went past 60 s of wall time"},
            0,
            SimulationFailedError,
            "^the run went past 60 s of wall time$",
            id="a-failure",
        ),
    ],
)
def test_what_the_child_left_is_read_back_as_untrusted(
    written: bytes | dict[str, Any] | None,
    code: int,
    error: type[Exception],
    match: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The child ran the engine over untrusted text, so what it left is untrusted too: bounded,
    parsed, validated whole, and on anything but a run the end of what it printed is logged."""
    (tmp_path / "stderr.txt").write_text("Traceback: the engine fell over\n")
    if written is not None:
        payload = written if isinstance(written, bytes) else json.dumps(written).encode()
        (tmp_path / mujoco_job.RESULT).write_bytes(payload)
    with (
        caplog.at_level(logging.WARNING, logger=mujoco_job.__name__),
        pytest.raises(error, match=match),
    ):
        mujoco_job.outcome_of(tmp_path, code)
    assert "the engine fell over" in caplog.text


def _points(*times: float) -> list[dict[str, Any]]:
    return [{"t": t, "positions": [0.0]} for t in times]


@pytest.mark.parametrize(
    "routine",
    [
        pytest.param({**ROUTINE, "joints": ["shoulder", "shoulder"]}, id="a-joint-twice"),
        pytest.param({"joints": ["shoulder"], "points": _points(0, 0)}, id="standing-still"),
        pytest.param({"joints": ["shoulder"], "points": _points(0.5, 1)}, id="not-from-zero"),
        pytest.param({"joints": ["shoulder"], "points": _points(0, 2, 1)}, id="back-in-time"),
        pytest.param(
            {
                "joints": ["shoulder"],
                "points": [{"t": 0, "positions": [0, 1]}, {"t": 1, "positions": [0]}],
            },
            id="two-targets-for-one-joint",
        ),
        pytest.param({"joints": ["shoulder"], "points": _points(*range(65))}, id="65-points"),
        pytest.param(
            {"joints": [f"j{k}" for k in range(17)], "points": ROUTINE["points"]}, id="17-joints"
        ),
        pytest.param(
            {"joints": ["shoulder"], "points": [{"t": 0, "positions": [float("nan")]}] * 2},
            id="nan",
        ),
        pytest.param({"joints": ["shoulder"], "points": _points(0, 31)}, id="past-thirty-seconds"),
        pytest.param({**ROUTINE, "joints": ["sh oulder"]}, id="a-name-with-a-space"),
        # the walk refuses a path mark in any of the model's values, so no joint can be named so
        pytest.param({**ROUTINE, "joints": ["robot0:shoulder"]}, id="a-name-with-a-colon"),
        pytest.param({**ROUTINE, "joints": ["arm/shoulder"]}, id="a-name-with-a-slash"),
        pytest.param({**ROUTINE, "speed": 2}, id="an-unknown-key"),
    ],
)
def test_joint_trajectory_is_generic_and_bounded(routine: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        JointTrajectory.model_validate(routine)
    lacks = RigidBodyTrajectory().can_answer(
        _question("peak_joint_current_a", {**FACTS, "trajectory": routine})
    )
    assert lacks.names == ("trajectory",)


def test_a_model_at_its_bound_fits_the_jobs_facts_and_is_counted_in_bytes() -> None:
    """Review Minor 7: the model's bound sits under the job's facts bound, with room for the
    escapes JSON adds, and it counts UTF-8 bytes, not characters."""
    body = '<body name="b"/>'  # as dense in quotes as a real model: one in eight characters
    near = "<mujoco>" + body * ((mujoco_job.MAX_MJCF_BYTES - 17) // len(body)) + "</mujoco>"
    assert len(near.encode()) <= mujoco_job.MAX_MJCF_BYTES
    ids = {"project_id": str(uuid.uuid4()), "subject_id": str(uuid.uuid4())}
    request = SimJobRequest.model_validate({**ids, "facts": {**FACTS, "mjcf": near}})
    assert request.facts["mjcf"] == near
    wide = "é" * (mujoco_job.MAX_MJCF_BYTES // 2 + 1)  # within the bound in characters, not bytes
    lone = '<mujoco model="\ud800"/>'  # a lone surrogate: JSON carries it, UTF-8 cannot encode it
    for mjcf in (wide, lone):
        question = _question("peak_joint_current_a", {**FACTS, "mjcf": mjcf})
        assert RigidBodyTrajectory().can_answer(question).names == ("mjcf",)


async def test_can_answer_and_an_absent_engine(
    monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine
) -> None:
    provider: SimProvider = RigidBodyTrajectory()
    assert (provider.name, provider.domain, provider.rung) == (
        "rigid_body_trajectory",
        "mechanical",
        3,
    )
    assert provider.quantities == {
        "peak_joint_torque_nm",
        "peak_joint_force_n",
        "peak_joint_current_a",
    }
    assert provider.can_answer(_question("peak_joint_current_a", {})).names == (
        "mjcf",
        "trajectory",
        "torque_constants",
    )
    partial = {**FACTS, "torque_constants": {"elbow": 0.5}}
    assert provider.can_answer(_question("peak_joint_current_a", partial)).names == (
        "torque_constants",
    )
    negative = {**FACTS, "torque_constants": {"shoulder": -0.5}}
    assert provider.can_answer(_question("peak_joint_current_a", negative)).names == (
        "torque_constants",
    )
    with pytest.raises(ValueError, match="does not compute"):
        provider.can_answer(_question("mass_kg", {}))
    assert set(RigidBodyTrajectory().inputs_for({**FACTS, "colour": "red"})) == set(FACTS)
    # no engine on this machine: not available, and the job says so before anything else
    monkeypatch.setattr(mujoco_job, "engine_installed", lambda: False)
    assert RigidBodyTrajectory().available is False
    with pytest.raises(SimulationFailedError, match="not available on this machine"):
        _run()
    request = {"project_id": str(uuid.uuid4()), "subject_id": str(uuid.uuid4()), "facts": FACTS}
    ctx = {
        "sessionmaker": async_sessionmaker(engine, expire_on_commit=False),
        "graph_hub": LiveHub(),
    }
    assert await run_mujoco_sim(ctx, request) == {
        "status": "not_available",
        "reason": "rigid_body_trajectory is not available on this machine",
    }


async def test_a_job_without_the_engine_leaves_a_finding_on_the_subject(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M140: a worker without the physics engine raises one standing info on the subject, naming
    the provider and why it did not run, since the queue keeps no result; nothing ran."""
    monkeypatch.setattr(mujoco_job, "engine_installed", lambda: False)
    project_id, part_id = await _seed(db, name="arm")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ctx = {"sessionmaker": sessions, "graph_hub": LiveHub()}
    request = {"project_id": str(project_id), "subject_id": str(part_id), "facts": FACTS}

    assert (await run_mujoco_sim(ctx, request))["status"] == "not_available"

    async with sessions() as read:
        flagged = list(
            await read.scalars(
                select(GraphEntity).where(
                    GraphEntity.kind == kinds.FINDING,
                    GraphEntity.attrs["rule_id"].astext == "simulation_not_available",
                )
            )
        )
        ran = await read.scalar(select(func.count()).where(GraphEntity.kind == kinds.SIM_RESULT))
    assert [finding.attrs["subjects"] for finding in flagged] == [[str(part_id)]]
    (only,) = flagged
    assert only.attrs["headline"] == (
        "could not simulate on the worker: rigid_body_trajectory is not available on this machine"
    )
    assert (only.attrs["evidence"]["provider"], only.domain, ran) == (
        "rigid_body_trajectory",
        "mechanical",
        0,
    )


@needs_engine
async def test_the_job_records_the_trajectory(db: AsyncSession, engine: AsyncEngine) -> None:
    project_id, part_id = await _seed(db, name="arm")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ctx = {"sessionmaker": sessions, "graph_hub": LiveHub()}
    request = {"project_id": str(project_id), "subject_id": str(part_id), "facts": FACTS}
    status = await run_mujoco_sim(ctx, request)
    assert status["status"] == "recorded"
    async with sessions() as read:
        row = await read.get(GraphEntity, uuid.UUID(str(status["sim_result_id"])))
        assert row is not None and row.kind == kinds.SIM_RESULT
        assert row.attrs["rung"] == 3
        assert row.attrs["provenance"]["inputs"]["expected_current_a"]["source"] == "derived"
        assert set(row.attrs["values"]) == {"peak_joint_torque_nm", "peak_joint_current_a"}
