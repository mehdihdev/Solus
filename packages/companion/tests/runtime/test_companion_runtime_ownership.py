"""Owner-only directories — mcp-fork-runtime.md §5 (POSIX real, Windows by fakes)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from solus_companion.runtime.errors import RuntimeSetupError
from solus_companion.runtime.ownership import (
    FILE_ALL_ACCESS,
    SYSTEM_SID,
    Ace,
    AclSnapshot,
    PosixOwnerOnly,
    WindowsOwnerOnly,
    owner_only_for,
    snapshot_is_owner_only,
)

USER = "S-1-5-21-1-2-3-1001"


def _dir(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    return path


def test_private_dir_owned_by_me_is_owner_only(tmp_path: Path) -> None:
    assert PosixOwnerOnly().check(_dir(tmp_path / "envs"))


@pytest.mark.parametrize("mode", [0o750, 0o770, 0o705, 0o701, 0o720])
def test_any_group_or_other_bit_is_refused(tmp_path: Path, mode: int) -> None:
    assert not PosixOwnerOnly().check(_dir(tmp_path / "envs", mode))


def test_wrong_owner_is_refused(tmp_path: Path) -> None:
    other = PosixOwnerOnly(euid=lambda: os.geteuid() + 1)
    assert not other.check(_dir(tmp_path / "envs"))


def test_a_symlinked_dir_is_refused_even_if_the_target_is_private(tmp_path: Path) -> None:
    target = _dir(tmp_path / "real")
    link = tmp_path / "envs"
    link.symlink_to(target, target_is_directory=True)
    assert not PosixOwnerOnly().check(link)


def test_missing_or_file_is_refused(tmp_path: Path) -> None:
    assert not PosixOwnerOnly().check(tmp_path / "absent")
    file = tmp_path / "file"
    file.write_text("x")
    os.chmod(file, 0o600)
    assert not PosixOwnerOnly().check(file)


def test_ensure_creates_0700_and_tightens_an_existing_dir(tmp_path: Path) -> None:
    policy = PosixOwnerOnly()
    created = tmp_path / "data" / "mcp-envs"
    policy.ensure(created)
    assert created.stat().st_mode & 0o777 == 0o700
    loose = _dir(tmp_path / "loose", 0o755)
    policy.ensure(loose)
    assert policy.check(loose)


def test_ensure_refuses_a_symlink_or_foreign_dir(tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(_dir(tmp_path / "real"), target_is_directory=True)
    with pytest.raises(RuntimeSetupError) as caught:
        PosixOwnerOnly().ensure(link)
    assert caught.value.code == "not_owner_only"
    with pytest.raises(RuntimeSetupError):
        PosixOwnerOnly(euid=lambda: os.geteuid() + 1).ensure(_dir(tmp_path / "theirs"))


# ---------------------------------------------------------------- Windows logic


def _snapshot(**overrides: object) -> AclSnapshot:
    base: dict[str, object] = {
        "owner_sid": USER,
        "protected": True,
        "aces": (
            Ace(kind="allow", sid=USER, mask=FILE_ALL_ACCESS),
            Ace(kind="allow", sid=SYSTEM_SID, mask=FILE_ALL_ACCESS),
        ),
    }
    base.update(overrides)
    return AclSnapshot(**base)  # type: ignore[arg-type]


def test_exact_two_ace_protected_dacl_is_owner_only() -> None:
    assert snapshot_is_owner_only(_snapshot(), USER)


@pytest.mark.parametrize(
    "overrides",
    [
        {"owner_sid": "S-1-5-32-544"},
        {"protected": False},
        {"aces": (Ace(kind="allow", sid=USER, mask=FILE_ALL_ACCESS),)},
        {
            "aces": (
                Ace(kind="allow", sid=USER, mask=FILE_ALL_ACCESS),
                Ace(kind="allow", sid=SYSTEM_SID, mask=FILE_ALL_ACCESS),
                Ace(kind="allow", sid="S-1-1-0", mask=0x120089),
            )
        },
        {
            "aces": (
                Ace(kind="allow", sid=USER, mask=FILE_ALL_ACCESS),
                Ace(kind="deny", sid=SYSTEM_SID, mask=FILE_ALL_ACCESS),
            )
        },
        {
            "aces": (
                Ace(kind="allow", sid=USER, mask=0x120089),
                Ace(kind="allow", sid=SYSTEM_SID, mask=FILE_ALL_ACCESS),
            )
        },
        {
            "aces": (
                Ace(kind="allow", sid=USER, mask=FILE_ALL_ACCESS),
                Ace(kind="allow", sid="S-1-5-32-545", mask=FILE_ALL_ACCESS),
            )
        },
    ],
)
def test_any_other_dacl_is_refused(overrides: dict[str, object]) -> None:
    assert not snapshot_is_owner_only(_snapshot(**overrides), USER)


class _FakeAcl:
    def __init__(self, snapshot: AclSnapshot | None) -> None:
        self.snapshot = snapshot
        self.applied: list[tuple[Path, str]] = []

    def current_user_sid(self) -> str:
        return USER

    def read(self, path: Path) -> AclSnapshot | None:
        return self.snapshot

    def apply(self, path: Path, user_sid: str) -> None:
        self.applied.append((path, user_sid))
        self.snapshot = _snapshot()


def test_windows_policy_checks_through_the_backend(tmp_path: Path) -> None:
    assert WindowsOwnerOnly(_FakeAcl(_snapshot())).check(tmp_path)
    assert not WindowsOwnerOnly(_FakeAcl(None)).check(tmp_path)
    assert not WindowsOwnerOnly(_FakeAcl(_snapshot(protected=False))).check(tmp_path)


def test_windows_ensure_applies_the_exact_dacl(tmp_path: Path) -> None:
    backend = _FakeAcl(_snapshot(protected=False))
    target = tmp_path / "mcp-envs"
    WindowsOwnerOnly(backend).ensure(target)
    assert target.is_dir()
    assert backend.applied == [(target, USER)]


def test_windows_ensure_fails_closed_when_the_dacl_does_not_stick(tmp_path: Path) -> None:
    class Stubborn(_FakeAcl):
        def apply(self, path: Path, user_sid: str) -> None:
            self.applied.append((path, user_sid))

    with pytest.raises(RuntimeSetupError):
        WindowsOwnerOnly(Stubborn(_snapshot(protected=False))).ensure(tmp_path / "x")


def test_policy_factory_picks_by_platform() -> None:
    assert isinstance(owner_only_for("darwin"), PosixOwnerOnly)
    assert isinstance(owner_only_for("linux"), PosixOwnerOnly)
