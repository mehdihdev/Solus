"""SOLUSDEV-321 P4-T3 — rung 3, mechanics in motion: the trajectory a scene model takes when its
joints follow a routine, the force its actuators need, and the current that force draws
(docs/api/simulation.md §7; R87, R106, R107).

`RigidBodyTrajectory` is a `SimProvider` at rung 3 (`name = "rigid_body_trajectory"`, mechanical).
It reads:

- `mjcf`: the scene model as the physics engine's own XML, at most `MAX_MJCF_BYTES` of UTF-8 (half
  the job's facts bound, so a model at its bound still fits once JSON escapes it). Before the
  engine sees it:
  - a DTD, a comment or a NUL is refused, and so is text that is not well-formed;
  - text whose root element is not the engine's own (`ENGINE`) is refused, a URDF among them;
  - livebench's guard runs on every text compiled (`_reject_file_referencing_mjcf`, reached
    through `load_local()`): a first, cheap reject of `<include>`, `file=` and `*dir`;
  - a walk over every parsed element is what the parser agrees with (`element_error`, R107): no
    `include`, `model`, `extension` or `plugin` element, no XML namespace, no attribute named
    `file*` or `*dir` (by the engine's own schema, every attribute it reads a file through), and
    no value holding a path;
  - the same walk refuses `replicate`, `composite`, `flexcomp` and `size` (R106): each multiplies
    the model, or sizes its memory, far past what its text states.

  It then compiles through the engine's virtual file system, under a directory that does not
  exist (`compiled`), and each of the compiled model's counts must be within its cap
  (`MODEL_CAPS`) before any `MjData` is made (`sized`).
- `trajectory`: a generic `JointTrajectory`, the joints a routine drives and timed targets for
  them;
- `torque_constants` {joint: N m/A, or N/A for a slide joint}: one positive constant for each joint
  the routine drives.

The run is forward dynamics. Each routine joint needs a position actuator in the model. At each
step its target is the routine's, interpolated linearly. The run records:

- the expected trajectory (each joint's position);
- the actuator force (the generalised force the actuators put on each joint);
- the expected current: that force over the joint's torque constant, `derived`.

It gives `peak_joint_torque_nm` (hinge joints), `peak_joint_force_n` (slide joints) and
`peak_joint_current_a`, each the largest over every step and every joint of its kind.

**It runs only inside its ARQ job, `run_mujoco_sim`, and the engine only in a child of its own**
(`simulate_in_child`, R106). A compile can run away: a hundred thousand replicas burn the whole
CPU limit. A few bytes can ask it for gigabytes: a height field, a texture. And a crash in the
engine must not take the worker with it. The child is this interpreter running this module
(`child_main`), with no PATH lookup and no shell. It gets a private directory, a three-name
environment, and the tessellation child's CPU and memory caps with a cap on every file it writes
(`limit_child`), set before it reads its request. It is killed hard at `CHILD_WALL_SECONDS`.
What it leaves is read back as untrusted (`outcome_of`).

The engine is an optional import, the way `load_local()` imports livebench; an engine or a
livebench that is absent is "not available on this machine". A run takes at most `MAX_STEPS`
steps and `MAX_WALL_SECONDS` of wall time, read at every step, and records at most `MAX_SAMPLES`
samples.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import json
import logging
import math
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Annotated, Any, Final, Self

# Parses only text whose DTDs and entities are refused before it is parsed.
from xml.etree import ElementTree  # noqa: S405

import numpy as np
from numpy.typing import NDArray
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationError,
    model_validator,
)

from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_api.livebench.sessions import load_local
from solus_api.simulation.providers import at_least
from solus_api.simulation.providers.ngspice_provider import limit_child, log_tail, run_or_flag
from solus_api.simulation.sim_capability import (
    MissingInputs,
    SimInput,
    SimProvenance,
    SimQuestion,
    SimResult,
    SimulationFailedError,
    SimulationRefusedError,
    SimValue,
)
from solus_api.simulation.sim_facts import MAX_JOB_FACTS_BYTES

logger = logging.getLogger(__name__)

ENGINE: Final = "mujoco"  # capability-hygiene: allow the engine's import and XML root
NOT_AVAILABLE: Final = "the physics engine is not available on this machine"
#: The bounds of one run. The model is counted in UTF-8 bytes, at half the job's facts bound, so a
#: model at its bound still fits beside its routine once JSON escapes its quotes (review Minor 7).
MAX_MJCF_BYTES: Final = MAX_JOB_FACTS_BYTES // 2
MAX_STEPS: Final = 50_000
MAX_WALL_SECONDS: Final = 60.0
#: A routine's bounds: joints, points and seconds.
MAX_JOINTS: Final = 16
MAX_POINTS: Final = 64
MAX_DURATION_S: Final = 30.0
#: What a result records: at most `MAX_SAMPLES` samples, and about `SERIES_VALUES` values a series
#: across the routine's joints, so the result stays under its byte bound.
MAX_SAMPLES: Final = 200
SERIES_VALUES: Final = 1_200
#: A floor for a torque constant, far below any motor's: it keeps a zero out of the division.
MIN_CONSTANT: Final = 1e-9
#: Elements a model may not hold: they reach another file or load code (R107), or multiply the
#: model or size its memory far past what its text states (R106).
REFUSED_TAGS: Final = frozenset(
    {"include", "model", "extension", "plugin", "replicate", "composite", "flexcomp", "size"}
)
#: What marks an attribute's value as a path: a separator, a parent directory, a drive or a scheme.
PATH_MARKS: Final = ("/", "\\", "..", ":")
#: The most a compiled model may hold, each checked before any `MjData` is made (R106). A chain of
#: 255 hinges fits, and its default arena is 28 MiB.
MODEL_CAPS: Final = MappingProxyType(
    {
        "nbody": (256, "bodies"),
        "njnt": (256, "joints"),
        "nu": (128, "actuators"),
        "ngeom": (1024, "geoms"),
        "nv": (256, "degrees of freedom"),
        "narena": (64 * 1024 * 1024, "bytes of arena"),
    }
)
#: The child's two files, in a private directory of its own, and the most the parent reads back.
REQUEST: Final = "request.json"
RESULT: Final = "result.json"
MAX_RESULT_BYTES: Final = 1024 * 1024
#: The child's hard deadline: the run's own wall time, and time to start and to compile.
CHILD_WALL_SECONDS: Final = MAX_WALL_SECONDS + 15
#: The most of a reason, or of the engine's message, that is kept.
MAX_REASON_CHARS: Final = 500
STOPPED: Final = (
    "the physics run stopped without a result: past its CPU or memory limit, or the engine failed"
)
QUANTITIES: Final = frozenset(
    {"peak_joint_torque_nm", "peak_joint_force_n", "peak_joint_current_a"}
)
READS: Final = ("mjcf", "trajectory", "torque_constants")
MJCF: Final = FactNeed(
    name="mjcf",
    set_in="the scene model's XML in the physics engine's own format (at most "
    f"{MAX_MJCF_BYTES // 1024} KiB of UTF-8)",
)
TRAJECTORY: Final = FactNeed(
    name="trajectory",
    set_in="the routine as {joints, points: [{t, positions}]}: at most 16 joints and 64 points, "
    "from 0 s, strictly in time, within 30 s",
)
CONSTANTS: Final = FactNeed(
    name="torque_constants",
    set_in="the drives' `torque_constants` {joint: N m/A, or N/A for a slide}, one for each joint "
    "the routine drives",
)

#: No `:` and no `/`: the walk refuses either in a model's value (`PATH_MARKS`), so no joint holds
#: one.
JointName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.\-]{1,128}$")]
Target = Annotated[float, Field(allow_inf_nan=False, ge=-1e3, le=1e3)]
Real = Annotated[float, Field(allow_inf_nan=False)]


class TrajectoryPoint(BaseModel):
    """One timed target: where each of the routine's joints should be at `t` seconds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    t: float = Field(ge=0, le=MAX_DURATION_S, allow_inf_nan=False)
    positions: tuple[Target, ...] = Field(min_length=1, max_length=MAX_JOINTS)


