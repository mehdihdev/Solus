"""Native tests use a disposable runtime fixture, never a developer install.

SOLUSDEV-322 P4-T1 adds the stage-mode doubles every new action is tested against: `FakeScene`
(a deterministic stand-in for `NativeScene`, recording calls) and `fake_worker` (a controlled
in-process child speaking the private pipe protocol through the REAL `serve_frames` and the
REAL `ActionEngine`, so a tool call round-trips a frame without Isaac).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))

if TYPE_CHECKING:
    pass

ARM = "/World/arm"
IMU = "/World/arm/imu"
CONTACT = "/World/arm/tip/contact"
CAMERA = "/World/cam"

#: What the `children` fixture yields: (created children, mode, killpg signals).
Children = tuple[list["Child"], dict[str, Any], list[int]]


@pytest.fixture(autouse=True)
def configured_runtime_fixture(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path_factory.mktemp("isaac-runtime-fixture")
    for name in (
        "python.sh",
        "setup_python_env.sh",
        "VERSION",
        "kit/python/bin/python3",
        "apps/isaacsim.exp.base.python.kit",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    monkeypatch.setenv("SOLUS_ISAAC_RUNTIME", str(root))
    monkeypatch.delenv("SOLUS_SIM_ROOTS", raising=False)


def _dof(position: float, lower: float = -1.57, upper: float = 1.57) -> dict[str, float]:
    return {"position_rad": position, "velocity_rad_s": 0.0, "lower_rad": lower, "upper_rad": upper}


class FakeScene:
    """Stage-mode double for `NativeScene`: one stage, one articulation, three sensors."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.stage: str | None = None
        self.paused = False
        self.articulations: dict[str, dict[str, Any]] = {}
        self.sensors: dict[str, dict[str, Any]] = {
            IMU: {
                "kind": "imu",
                "lin_acc_m_s2": [0.0, 0.0, 9.81],
                "ang_vel_rad_s": [0.0, 0.0, 0.0],
            },
            CONTACT: {"kind": "contact", "in_contact": False, "force_n": 0.0},
        }
        self.camera_path: str | None = CAMERA

    # --- graph-bound surface (unchanged) ---------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {"loaded": False, "stage": self.stage, "paused": self.paused}

    def invalidate_loaded_state(self) -> None:
        self.calls.append(("invalidated",))

    def load(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("load",))
        return {"loaded": True}

    # --- stage-mode surface -------------------------------------------------------------------
    def open_stage(self, path: str) -> dict[str, Any]:
        self.calls.append(("open_stage", path))
        self.stage = Path(path).name
        self.articulations = {
            ARM: {"name": "arm", "dofs": {"shoulder": _dof(0.0), "elbow": _dof(0.1)}}
        }
        return {"stage": self.stage, "prims": 12, "articulations": list(self.articulations)}

    def find_articulations(self) -> list[dict[str, Any]]:
        self.calls.append(("find_articulations",))
        return [
            {"path": path, "name": a["name"], "dofs": list(a["dofs"])}
            for path, a in self.articulations.items()
        ]

    def articulation_state(self, path: str) -> dict[str, Any]:
        if path not in self.articulations:
            raise ValueError("articulation unavailable")
        return {"path": path, "dofs": copy.deepcopy(self.articulations[path]["dofs"])}

    def sensor_readings(self, paths: list[str]) -> list[dict[str, Any]]:
        unknown = [p for p in paths if p not in self.sensors]
        if unknown:
            raise ValueError("sensor unavailable")
        return [{"path": p, **copy.deepcopy(self.sensors[p])} for p in paths]

    def camera_frame(self) -> dict[str, Any] | None:
        if self.camera_path is None:
            return None
        pixels = bytes([0, 64, 128, 255])
        return {
            "path": self.camera_path,
            "width": 2,
            "height": 2,
            "frame_png_b64": base64.b64encode(pixels).decode(),
            "frame_sha256": hashlib.sha256(pixels).hexdigest(),
        }

    def spawn_at(
        self, model_file: Path, name: str, xyz: list[float], rpy: list[float]
    ) -> dict[str, Any]:
        self.calls.append(("spawn_at", model_file.name, name, list(xyz), list(rpy)))
        path = f"/World/{name}"
        self.articulations[path] = {
            "name": name,
            "dofs": {"shoulder": _dof(0.0), "elbow": _dof(0.0)},
        }
        return {"prim_path": path, "dofs": ["shoulder", "elbow"]}

    def control(self, action: str, steps: int) -> dict[str, Any]:
        self.calls.append(("control", action, steps))
        self.paused = action in ("pause", "step")
        return {"action": action, "steps": steps, "paused": self.paused}

    def run_sweep(
        self, path: str, joint: str, targets: list[float], cancelled: Any
    ) -> dict[str, Any]:
        self.calls.append(("run_sweep", path, joint, len(targets)))
        dof = self.articulations[path]["dofs"][joint]
        dof["position_rad"] = targets[-1]
        return {
            "steps": len(targets),
            "final_position_rad": targets[-1],
            "min_rad": min(targets),
            "max_rad": max(targets),
        }

    def export_stage(self, dest: Path) -> dict[str, Any]:
        self.calls.append(("export_stage", dest.name))
        data = f'#usda 1.0\n(doc = "{self.stage}")\n'.encode()
        dest.write_bytes(data)
        return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class Child:
    """A controlled in-process child for `Controller._spawn`: speaks the private pipe protocol
    over the real descriptors through the REAL `serve_frames`."""

    def __init__(
        self, created: list[Child], mode: dict[str, Any], argv: list[str], **kwargs: Any
    ) -> None:
        from integrations.mcp.isaac.solus.worker import serve_frames

        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        assert set(kwargs["env"]) == {"HOME", "PATH", "LANG", "TMPDIR"}
        assert argv[1].endswith("/solus/worker.py")
        self.pid = 43210 + len(created)
        self.finished = threading.Event()
        self.stop_event = threading.Event()
        self.ignore_term = False
        self.stdout = io.BytesIO(b"x" * 16384 + b"bounded-tail")
        request = os.dup(int(argv[2]))
        reply = os.dup(int(argv[3]))
        generation = argv[4]
        workspace_fd = os.dup(int(argv[5]))
        engine = mode["engine"](workspace_fd, Path(kwargs["cwd"]), generation)

        def run() -> None:
            with (
                os.fdopen(request, "rb", buffering=0) as reader,
                os.fdopen(reply, "wb", buffering=0) as writer,
            ):
                try:
                    if mode["value"] == "eof":
                        return
                    if mode["value"] == "hang":
                        self.stop_event.wait(3)
                        return
                    if mode["value"] == "bad_ready":
                        writer.write(b'{"ready":true,"generation":"foreign"}\n')
                        self.stop_event.wait(3)
                        return
                    serve_frames(reader, writer, generation, engine)
                finally:
                    os.close(workspace_fd)
                    self.finished.set()

        self.thread = threading.Thread(target=run, daemon=True)
        created.append(self)
        self.thread.start()

    def poll(self) -> int | None:
        return 0 if self.finished.is_set() else None

    def wait(self, timeout: float) -> int:
        if self.ignore_term and not self.stop_event.is_set():
            raise subprocess.TimeoutExpired("owned worker", timeout)
        if not self.finished.wait(timeout):
            raise subprocess.TimeoutExpired("owned worker", timeout)
        return 0


