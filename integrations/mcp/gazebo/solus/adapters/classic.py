"""The classic adapter (Gazebo 11): ``gz`` tools against a ``gzserver``.

Recorded from Classic 11.15.1 on 2026-11-09 (RECON §2): ``gz model`` has no ``--list`` and no
``-j``; model names come from the ``/gazebo/<w>/<model>/<link>/...`` topics and joints with their
angles from ``gz model -w <w> -m <m> -i`` (``gazebo.msgs.Model`` text format, names scoped
``<model>::<name>``). There is no joint-state topic, so a window is a poll at ≤ 10 Hz; there is
no save-world service, so ``save_world`` is :class:`Unsupported`.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from ..family_detect import Family
from .adapter_base import (
    RESET_SCOPES,
    CliError,
    CliRunner,
    Completed,
    ControlAction,
    JointSample,
    Scene,
    SceneJoint,
    SceneModel,
    Unsupported,
    WorldPose,
    check_abs_path,
    check_name,
    check_topic,
    finite,
    fmt_float,
    name_ok,
    parse_cli_text,
    run_argv,
    spawn_process,
    stderr_detail,
    text_items,
)

# ponytail: 10 Hz ceiling; a real classic `gz model -i` answers in ~0.5 s anyway.
POLL_INTERVAL_S: Final = 0.1
MAX_MODEL_LOOKUPS: Final = 32
# World-level topic families under /gazebo/<w>/ that are not model names.
_WORLD_TOPICS: Final = frozenset({"model", "pose", "light", "log", "physics", "factory"})
_RESET_FLAGS: Final = {"all": "-r", "time": "-t", "model_only": "-o"}
_SAVE_WORLD_SENTENCE: Final = (
    "Classic Gazebo has no save-world service; save from the GUI with File > Save World As."
)

#: Classic `gz topic -d` takes WHOLE seconds (`-d 0.3` is "Invalid arguments", recorded live in
#: P8-T2); world_stats publishes every 0.2 s, so one second always carries a sample.
CLASSIC_STATS_WINDOW_S: Final = 1


class ClassicAdapter:
    def __init__(
        self,
        family: Family,
        *,
        run: CliRunner = run_argv,
        home: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.family = family
        self.gz = str(family.bin_dir / "gz")
        self.run = run
        self.home = home
        self.clock = clock
        self.sleep = sleep

    # --- discovery ---------------------------------------------------------------------------

    def running_worlds(self) -> list[str]:
        worlds = {
            parts[2]
            for parts in self._topic_parts()
            if len(parts) == 4 and parts[1] == "gazebo" and parts[3] == "world_stats"
        }
        return sorted(worlds)

    def scene(self, world: str) -> Scene:
        check_name(world)
        names = sorted(
            {
                parts[3]
                for parts in self._topic_parts()
                if len(parts) >= 5 and parts[1:3] == ["gazebo", world]
                if parts[3] not in _WORLD_TOPICS and name_ok(parts[3])
            }
        )
        models = tuple(self._model(world, name) for name in names[:MAX_MODEL_LOOKUPS])
        return Scene(world=world, models=models)

    def _topic_parts(self) -> list[list[str]]:
        done = self._ok([self.gz, "topic", "-l"], 10.0)
        return [line.split("/") for line in done.stdout.splitlines() if line.startswith("/gazebo/")]

    def _model_info(self, world: str, model: str) -> dict[str, Any]:
        argv = [self.gz, "model", "-w", world, "-m", model, "-i"]
        done = self._ok(argv, 10.0)
        if "Unable to get info" in done.stdout or 'name: "' not in done.stdout:
            raise CliError(argv, f"model {model} is not in world {world}")
        return parse_cli_text(argv, done.stdout)

    def _model(self, world: str, name: str) -> SceneModel:
        doc = self._model_info(world, name)
        strip = f"{name}::"
        links = tuple(
            str(link["name"]).removeprefix(strip)
            for link in text_items(doc, "link")
            if isinstance(link.get("name"), str)
        )
        joints = tuple(
            SceneJoint(
                name=str(joint["name"]).removeprefix(strip),
                type=str(joint["type"]).lower() if isinstance(joint.get("type"), str) else None,
                parent_link=_unscoped(joint.get("parent"), strip),
                child_link=_unscoped(joint.get("child"), strip),
            )
            for joint in text_items(doc, "joint")
            if isinstance(joint.get("name"), str)
        )
        return SceneModel(name=name, links=links, joints=joints)

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self, world_file: Path, *, gui: bool) -> subprocess.Popen[bytes]:
        path = check_abs_path(world_file)
        exe = self.family.bin_dir / ("gazebo" if gui else "gzserver")
        home = self.home or Path.cwd() / ".solus" / "sim" / "home"
        return spawn_process([str(exe), path], home=home)

    def spawn(self, world: str, model_sdf_path: Path, name: str, pose: WorldPose) -> None:
        check_name(world)
        check_name(name)
        path = check_abs_path(model_sdf_path)
        x, y, z = (fmt_float(v) for v in pose.xyz)
        roll, pitch, yaw = (fmt_float(v) for v in pose.rpy)
        argv = [
            self.gz, "model", "-w", world, "-m", name, "-f", path,
            "-x", x, "-y", y, "-z", z, "-R", roll, "-P", pitch, "-Y", yaw,
        ]  # fmt: skip
        self._ok(argv, 20.0)
        # Classic answers rc 0 whether or not the model made it in (P8 defect B): confirm it.
        self._model_info(world, name)

    # --- state -------------------------------------------------------------------------------

    def joint_state(
        self, world: str, model: str, joints: Sequence[str] | None, window_s: float
    ) -> list[JointSample]:
        check_name(world)
        check_name(model)
        wanted = {check_name(j) for j in joints} if joints is not None else None
        polls: list[dict[str, Any]] = []
        started = self.clock()
        deadline = started + max(window_s, 0.0)
        tick = started
        while True:
            polls.append(self._model_info(world, model))
            tick += POLL_INTERVAL_S
            if tick > deadline or self.clock() >= deadline:
                break
            self.sleep(max(0.0, tick - self.clock()))
        paused = self._paused(world)
        samples = [
            JointSample(joint=name, position=angle, velocity=None, sim_time_s=None, paused=paused)
            for doc in polls
            for name, angle in _angles(doc, model)
            if wanted is None or name in wanted
        ]
        if not samples:
            raise CliError(
                [self.gz, "model"],
                f"no finite joint angles for the requested joints of {model}",
            )
        return samples

    def _paused(self, world: str) -> bool:
        topic = f"/gazebo/{world}/world_stats"
        argv = [self.gz, "topic", "-e", topic, "-d", str(CLASSIC_STATS_WINDOW_S)]
        done = self._ok(argv, CLASSIC_STATS_WINDOW_S + 2.0)
        flags = text_items(parse_cli_text(argv, done.stdout), "paused")
        if not flags:
            raise CliError(argv, f"world {world} publishes no world_stats")
        return bool(flags[-1])

    def set_targets(self, world: str, model: str, targets: Mapping[str, float]) -> None:
        check_name(world)
        check_name(model)
        plan = [(check_name(joint), fmt_float(value)) for joint, value in targets.items()]
        for joint, value in plan:
            argv = [self.gz, "joint", "-w", world, "-m", model, "-j", joint, "--pos-t", value]
            self._ok(argv, 10.0)

    def control(
        self, world: str, action: ControlAction, *, steps: int = 1, scope: str = "all"
    ) -> None:
        check_name(world)
        self._ok([self.gz, "world", "-w", world, *_world_flags(action, steps, scope)], 10.0)

    def save_world(self, world: str, root: Path, rel: str) -> None:
        check_name(world)
        raise Unsupported(self.family.name, self.family.version, _SAVE_WORLD_SENTENCE)

    def telemetry_argv(self, topic: str) -> list[str]:
        return [self.gz, "topic", "-e", check_topic(topic)]

    def _ok(self, argv: list[str], timeout: float) -> Completed:
        """Classic's CLIs report failures as `Error...` stderr lines with rc 0 (recorded live
        in P8-T2: `gz model -f` on an unparseable URDF), so an Error line fails like a rc."""
        done = self.run(argv, timeout)
        if done.returncode != 0 or _error_line(done.stderr):
            raise CliError(argv, f"gz {argv[1]} failed: {stderr_detail(done.stderr)}")
        return done


def _error_line(stderr: str) -> bool:
    return any(line.startswith("Error") for line in stderr.splitlines())


def _unscoped(value: Any, strip: str) -> str | None:
    return str(value).removeprefix(strip) if isinstance(value, str) else None


def _angles(doc: Mapping[str, Any], model: str) -> list[tuple[str, float]]:
    strip = f"{model}::"
    out: list[tuple[str, float]] = []
    for joint in text_items(doc, "joint"):
        name, angle = joint.get("name"), finite(joint.get("angle"))
        if isinstance(name, str) and angle is not None:
            out.append((name.removeprefix(strip), angle))
    return out


def _world_flags(action: str, steps: int, scope: str) -> list[str]:
    if action == "pause":
        return ["-p", "1"]
    if action == "play":
        return ["-p", "0"]
    if action == "step":
        if not isinstance(steps, int) or not 1 <= steps <= 10_000:
            raise ValueError("steps must be 1..10000")
        return ["-s"] if steps == 1 else ["-m", str(steps)]
    if action == "reset":
        if scope not in RESET_SCOPES:
            raise ValueError(f"reset scope must be one of {RESET_SCOPES}")
        return [_RESET_FLAGS[scope]]
    raise ValueError(f"unknown control action {action!r}")