class JointTrajectory(BaseModel):
    """A generic routine: the joints it drives, and timed targets for them (radians for a hinge,
    metres for a slide), from 0 s and strictly in time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    joints: tuple[JointName, ...] = Field(min_length=1, max_length=MAX_JOINTS)
    points: tuple[TrajectoryPoint, ...] = Field(min_length=2, max_length=MAX_POINTS)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.joints)) != len(self.joints):
            raise ValueError("a routine names a joint twice")
        if any(len(point.positions) != len(self.joints) for point in self.points):
            raise ValueError("each point holds one target for each joint")
        times = [point.t for point in self.points]
        paired = zip(times, times[1:], strict=False)
        if times[0] != 0 or any(later <= earlier for earlier, later in paired):
            raise ValueError("a routine starts at 0 s and moves forward in time")
        return self


class TrajectoryOutcome(BaseModel):
    """A run's whole outcome, as the child hands it back (`follow`): the model's counts and
    timestep, whether each routine joint is a hinge, and the recording. That is the sampled
    times, positions and forces one column a joint, the largest force on each joint over every
    step, and the steps taken. The parent reads it as untrusted, so its shape is checked too."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bodies: int = Field(ge=1)
    joints: int = Field(ge=0)
    actuators: int = Field(ge=0)
    timestep_s: float = Field(gt=0, allow_inf_nan=False)
    hinges: tuple[bool, ...] = Field(min_length=1, max_length=MAX_JOINTS)
    times: tuple[Real, ...] = Field(min_length=1, max_length=MAX_SAMPLES)
    positions: tuple[tuple[Real, ...], ...]
    forces: tuple[tuple[Real, ...], ...]
    peaks: tuple[Real, ...]
    steps: int = Field(ge=1)

    @model_validator(mode="after")
    def _one_row_a_sample_and_one_column_a_joint(self) -> Self:
        columns, rows = len(self.hinges), len(self.times)
        tables = (self.positions, self.forces)
        if len(self.peaks) != columns or any(len(table) != rows for table in tables):
            raise ValueError("a recording holds one row a sample and one column a joint")
        if any(len(row) != columns for table in tables for row in table):
            raise ValueError("a recording holds one row a sample and one column a joint")
        return self


