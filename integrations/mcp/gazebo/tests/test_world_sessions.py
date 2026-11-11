"""One owned simulator per fork process, any number of attached (user-started) worlds.
Owned processes are the ONLY thing `stop`/`close` ever signal, by process group, through the
Popen handle this registry holds. Lifecycle runs against a fake Popen (as
isaac/tests/test_controller_lifecycle.py) and the gz8 fixture CLI — no simulator starts."""

from __future__ import annotations

import signal
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from integrations.mcp.gazebo.solus.adapters import adapter_for
from integrations.mcp.gazebo.solus.adapters.adapter_base import Adapter, CliError
from integrations.mcp.gazebo.solus.family_detect import Family
from integrations.mcp.gazebo.solus.world_sessions import (
    SessionRefusedError,
    WorldSessions,
    is_attached_id,
)
from integrations.mcp.gazebo.tests.conftest import Children

cold = pytest.mark.usefixtures("cold_simulator")


@pytest.fixture
def gz_adapter(fixture_family: Callable[[str], Family], tmp_path: Path) -> Adapter:
    return adapter_for(fixture_family("gz8"), home=tmp_path / "home")


@pytest.fixture
def world_file(tmp_path: Path) -> Path:
    path = tmp_path / "empty.sdf"
    path.write_text('<sdf version="1.10"><world name="empty"/></sdf>')
    return path


def _registry_with_fake_clock() -> tuple[WorldSessions, list[float]]:
    now = [0.0]

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    return WorldSessions(clock=clock, sleep=sleep), now


def _open(registry: WorldSessions, adapter: Adapter, path: Path, world: str = "empty") -> Any:
    return registry.open_world(adapter, path, world=world, world_ref=path.name, gui=False)


@cold
def test_open_world_owns_the_process_and_stop_signals_its_group_only(
    fake_children: Children, gz_adapter: Adapter, world_file: Path
) -> None:
    created, signals = fake_children
    registry, _ = _registry_with_fake_clock()
    session = _open(registry, gz_adapter, world_file)
    assert session.owned and session.world == "empty" and session.world_ref == "empty.sdf"
    assert not is_attached_id(session.session_id)
    assert len(created) == 1
    assert Path(created[0].argv[0]).parent == gz_adapter.family.bin_dir
    assert created[0].argv[1:] == ["sim", "-s", "-r", str(world_file)]
    assert registry.get(session.session_id) is session
    assert registry.owned_alive() is session
    assert signals == []
    registry.stop(session.session_id)
    assert signals == [(created[0].pid, signal.SIGTERM)]
    assert registry.owned_alive() is None
    with pytest.raises(SessionRefusedError) as refused:
        registry.get(session.session_id)
    assert refused.value.code == "session_unavailable"


@cold
def test_open_world_twice_is_busy(
    fake_children: Children, gz_adapter: Adapter, world_file: Path
) -> None:
    created, _ = fake_children
    registry, _ = _registry_with_fake_clock()
    _open(registry, gz_adapter, world_file)
    with pytest.raises(SessionRefusedError) as refused:
        _open(registry, gz_adapter, world_file)
    assert refused.value.code == "busy"
    assert len(created) == 1, "a second simulator was started"


def test_stop_refuses_attached_session(fake_children: Children, gz_adapter: Adapter) -> None:
    _, signals = fake_children
    registry, _ = _registry_with_fake_clock()
    attached = registry.attach(gz_adapter, "empty")
    assert not attached.owned and attached.process is None
    with pytest.raises(SessionRefusedError) as refused:
        registry.stop(attached.session_id)
    assert refused.value.code == "not_owned"
    assert registry.get(attached.session_id) is attached, "the attached session survives"
    assert signals == []


def test_open_world_refuses_a_name_the_user_is_already_running(
    fake_children: Children, gz_adapter: Adapter, world_file: Path
) -> None:
    """A user-started `empty` must never be re-labelled as Solus-owned (no card would follow)."""
    created, _ = fake_children
    registry, _ = _registry_with_fake_clock()
    attached = registry.attach(gz_adapter, "empty")
    with pytest.raises(SessionRefusedError) as refused:
        _open(registry, gz_adapter, world_file)
    assert refused.value.code == "world_already_running"
    assert "attach" in refused.value.reason
    assert created == [], "adapter.start was called"
    assert registry.owned_alive() is None and registry.all() == [attached]


def test_attach_requires_a_running_world(gz_adapter: Adapter) -> None:
    registry, _ = _registry_with_fake_clock()
    with pytest.raises(SessionRefusedError) as refused:
        registry.attach(gz_adapter, "nowhere")
    assert refused.value.code == "world_not_running"


