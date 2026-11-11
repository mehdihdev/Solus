"""The new-family adapter (`gz sim`: Garden 7, Harmonic 8, Ionic 9, Jetty 10).

Argv shapes recorded from Harmonic 8.15.0 on 2026-11-09 (RECON §3). Services always carry
``--timeout``. Joints are listed with ``gz model -m <m> -j`` because ``scene/info`` carries
models and links only (verified live); ``gz model`` reads the first running world, so joint
listings assume the one owned server this fork runs.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar, Final

from ..family_detect import Family
from ..worlds import confined_write, rel_parts
from .adapter_base import (
    MAX_SAMPLES,
    RESET_SCOPES,
    SERVICE_TIMEOUT_MS,
    STATS_WINDOW_S,
    CliError,
    CliRunner,
    Completed,
    ControlAction,
    JointSample,
    Scene,
    SceneJoint,
    SceneModel,
    WorldPose,
    check_abs_path,
    check_name,
    check_topic,
    decimate,
    finite,
    fmt_float,
    name_ok,
    parse_cli_text,
    run_argv,
    spawn_process,
    stderr_detail,
    text_items,
)

_JOINT_LINE = re.compile(r"^- Joint \[\d+\]$")
_FIELD = re.compile(r"^\s+- (Name|Type|Parent Link|Child Link): (.+?)(?: \[\d+\])?$")
MAX_JOINT_LOOKUPS: Final = 32  # ponytail: joints listed for the first 32 models of a scene
_RESET_FIELDS: Final = {"all": "all", "time": "time_only", "model_only": "model_only"}


class GzAdapter:
    MSGS: ClassVar[str] = "gz.msgs"
    SUB: ClassVar[str] = "sim"

    def __init__(
        self, family: Family, *, run: CliRunner = run_argv, home: Path | None = None
    ) -> None:
        self.family = family
        self.exe = str(family.exe)
        self.run = run
        self.home = home

    # --- discovery ---------------------------------------------------------------------------

    def running_worlds(self) -> list[str]:
        done = self._ok([self.exe, "service", "-l"], 10.0)
        worlds = {
            line.split("/")[2]
            for line in done.stdout.splitlines()
            if line.startswith("/world/") and line.count("/") >= 3
        }
        return sorted(worlds)

    def scene(self, world: str) -> Scene:
        check_name(world)
        doc = self._service(world, "scene/info", "Empty", "Scene", "")
        models: list[SceneModel] = []
        for index, model in enumerate(text_items(doc, "model")):
            name = model.get("name")
            if not isinstance(name, str):
                continue
            links = tuple(
                link["name"] for link in text_items(model, "link") if name_ok(link.get("name"))
            )
            joints = self._joints(name) if index < MAX_JOINT_LOOKUPS and name_ok(name) else ()
            models.append(SceneModel(name=name, links=links, joints=joints))
        return Scene(world=world, models=tuple(models))

    def _joints(self, model: str) -> tuple[SceneJoint, ...]:
        done = self._ok([self.exe, "model", "-m", model, "-j"], 10.0)
        joints: list[dict[str, str]] = []
        for line in done.stdout.splitlines():
            if _JOINT_LINE.match(line):
                joints.append({})
            elif joints and (field := _FIELD.match(line)):
                joints[-1][field.group(1)] = field.group(2)
        return tuple(
            SceneJoint(j["Name"], j.get("Type"), j.get("Parent Link"), j.get("Child Link"))
            for j in joints
            if "Name" in j
        )

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self, world_file: Path, *, gui: bool) -> subprocess.Popen[bytes]:
        path = check_abs_path(world_file)
        argv = [self.exe, self.SUB, *(() if gui else ("-s",)), "-r", path]
        return spawn_process(argv, home=self.home or Path.cwd() / ".solus" / "sim" / "home")

    def spawn(self, world: str, model_sdf_path: Path, name: str, pose: WorldPose) -> None:
        check_name(world)
        check_name(name)
        path = check_abs_path(model_sdf_path)
        x, y, z = (fmt_float(v) for v in pose.xyz)
        qx, qy, qz, qw = (fmt_float(v) for v in pose.quaternion())
        req = (
            f'sdf_filename: "{path}" name: "{name}" pose {{ position {{ x: {x} y: {y} z: {z} }} '
            f"orientation {{ x: {qx} y: {qy} z: {qz} w: {qw} }} }}"
        )
        self._expect_true(world, "create", "EntityFactory", req, "the server refused the spawn")

    # --- state -------------------------------------------------------------------------------

    def joint_state(
        self, world: str, model: str, joints: Sequence[str] | None, window_s: float
    ) -> list[JointSample]:
        check_name(world)
        check_name(model)
        wanted = {check_name(j) for j in joints} if joints is not None else None
        topic = f"/world/{world}/model/{model}/joint_state"
        argv = [self.exe, "topic", "-e", "-t", topic, "--json-output"]
        argv += ["-n", "1"] if window_s <= 0 else ["-d", fmt_float(window_s)]
        done = self._ok(argv, max(window_s, 0.0) + 1.0)
        messages = [m for m in map(_json_object_line, done.stdout.splitlines()) if m]
        if not messages:
            raise CliError(argv, f"no joint_state published for {model} in {world}")
        paused = self._paused(world)
        samples = [
            sample
            for message in decimate(messages, MAX_SAMPLES)
            for sample in _joint_samples_from_message(message, wanted, paused)
        ]
        if not samples:
            raise CliError(argv, f"none of the requested joints are published by {model}")
        return samples

    def _paused(self, world: str) -> bool:
        topic = f"/world/{world}/stats"
        argv = [
            self.exe,
            "topic",
            "-e",
            "-t",
            topic,
            "--json-output",
            "-d",
            fmt_float(STATS_WINDOW_S),
        ]
        done = self._ok(argv, STATS_WINDOW_S + 1.0)
        lines = [m for m in map(_json_object_line, done.stdout.splitlines()) if m]
        if not lines:
            raise CliError(argv, f"world {world} publishes no stats")
        return bool(lines[-1].get("paused", False))

    def set_targets(self, world: str, model: str, targets: Mapping[str, float]) -> None:
        check_name(world)
        check_name(model)
        plan = [(check_name(joint), fmt_float(value)) for joint, value in targets.items()]
        for joint, value in plan:
            topic = f"/model/{model}/joint/{joint}/0/cmd_pos"
            argv = [
                self.exe,
                "topic",
                "-t",
                topic,
                "-m",
                f"{self.MSGS}.Double",
                "-p",
                f"data: {value}",
            ]
            self._ok(argv, 5.0)

    def control(
        self, world: str, action: ControlAction, *, steps: int = 1, scope: str = "all"
    ) -> None:
        check_name(world)
        req = _world_control_request(action, steps, scope)
        self._expect_true(world, "control", "WorldControl", req, f"the server refused {action}")

    def save_world(self, world: str, root: Path, rel: str) -> None:
        """The running world's SDF written to ``root/rel`` through :func:`confined_write`."""
        check_name(world)
        rel_parts(rel)  # refuse a hostile destination before the server is asked
        doc = self._service(world, "generate_world_sdf", "SdfGeneratorConfig", "StringMsg", "")
        data = doc.get("data")
        if not isinstance(data, str) or not data.lstrip().startswith("<sdf"):
            raise CliError([self.exe, "service"], "the server returned no world SDF")
        confined_write(root, rel, data.encode())

    def telemetry_argv(self, topic: str) -> list[str]:
        return [self.exe, "topic", "-e", "-t", check_topic(topic), "--json-output"]

    # --- plumbing ----------------------------------------------------------------------------

    def _service(
        self, world: str, name: str, reqtype: str, reptype: str, req: str
    ) -> dict[str, Any]:
        argv = [
            self.exe, "service", "-s", f"/world/{world}/{name}",
            "--reqtype", f"{self.MSGS}.{reqtype}", "--reptype", f"{self.MSGS}.{reptype}",
            "--timeout", str(SERVICE_TIMEOUT_MS), "--req", req,
        ]  # fmt: skip
        done = self._ok(argv, SERVICE_TIMEOUT_MS / 1000 + 3.0)
        if "timed out" in done.stderr:
            raise CliError(argv, f"service /world/{world}/{name} timed out (is the world running?)")
        if "Unable to create request" in done.stderr:
            raise CliError(argv, f"the server rejected the {reqtype} request")
        return parse_cli_text(argv, done.stdout)

    def _expect_true(self, world: str, name: str, reqtype: str, req: str, failure: str) -> None:
        if self._service(world, name, reqtype, "Boolean", req).get("data") is not True:
            raise CliError([self.exe, "service", name], failure)

    def _ok(self, argv: list[str], timeout: float) -> Completed:
        done = self.run(argv, timeout)
        if done.returncode != 0:
            detail = stderr_detail(done.stderr)
            raise CliError(argv, f"{Path(self.exe).name} {argv[1]} failed: {detail}")
        return done