@dataclass(frozen=True)
class JointDrive:
    """A routine joint's handles in the compiled model: its position slot, its velocity slot, its
    position actuator, and whether it is a hinge."""

    joint: str
    qpos: int
    dof: int
    actuator: int
    hinge: bool


def engine_installed() -> bool:
    """Whether this server has the engine: found, never imported here. Only the child imports
    it."""
    return importlib.util.find_spec(ENGINE) is not None


def physics_engine() -> ModuleType | None:
    """The physics engine, when this server has it installed: an optional import, as
    `load_local()` imports livebench."""
    if not engine_installed():
        return None
    return importlib.import_module(ENGINE)


def read_trajectory(facts: Mapping[str, Any]) -> JointTrajectory | None:
    try:
        return JointTrajectory.model_validate(facts.get("trajectory"))
    except ValidationError:
        return None


def read_constants(facts: Mapping[str, Any], routine: JointTrajectory | None) -> bool:
    """Whether `torque_constants` is a mapping of positive numbers. When the routine is known, it
    must give one for each joint the routine drives."""
    raw = facts.get("torque_constants")
    positive = at_least(MIN_CONSTANT)
    if not isinstance(raw, Mapping) or not all(positive(v) is not None for v in raw.values()):
        return False
    return routine is None or all(joint in raw for joint in routine.joints)


def mjcf_size(raw: object) -> int | None:
    """The model's size in UTF-8 bytes, or None when it is no text, or text UTF-8 cannot encode (a
    lone surrogate, which JSON can carry; the parser would raise on it)."""
    if not isinstance(raw, str):
        return None
    try:
        return len(raw.encode())
    except UnicodeEncodeError:
        return None


def trajectory_unmet(facts: Mapping[str, Any]) -> tuple[FactNeed, ...]:
    """What a run lacks, in the order the facts are named. Every quantity needs all three."""
    size = mjcf_size(facts.get("mjcf"))
    routine = read_trajectory(facts)
    needs = [] if size is not None and 0 < size <= MAX_MJCF_BYTES else [MJCF]
    needs += [] if routine is not None else [TRAJECTORY]
    return (*needs, *([] if read_constants(facts, routine) else [CONSTANTS]))