class RefusingEngine:
    """The lifecycle tests' engine: status answers, every action is refused."""

    generation = 0

    def status(self) -> dict[str, Any]:
        return {"loaded": False}

    def dispatch(self, *args: Any) -> dict[str, Any]:
        raise ValueError("refused")


@pytest.fixture
def children(monkeypatch: pytest.MonkeyPatch) -> Iterator[Children]:
    """(created children, mode, killpg signals). `mode["engine"]` builds the child's engine from
    `(workspace_fd, private_dir, generation)`; the default refuses every action."""
    import signal

    created: list[Child] = []
    mode: dict[str, Any] = {"value": "normal", "engine": lambda *args: RefusingEngine()}
    signals: list[int] = []

    def child_factory(argv: list[str], **kwargs: Any) -> Child:
        return Child(created, mode, argv, **kwargs)

    def kill(pid: int, sig: int) -> None:
        assert created and pid == created[-1].pid
        signals.append(sig)
        if sig == signal.SIGTERM and created[-1].ignore_term:
            return
        created[-1].stop_event.set()
        created[-1].finished.set()

    monkeypatch.setattr(subprocess, "Popen", child_factory)
    monkeypatch.setattr(os, "killpg", kill)
    yield created, mode, signals
    for child in created:
        child.stop_event.set()
        child.thread.join(timeout=1)


@pytest.fixture
def fake_worker(children: Children) -> list[FakeScene]:
    """A child running the REAL `ActionEngine` over a `FakeScene`; returns the scenes created."""
    from integrations.mcp.isaac.solus.actions import ActionEngine

    created, mode, signals = children
    scenes: list[FakeScene] = []

    def engine(workspace_fd: int, private_dir: Path, generation: str) -> ActionEngine:
        scene = FakeScene()
        scenes.append(scene)
        return ActionEngine(scene, Path(f"/proc/self/fd/{workspace_fd}"), private_dir)

    mode["engine"] = engine
    return scenes
