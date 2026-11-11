"""Fork tests import `integrations.mcp.gazebo.solus.*` from the repo root and
never see the developer's simulator installs: every test starts with
`SOLUS_GAZEBO_PATH` and `SOLUS_SIM_ROOTS` unset and PATH pinned."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from integrations.mcp.gazebo.solus.family_detect import Family  # noqa: E402

FIXTURE_BINS = Path(__file__).resolve().parent / "fixtures" / "bin"
#: Setting GZ_PARTITION to this makes every fixture CLI replay a paused world (see replay_lib).
PAUSED_PARTITION = "solus-fixture-paused"
#: The classic11 fixture prints `angle: nan` / `angle: inf` under this partition.
NONFINITE_PARTITION = "solus-fixture-nonfinite"
#: Every fixture CLI lists NO running world under this partition (no server up yet).
IDLE_PARTITION = "solus-fixture-idle"
_FIXTURE_FAMILIES = {
    "gz8": ("gz", "8.15.0", "gz"),
    "ign6": ("ignition", "6.16.0", "ign"),
    "classic11": ("classic", "11.15.1", "gzserver"),
}


@pytest.fixture(autouse=True)
def scrubbed_simulator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLUS_GAZEBO_PATH", raising=False)
    monkeypatch.delenv("SOLUS_SIM_ROOTS", raising=False)
    monkeypatch.delenv("GZ_PARTITION", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")


@pytest.fixture
def fixture_bins() -> Path:
    return FIXTURE_BINS


@pytest.fixture
def fixture_family() -> Callable[[str], Family]:
    """`Family` rows pointing at the fixture CLIs, as `detect_families` would build them."""

    def build(name: str) -> Family:
        family, version, exe = _FIXTURE_FAMILIES[name]
        bin_dir = FIXTURE_BINS / name
        return Family(name=family, version=version, bin_dir=bin_dir, exe=bin_dir / exe)  # type: ignore[arg-type]

    return build


class FakePopen:
    """A stand-in for the simulator process `spawn_process` starts: records the argv and the
    Popen keywords, is 'alive' until `os.killpg` (also faked) reaches its pid."""

    def __init__(self, created: list[FakePopen], argv: list[str], **kwargs: Any) -> None:
        assert kwargs["start_new_session"] is True
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"]["PATH"] == "/usr/bin:/bin" and "HOME" in kwargs["env"]
        assert "SOLUS_MCP_WORKSPACE" not in kwargs["env"]
        self.argv = argv
        self.pid = 40000 + len(created)
        self.exit_code: int | None = None
        self.ignore_term = False
        created.append(self)

    def poll(self) -> int | None:
        return self.exit_code

    def wait(self, timeout: float | None = None) -> int:
        if self.exit_code is None:
            raise subprocess.TimeoutExpired("owned simulator", timeout or 0)
        return self.exit_code


Children = tuple[list[FakePopen], list[tuple[int, int]]]


@pytest.fixture
def fake_children(monkeypatch: pytest.MonkeyPatch) -> Children:
    """(created processes, killpg signals). `subprocess.run` on a fixture CLI stays real."""
    created: list[FakePopen] = []
    signals: list[tuple[int, int]] = []
    real_popen = subprocess.Popen

    def factory(argv: list[str], **kwargs: Any) -> Any:
        if "start_new_session" not in kwargs:
            return real_popen(argv, **kwargs)
        if os.environ.get("GZ_PARTITION") == IDLE_PARTITION:
            monkeypatch.delenv("GZ_PARTITION")  # the owned server came up: its world is listed
        return FakePopen(created, argv, **kwargs)

    def killpg(pgid: int, sig: int) -> None:
        signals.append((pgid, sig))
        child = next(c for c in created if c.pid == pgid)
        if sig == signal.SIGTERM and child.ignore_term:
            return
        child.exit_code = -sig

    monkeypatch.setattr(subprocess, "Popen", factory)
    monkeypatch.setattr(os, "killpg", killpg)
    return created, signals


@pytest.fixture
def cold_simulator(monkeypatch: pytest.MonkeyPatch, fake_children: Children) -> Callable[[], None]:
    """No world is running until `fake_children` starts the owned server (then the fixture CLIs
    list it). Call the returned function to go cold again, e.g. after that server dies."""

    def cold() -> None:
        monkeypatch.setenv("GZ_PARTITION", IDLE_PARTITION)

    cold()
    return cold