def checked_mjcf(xml: str, local: Any) -> None:
    """Refuses, before the engine sees it, text that is not the engine's own XML, or that could
    reach a file or a plugin, or multiply the model (module docstring)."""
    if "<!" in xml or "\x00" in xml:
        raise SimulationRefusedError("the model may hold no DTD, comment or NUL")
    try:
        root = ElementTree.fromstring(xml)  # noqa: S314 — no DTD or entity reaches the parser
    except ElementTree.ParseError:
        raise SimulationRefusedError("the model is not well-formed XML") from None
    if root.tag != ENGINE:
        raise SimulationRefusedError(
            "the model's root element is not the engine's own: a URDF or another format is refused"
        )
    try:
        local._reject_file_referencing_mjcf(xml)
    except ValueError as exc:
        raise SimulationRefusedError(str(exc)) from None
    for element in root.iter():
        why = element_error(element)
        if why is not None:
            raise SimulationRefusedError(why)


def element_error(element: ElementTree.Element) -> str | None:
    """Why one parsed element could reach a file, load code or multiply the model, or None (R106,
    R107). The substring guard above is a first, cheap reject; this walk is what the parser itself
    agrees with:

    - no element in `REFUSED_TAGS`;
    - no XML namespace, which would hide a name from both;
    - no attribute whose name starts `file` or ends `dir` (`dir` itself, a light's direction, is
      a vector);
    - no attribute value that holds a path: a separator, a parent directory, a drive or a scheme.
    """
    if "{" in element.tag:
        return "the model may use no XML namespace"
    if element.tag in REFUSED_TAGS:
        return f"the model may hold no `{element.tag}` element"
    for name, value in element.attrib.items():
        if "{" in name:
            return "the model may use no XML namespace"
        if name.startswith("file") or (name.endswith("dir") and name != "dir"):
            return f"the model may name no file or directory (`{name[:32]}`)"
        if any(mark in value for mark in PATH_MARKS):
            return f"attribute `{name[:32]}` holds a path"
    return None


def compiled(engine: Any, xml: str) -> Any:
    """The compiled model, through the engine's virtual file system (R107). The text is the one
    file the VFS holds, at a path under a directory that does not exist. A relative reference,
    which a compile from a string resolves against the worker's working directory, resolves there
    to nothing and is never opened; a reference to an asset the VFS lacks fails closed. An
    absolute path the engine still opens from the disk (verified on 3.11.0), so `element_error`
    refusing every file attribute and every value holding a path is what keeps one out. The
    engine's own message can echo the text it was handed, so it is logged in part and never
    returned."""
    with tempfile.TemporaryDirectory(prefix="solus-scene-") as private:
        path = str(Path(private) / "absent" / "scene.xml")
        try:
            return engine.MjModel.from_xml_path(path, {path: xml.encode()})
        except Exception as exc:  # noqa: BLE001 — whatever the engine raises, the model is refused
            logger.warning("scene model did not compile: %s", str(exc)[:MAX_REASON_CHARS])
            raise SimulationRefusedError("the model does not compile") from None


def sized(model: Any) -> Any:
    """The compiled model, once each of its counts is within its cap (`MODEL_CAPS`, R106). It is
    checked before any `MjData` is made, so no arena is allocated for a model past one."""
    for count, (cap, noun) in MODEL_CAPS.items():
        held = int(getattr(model, count))
        if held > cap:
            raise SimulationRefusedError(
                f"the model has {held:,} {noun}; a run takes at most {cap:,}"
            )
    return model


def drives_of(engine: Any, model: Any, routine: JointTrajectory) -> tuple[JointDrive, ...]:
    """Each routine joint's handles: a hinge or a slide, driven by a position actuator."""
    servo = (
        (model.actuator_trntype == engine.mjtTrn.mjTRN_JOINT)
        & (model.actuator_biastype == engine.mjtBias.mjBIAS_AFFINE)
        & (model.actuator_gainprm[:, 0] > 0)
        & np.isclose(model.actuator_biasprm[:, 1], -model.actuator_gainprm[:, 0])
    )
    kinds = {int(engine.mjtJoint.mjJNT_HINGE): True, int(engine.mjtJoint.mjJNT_SLIDE): False}
    drives: list[JointDrive] = []
    for name in routine.joints:
        joint = engine.mj_name2id(model, engine.mjtObj.mjOBJ_JOINT, name)
        if joint < 0:
            raise SimulationRefusedError(f"the model has no joint `{name}`")
        if int(model.jnt_type[joint]) not in kinds:
            raise SimulationRefusedError(f"joint `{name}` is neither a hinge nor a slide")
        found = np.flatnonzero(servo & (model.actuator_trnid[:, 0] == joint))
        if not len(found):
            raise SimulationRefusedError(f"joint `{name}` has no position actuator")
        hinge = kinds[int(model.jnt_type[joint])]
        qpos, dof = int(model.jnt_qposadr[joint]), int(model.jnt_dofadr[joint])
        drives.append(JointDrive(name, qpos, dof, int(found[0]), hinge))
    return tuple(drives)


