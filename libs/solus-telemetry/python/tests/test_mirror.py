"""Explicit adapters preserve control semantics and isolate a bounded telemetry sink."""

import json
import threading
import time
from collections.abc import Callable, Mapping

import pytest
from solus_telemetry.mirror import MethodAdapter, MirrorConfig, mirror


class Robot:
    def read(self) -> dict[str, float]:
        return {"position": 2.0}

    def write(self, command: Mapping[str, object]) -> Mapping[str, object]:
        return command


def config(*, capacity: int = 128) -> MirrorConfig:
    return MirrorConfig(
        device_id="ethernet:127.0.0.1",
        port=14550,
        methods=(
            MethodAdapter("read", {"joint.position": "position"}),
            MethodAdapter("write", {"joint.command": "position"}, argument=0),
        ),
        units={"joint.position": "rad", "joint.command": "rad"},
        capacity=capacity,
    )


def wait_for(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.001)


def test_completed_calls_keep_identity_and_restore() -> None:
    robot = Robot()
    lines: list[bytes] = []
    handle = mirror(robot, config=config(), sink=lines.append)
    command = {"position": 3.0}
    assert robot.write(command) is command
    assert robot.read() == {"position": 2.0}
    wait_for(lambda: len(lines) == 2)
    handle.close()
    packets = [json.loads(line) for line in lines]
    assert packets[0]["values"] == {"joint.command": 3.0}
    assert packets[1]["units"] == {"joint.position": "rad"}
    assert [packet["seq"] for packet in packets] == [0, 1]
    assert "read" not in vars(robot)
    assert handle.counters.sent == 2


def test_sink_block_overflow_and_close_never_block_control() -> None:
    release, entered = threading.Event(), threading.Event()

    def blocked(line: bytes) -> None:
        entered.set()
        release.wait(2)

    robot = Robot()
    handle = mirror(robot, config=config(capacity=1), sink=blocked)
    robot.read()
    assert entered.wait(1)
    for _ in range(10):
        robot.read()
    assert handle.counters.dropped >= 9
    start = time.monotonic()
    handle.close()
    assert time.monotonic() - start < 0.2
    release.set()


def test_failures_and_foreign_wrapper_are_preserved() -> None:
    robot = Robot()

    def fail(line: bytes) -> None:
        raise OSError("offline")

    handle = mirror(robot, config=config(), sink=fail)
    robot.read()
    wait_for(lambda: handle.counters.errors == 1)

    def other() -> dict[str, float]:
        return {"position": 9.0}

    robot.read = other  # type: ignore[method-assign]
    handle.close()
    assert robot.read is other


def test_control_exception_is_original_and_not_emitted() -> None:
    robot = Robot()
    error = RuntimeError("hardware failed")

    def fail() -> dict[str, float]:
        raise error

    robot.read = fail  # type: ignore[method-assign]
    lines: list[bytes] = []
    handle = mirror(robot, config=config(), sink=lines.append)
    with pytest.raises(RuntimeError) as caught:
        robot.read()
    assert caught.value is error
    handle.close()
    assert lines == []


def test_bad_observations_drop_without_changing_result() -> None:
    robot = Robot()
    handle = mirror(robot, config=config(), sink=lambda _: None)
    for value in (float("nan"), True, "bad"):
        command = {"position": value}
        assert robot.write(command) is command
    assert handle.counters.dropped == 3
    handle.close()


def test_unknown_method_and_bad_config_do_not_instrument() -> None:
    robot = Robot()
    with pytest.raises(ValueError):
        mirror(
            robot,
            config=MirrorConfig(
                device_id="x", port=1, methods=(MethodAdapter("absent", {"a": "a"}),)
            ),
        )
    assert vars(robot) == {}
    with pytest.raises(ValueError):
        config(capacity=0)


def test_keyword_commands_missing_keys_and_double_install() -> None:
    class KeywordRobot:
        def write(self, *, command: dict[str, float]) -> dict[str, float]:
            return command

    robot = KeywordRobot()
    selected = MirrorConfig(
        device_id="local",
        port=1234,
        methods=(MethodAdapter("write", {"a": "position"}, argument="command"),),
    )
    lines: list[bytes] = []
    handle = mirror(robot, config=selected, sink=lines.append)
    with pytest.raises(ValueError, match="already mirrored"):
        mirror(robot, config=selected)
    assert robot.write(command={}) == {}
    assert handle.counters.dropped == 1
    robot.write(command={"position": 2.0})
    wait_for(lambda: len(lines) == 1)
    handle.close()
    handle.close()


@pytest.mark.parametrize("argument", [-1, 65, True, "bad key"])
def test_bad_argument_selection(argument: int | str) -> None:
    with pytest.raises(ValueError):
        MethodAdapter("read", {"a": "a"}, argument=argument)


def test_invalid_method_names_signals_and_config() -> None:
    with pytest.raises(ValueError):
        MethodAdapter("_read", {"a": "a"})
    with pytest.raises(ValueError):
        MethodAdapter("read", {})
    with pytest.raises(ValueError):
        MethodAdapter("read", {"a": ""})
    with pytest.raises(ValueError):
        MirrorConfig(device_id="x", port=0, methods=())
    with pytest.raises(ValueError):
        MirrorConfig(device_id="x", port=1, methods=())
    method = MethodAdapter("read", {"a": "a"})
    with pytest.raises(ValueError):
        MirrorConfig(device_id="x", port=1, methods=(method, method))
    with pytest.raises(ValueError):
        mirror(object(), config=config())


def test_rejects_async_and_restores_preexisting_method() -> None:
    robot = Robot()

    async def asynchronous() -> dict[str, float]:
        return {}

    robot.read = asynchronous  # type: ignore[method-assign, assignment]
    with pytest.raises(ValueError, match="synchronous"):
        mirror(robot, config=config())

    def custom() -> dict[str, float]:
        return {"position": 4.0}

    robot.read = custom  # type: ignore[method-assign]
    handle = mirror(robot, config=config(), sink=lambda _: None)
    handle.close()
    assert robot.read is custom


def test_thread_start_failure_restores_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_start(self: threading.Thread) -> None:
        raise RuntimeError("cannot start thread")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    robot = Robot()
    with pytest.raises(RuntimeError, match="cannot start"):
        mirror(robot, config=config())
    assert vars(robot) == {}


def test_non_dictionary_result_is_returned_unchanged() -> None:
    value = [1.0]

    class ListRobot:
        def read(self) -> list[float]:
            return value

    robot = ListRobot()
    handle = mirror(
        robot,
        config=MirrorConfig(
            device_id="local", port=1234, methods=(MethodAdapter("read", {"a": "a"}),)
        ),
        sink=lambda _: None,
    )
    assert robot.read() is value
    assert handle.counters.dropped == 1
    handle.close()
