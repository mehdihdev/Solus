"""A persisted API identity is usable only while this process owns its lifetime lock."""

import asyncio
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from solus_api.hardware.runtime_owner import RuntimeOwner, RuntimeOwnershipError


async def test_shutdown_drains_pending_identity_acquisition(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from solus_api.hardware.connections import HardwareConnections
    from sqlalchemy.ext.asyncio import async_sessionmaker

    owner = RuntimeOwner(home=tmp_path, location=tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = owner.acquire

    def blocked() -> str:
        entered.set()
        release.wait()
        return original()

    monkeypatch.setattr(owner, "acquire", blocked)
    coordinator = HardwareConnections(
        sessions=async_sessionmaker(),
        manager=cast(Any, SimpleNamespace(on_ended=None)),
        local=object(),
        hub=cast(Any, None),
        owner=owner,
    )
    pending = asyncio.create_task(coordinator.ensure_owner())
    await asyncio.to_thread(entered.wait)
    pending.cancel()
    closing = asyncio.create_task(coordinator.aclose())
    await asyncio.sleep(0)
    try:
        assert not closing.done()
    finally:
        release.set()
        await asyncio.gather(pending, closing, return_exceptions=True)
    try:
        assert owner.identity is None
    finally:
        owner.close()


def test_same_scope_excludes_simultaneous_owner_and_reuses_identity(tmp_path: Path) -> None:
    first = RuntimeOwner(home=tmp_path, location=tmp_path / "checkout")
    second = RuntimeOwner(home=tmp_path, location=tmp_path / "checkout")
    try:
        identity = first.acquire()
        assert str(uuid.UUID(identity)) == identity
        with pytest.raises(RuntimeOwnershipError):
            second.acquire()
        first.close()
        assert second.acquire() == identity
    finally:
        first.close()
        second.close()


def test_distinct_checkout_locations_have_distinct_owners(tmp_path: Path) -> None:
    first = RuntimeOwner(home=tmp_path, location=tmp_path / "one")
    second = RuntimeOwner(home=tmp_path, location=tmp_path / "two")
    try:
        assert first.acquire() != second.acquire()
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("fault", ["malformed", "oversize", "symlink"])
def test_existing_invalid_owner_is_never_followed_or_replaced(tmp_path: Path, fault: str) -> None:
    owner = RuntimeOwner(home=tmp_path, location=tmp_path / "checkout")
    owner.acquire()
    owner.close()
    path = owner.path
    assert path is not None
    if fault == "symlink":
        target = tmp_path / "private-target"
        target.write_text("untouched")
        path.unlink()
        path.symlink_to(target)
    else:
        path.write_text("invalid" if fault == "malformed" else "x" * 1024)
    before = path.read_bytes()
    with pytest.raises(RuntimeOwnershipError):
        owner.acquire()
    assert path.read_bytes() == before
    owner.close()