def follow(
    engine: Any, model: Any, routine: JointTrajectory, drives: tuple[JointDrive, ...]
) -> TrajectoryOutcome:
    """Step the model along the routine (module docstring), within `MAX_STEPS` and
    `MAX_WALL_SECONDS`, the wall clock read at every step (R106). Every array is sized before the
    first step."""
    timestep = float(model.opt.timestep)
    steps = math.ceil(round(routine.points[-1].t / timestep, 9))
    if steps > MAX_STEPS:
        raise SimulationRefusedError(
            f"the routine needs {steps:,} steps at the model's timestep; a run takes at most "
            f"{MAX_STEPS:,}"
        )
    times = np.array([point.t for point in routine.points])
    targets = np.array([point.positions for point in routine.points])
    clock = np.arange(1, steps + 1) * timestep
    plan = np.stack([np.interp(clock, times, targets[:, k]) for k in range(len(drives))], axis=1)
    count = max(2, min(MAX_SAMPLES, SERIES_VALUES // len(drives)))
    marks = np.unique(np.append(np.linspace(0, steps - 1, count).astype(int), steps - 1))
    sampled = {int(step): row for row, step in enumerate(marks)}
    positions, forces = np.empty((len(marks), len(drives))), np.empty((len(marks), len(drives)))
    actuators, dofs = [d.actuator for d in drives], [d.dof for d in drives]
    qpos = [d.qpos for d in drives]
    data = engine.MjData(model)
    data.qpos[qpos] = targets[0]
    engine.mj_forward(model, data)
    peaks = np.zeros(len(drives))
    started = time.monotonic()
    for step in range(steps):
        if time.monotonic() - started > MAX_WALL_SECONDS:
            raise SimulationFailedError(f"the run went past {MAX_WALL_SECONDS:g} s of wall time")
        data.ctrl[actuators] = plan[step]
        engine.mj_step(model, data)
        force = data.qfrc_actuator[dofs]
        np.maximum(peaks, np.abs(force), out=peaks)
        if step in sampled:
            positions[sampled[step]], forces[sampled[step]] = data.qpos[qpos], force
    return TrajectoryOutcome.model_validate(
        {
            "bodies": int(model.nbody),
            "joints": int(model.njnt),
            "actuators": int(model.nu),
            "timestep_s": timestep,
            "hinges": [drive.hinge for drive in drives],
            "times": clock[marks].tolist(),
            "positions": positions.tolist(),
            "forces": forces.tolist(),
            "peaks": peaks.tolist(),
            "steps": steps,
        }
    )


def simulate(engine: Any, xml: str, routine: JointTrajectory) -> TrajectoryOutcome:
    """The child's whole run: compile, check each count against its cap, find the drives, and
    follow the routine."""
    model = sized(compiled(engine, xml))
    return follow(engine, model, routine, drives_of(engine, model, routine))


def child_main() -> None:
    """The child `simulate_in_child` starts, in its private directory: its limits before anything
    else, then the one request beside it, and one result."""
    limit_child()
    request = json.loads(Path(REQUEST).read_bytes())
    engine = physics_engine()
    result: dict[str, JsonValue]
    try:
        if engine is None:
            raise SimulationFailedError(NOT_AVAILABLE)
        routine = JointTrajectory.model_validate(request["trajectory"])
        outcome = simulate(engine, str(request["mjcf"]), routine)
        result = {"status": "ran", "outcome": outcome.model_dump(mode="json")}
    except SimulationRefusedError as exc:
        result = {"status": "refused", "reason": str(exc)}
    except SimulationFailedError as exc:
        result = {"status": "failed", "reason": str(exc)}
    Path(RESULT).write_text(json.dumps(result))


def simulate_in_child(xml: str, routine: JointTrajectory) -> TrajectoryOutcome:
    """`simulate`, in a child of its own (module docstring, R106): this interpreter running this
    module, in a private directory, killed hard at `CHILD_WALL_SECONDS`."""
    with tempfile.TemporaryDirectory(prefix="solus-trajectory-") as private:
        work = Path(private)
        request = {"mjcf": xml, "trajectory": routine.model_dump(mode="json")}
        (work / REQUEST).write_text(json.dumps(request))
        with (work / "stderr.txt").open("wb") as err:
            try:
                done = subprocess.run(  # noqa: S603 — this interpreter and this module, no shell
                    [sys.executable, "-I", "-m", __name__],
                    cwd=work,
                    env={"HOME": private, "LC_ALL": "C", "OPENBLAS_NUM_THREADS": "1"},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=err,
                    timeout=CHILD_WALL_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise SimulationFailedError(
                    f"the run went past {CHILD_WALL_SECONDS:g} s of wall time"
                ) from None
            except (OSError, subprocess.SubprocessError) as exc:
                raise SimulationFailedError(
                    f"the physics run did not start: {type(exc).__name__}"
                ) from None
        return outcome_of(work, done.returncode)


def outcome_of(work: Path, code: int) -> TrajectoryOutcome:
    """What the child left in `work`, read back as untrusted: at most `MAX_RESULT_BYTES`, parsed,
    and validated whole. A refusal or a failure the child reports is raised as one, its reason
    bounded; on anything but a run, the end of what the child printed is logged."""
    path, raw = work / RESULT, None
    if code == 0 and path.is_file() and path.stat().st_size <= MAX_RESULT_BYTES:
        with contextlib.suppress(ValueError, RecursionError):
            raw = json.loads(path.read_bytes())
    status = raw.get("status") if isinstance(raw, dict) else None
    try:
        if status == "ran" and isinstance(raw, dict):
            return TrajectoryOutcome.model_validate(raw.get("outcome"))
    except ValidationError:
        status = "malformed"
    logger.warning("physics run %s (exit %s): %s", status or "stopped", code, log_tail(work))
    if status in ("refused", "failed") and isinstance(raw, dict):
        error = SimulationRefusedError if status == "refused" else SimulationFailedError
        raise error(str(raw.get("reason"))[:MAX_REASON_CHARS])
    raise SimulationFailedError(STOPPED)


def rounded(values: NDArray[np.float64]) -> list[JsonValue]:
    """A recorded series, to six significant figures."""
    return [float(f"{value:.6g}") for value in values]


def trajectory_values(
    outcome: TrajectoryOutcome, constants: NDArray[np.float64]
) -> dict[str, SimValue]:
    peaks = np.array(outcome.peaks, dtype=np.float64)
    values = {"peak_joint_current_a": SimValue(value=float((peaks / constants).max()), unit="A")}
    hinges = [k for k, hinge in enumerate(outcome.hinges) if hinge]
    slides = [k for k, hinge in enumerate(outcome.hinges) if not hinge]
    if hinges:
        values["peak_joint_torque_nm"] = SimValue(value=float(peaks[hinges].max()), unit="N m")
    if slides:
        values["peak_joint_force_n"] = SimValue(value=float(peaks[slides].max()), unit="N")
    return values


def trajectory_inputs(
    inputs: Mapping[str, SimInput],
    routine: JointTrajectory,
    outcome: TrajectoryOutcome,
    constants: NDArray[np.float64],
) -> dict[str, SimInput]:
    """Each input with its source, and the recorded series as `derived`. The model is recorded by
    its counts, never by its text."""

    def series(table: NDArray[np.float64]) -> dict[str, JsonValue]:
        return {joint: rounded(table[:, k]) for k, joint in enumerate(routine.joints)}

    forces = np.array(outcome.forces, dtype=np.float64)
    shape: dict[str, JsonValue] = {
        "bytes": len(str(inputs["mjcf"].value).encode()),
        "bodies": outcome.bodies,
        "joints": outcome.joints,
        "actuators": outcome.actuators,
    }
    trajectory: dict[str, JsonValue] = {"t": rounded(np.array(outcome.times, dtype=np.float64))}
    trajectory["positions"] = series(np.array(outcome.positions, dtype=np.float64))
    used: dict[str, JsonValue] = {
        joint: float(k) for joint, k in zip(routine.joints, constants, strict=True)
    }
    return {
        "mjcf": SimInput(value=shape, source=inputs["mjcf"].source),
        "trajectory": inputs["trajectory"],
        "torque_constants": SimInput(value=used, source=inputs["torque_constants"].source),
        "timestep_s": SimInput(value=outcome.timestep_s, source="known"),
        "steps": SimInput(value=outcome.steps, source="derived"),
        "expected_trajectory": SimInput(value=trajectory, source="derived"),
        "actuator_force": SimInput(value=series(forces), source="derived"),
        "expected_current_a": SimInput(value=series(np.abs(forces) / constants), source="derived"),
    }


LEAVES_OUT: Final = (
    "the motor's electrical dynamics: the current is the joint's force over its torque constant, "
    "at once",
    "friction, backlash and compliance the model does not state",
    "control beyond the model's own position actuators, which follow the routine's linear "
    "interpolation",
    "the steps between recorded samples (the peaks are over every step)",
    "sensor noise and delay",
)


@dataclass(frozen=True)
class RigidBodyTrajectory:
    """The trajectory job's provider (module docstring)."""

    name: str = "rigid_body_trajectory"
    domain: str = "mechanical"
    rung: int = 3
    quantities: frozenset[str] = QUANTITIES

    @property
    def available(self) -> bool:
        return engine_installed() and load_local() is not None

    def can_answer(self, question: SimQuestion) -> MissingInputs:
        if question.quantity not in QUANTITIES:
            raise ValueError(f"{self.name} does not compute {question.quantity!r}")
        lacks = trajectory_unmet(question.facts)
        return MissingInputs(missing=lacks, covered=() if lacks else tuple(sorted(QUANTITIES)))

    def inputs_for(self, facts: Mapping[str, Any]) -> dict[str, SimInput]:
        """The facts a run reads, each stated `known`: the graph or the caller states them."""
        return {
            name: SimInput(value=facts[name], source="known") for name in READS if name in facts
        }

    def run(self, inputs: Mapping[str, SimInput]) -> SimResult:
        """The run (module docstring); only `run_mujoco_sim` calls it. `SimulationFailedError` when
        the engine or livebench is absent, or the run passes a limit or stops without a result;
        `SimulationRefusedError` when there is nothing to run, or the model is refused, does not
        compile, is past a cap, cannot be driven, or needs too many steps."""
        local = load_local()
        if not engine_installed() or local is None:
            raise SimulationFailedError(NOT_AVAILABLE)
        facts = {name: item.value for name, item in inputs.items()}
        lacks = trajectory_unmet(facts)
        routine = read_trajectory(facts)
        raw = facts.get("torque_constants")
        if lacks or routine is None or not isinstance(raw, Mapping):
            names = ", ".join(need.name for need in lacks)
            raise SimulationRefusedError(f"{self.name} has nothing to compute: {names} unknown")
        xml = str(facts["mjcf"])
        checked_mjcf(xml, local)
        outcome = simulate_in_child(xml, routine)
        # each a positive number, as `trajectory_unmet` checked
        constants = np.array([raw[joint] for joint in routine.joints], dtype=np.float64)
        return SimResult(
            values=trajectory_values(outcome, constants),
            provenance=SimProvenance(
                solver=self.name,
                inputs=trajectory_inputs(inputs, routine, outcome, constants),
                leaves_out=LEAVES_OUT,
            ),
        )


async def run_mujoco_sim(ctx: dict[str, Any], request: dict[str, Any]) -> dict[str, JsonValue]:
    """The ARQ job, and the one caller of `RigidBodyTrajectory.run` (module docstring): the run,
    off the event loop and recorded (`run_and_record`), or flagged on the subject when the worker
    lacks the engine (`run_or_flag`, M140)."""
    return await run_or_flag(ctx, RigidBodyTrajectory(), request)


if __name__ == "__main__":  # pragma: no cover — the child's entry, which `simulate_in_child` runs
    child_main()