@cold
def test_attached_ids_never_collide_with_owned(
    fake_children: Children, gz_adapter: Adapter, world_file: Path
) -> None:
    registry, _ = _registry_with_fake_clock()
    owned = _open(registry, gz_adapter, world_file)
    attached_ids = {registry.attach(gz_adapter, "empty").session_id for _ in range(20)}
    assert len(attached_ids) == 20
    assert all(is_attached_id(i) for i in attached_ids)
    assert not is_attached_id(owned.session_id)
    assert owned.session_id not in attached_ids
    assert len(registry.all()) == 21


@cold
def test_close_kills_only_owned_process_groups(
    fake_children: Children, gz_adapter: Adapter, world_file: Path
) -> None:
    created, signals = fake_children
    registry, _ = _registry_with_fake_clock()
    owned = _open(registry, gz_adapter, world_file)
    registry.attach(gz_adapter, "empty")
    registry.attach(gz_adapter, "empty")
    registry.close()
    assert signals == [(created[0].pid, signal.SIGTERM)]
    assert registry.all() == [] and registry.owned_alive() is None
    with pytest.raises(SessionRefusedError):
        registry.get(owned.session_id)


@cold
def test_unresponsive_owned_process_gets_a_bounded_sigkill(
    fake_children: Children, gz_adapter: Adapter, world_file: Path
) -> None:
    created, signals = fake_children
    registry, _ = _registry_with_fake_clock()
    session = _open(registry, gz_adapter, world_file)
    created[0].ignore_term = True
    registry.stop(session.session_id)
    assert signals == [(created[0].pid, signal.SIGTERM), (created[0].pid, signal.SIGKILL)]


def test_dead_owned_process_is_reconciled_and_frees_the_slot(
    fake_children: Children,
    gz_adapter: Adapter,
    world_file: Path,
    cold_simulator: Callable[[], None],
) -> None:
    created, signals = fake_children
    registry, _ = _registry_with_fake_clock()
    first = _open(registry, gz_adapter, world_file)
    created[0].exit_code = 1  # the simulator crashed on its own
    cold_simulator()  # ...and took its world with it
    assert registry.owned_alive() is None
    with pytest.raises(SessionRefusedError) as refused:
        registry.get(first.session_id)
    assert refused.value.code == "session_unavailable"
    second = _open(registry, gz_adapter, world_file)
    assert second.session_id != first.session_id and len(created) == 2
    assert signals == []  # a dead process is never signalled


def test_open_world_kills_the_process_when_the_world_never_comes_up(
    fake_children: Children, gz_adapter: Adapter, tmp_path: Path
) -> None:
    created, signals = fake_children
    registry, now = _registry_with_fake_clock()
    path = tmp_path / "other.sdf"
    path.write_text("<sdf/>")
    with pytest.raises(CliError, match="did not come up"):
        _open(registry, gz_adapter, path, world="other")
    assert now[0] >= WorldSessions.READY_TIMEOUT_S
    assert signals == [(created[0].pid, signal.SIGTERM)]
    assert registry.owned_alive() is None and registry.all() == []


def test_open_world_reports_a_process_that_exits_early(
    fake_children: Children, gz_adapter: Adapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created, signals = fake_children
    registry, _ = _registry_with_fake_clock()
    path = tmp_path / "other.sdf"
    path.write_text("<sdf/>")
    original = subprocess.Popen

    def dying(argv: list[str], **kwargs: Any) -> Any:
        child = original(argv, **kwargs)
        child.exit_code = 255  # type: ignore[attr-defined]
        return child

    monkeypatch.setattr(subprocess, "Popen", dying)
    with pytest.raises(CliError, match="exited"):
        _open(registry, gz_adapter, path, world="other")
    assert signals == [] and len(created) == 1
    assert registry.all() == []


def test_open_world_fails_closed_when_running_worlds_cannot_be_listed(
    gz_adapter: Adapter, world_file: Path
) -> None:
    """A transport error is NOT "nothing running": Solus cannot prove the world is free, so it
    refuses rather than risk re-labelling a user's world as owned."""
    started: list[Path] = []

    class Blind:
        family = gz_adapter.family

        def running_worlds(self) -> list[str]:
            raise CliError(["gz", "topic", "-l"], "transport down")

        def start(self, world_file: Path, *, gui: bool) -> subprocess.Popen[bytes]:
            started.append(world_file)
            raise AssertionError("start must never run")

    registry, _ = _registry_with_fake_clock()
    with pytest.raises(SessionRefusedError) as refused:
        _open(registry, Blind(), world_file)  # type: ignore[arg-type]
    assert refused.value.code == "transport_unavailable"
    assert "retry or attach" in refused.value.reason
    assert started == [] and registry.all() == []