def _world_control_request(action: str, steps: int, scope: str) -> str:
    if action == "pause":
        return "pause: true"
    if action == "play":
        return "pause: false"
    if action == "step":
        if not isinstance(steps, int) or not 1 <= steps <= 10_000:
            raise ValueError("steps must be 1..10000")
        # Recorded: gz-sim steps only while paused, so the request pauses first.
        return f"pause: true multi_step: {steps}"
    if action == "reset":
        if scope not in RESET_SCOPES:
            raise ValueError(f"reset scope must be one of {RESET_SCOPES}")
        return f"reset {{ {_RESET_FIELDS[scope]}: true }}"
    raise ValueError(f"unknown control action {action!r}")


def _json_object_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _joint_samples_from_message(
    message: dict[str, Any], wanted: set[str] | None, paused: bool
) -> list[JointSample]:
    stamp = (message.get("header") or {}).get("stamp") or {}
    try:
        sim_time: float | None = int(stamp.get("sec", 0)) + int(stamp.get("nsec", 0)) / 1e9
    except (TypeError, ValueError):
        sim_time = None
    out: list[JointSample] = []
    for joint in message.get("joint") or []:
        if not isinstance(joint, dict):
            continue
        name, axis = joint.get("name"), joint.get("axis1")
        if (
            not isinstance(name, str)
            or not isinstance(axis, dict)
            or (wanted and name not in wanted)
        ):
            continue
        position = finite(axis.get("position", 0.0))
        if position is None:
            continue
        out.append(
            JointSample(
                joint=name,
                position=position,
                velocity=finite(axis.get("velocity")),
                sim_time_s=sim_time,
                paused=paused,
            )
        )
    return out
