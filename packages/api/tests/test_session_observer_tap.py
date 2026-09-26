import uuid
from unittest.mock import Mock

from test_sessions import FakeConn, _manager, _packet, _start


async def test_local_observer_is_session_owned_and_project_scoped():
    first, second = uuid.uuid4(), uuid.uuid4()
    instances = []

    def factory():
        observer = Mock()
        observer.add.return_value = [{"kind": "change_point"}]
        instances.append(observer)
        return observer

    sink = Mock()
    manager, _ = _manager(first, observer_factory=factory, event_sink=sink)
    left, right = FakeConn(), FakeConn()
    await _start(manager, first, left)
    await _start(manager, second, right)
    await left.drive(_packet("device", 0, value=1))
    assert len(instances) == 2
    instances[0].add.assert_called_once()
    instances[1].add.assert_not_called()
    sink.assert_called_once_with(first, {"kind": "change_point"})
    await manager.aclose_all()


async def test_observer_failure_does_not_drop_telemetry():
    project = uuid.uuid4()
    observer = Mock()
    observer.add.side_effect = ValueError("bad sample")
    manager, plumbing = _manager(project, observer_factory=lambda: observer, event_sink=Mock())
    conn = FakeConn()
    await _start(manager, project, conn)
    await conn.drive(_packet("device", 0, value=1))
    assert (await plumbing.get_device_recent(project, "device")).signals
    await manager.aclose_all()
