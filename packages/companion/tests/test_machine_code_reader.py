"""The ungated saved-code reader must not become a generic private-file reader."""

import os
from pathlib import Path

import pytest
from solus_companion.machine import code_reader
from solus_companion.machine.actions import MachineActionError
from solus_companion.machine.server import MachineServer


def test_reads_saved_utf8_code(tmp_path: Path) -> None:
    (tmp_path / "robot.py").write_text("print('robot')\n")
    assert code_reader.read_code_file(tmp_path, "robot.py") == {
        "path": "robot.py",
        "content": "print('robot')\n",
        "encoding": "utf-8",
        "size_bytes": 15,
    }


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/tmp/robot.py",
        ".env",
        ".env.local",
        ".git/config",
        "nested/secrets.py",
        "credentials/config.json",
        "id_rsa",
        "a\\..\\secret.py",
        "nested/.env/config.py",
    ],
)
def test_refuses_sensitive_and_unconfined_paths_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    def unexpected(*args: object, **kwargs: object) -> int:
        raise AssertionError("unsafe path reached filesystem open")

    monkeypatch.setattr(os, "open", unexpected)
    with pytest.raises(MachineActionError):
        code_reader.read_code_file(tmp_path, path)


@pytest.mark.parametrize("folder", [False, True])
def test_refuses_even_in_workspace_symlinks(tmp_path: Path, folder: bool) -> None:
    private = tmp_path / "secrets"
    private.mkdir()
    (private / "real.py").write_text("private content")
    if folder:
        (tmp_path / "src").symlink_to(private, target_is_directory=True)
        path = "src/real.py"
    else:
        (tmp_path / "safe.py").symlink_to(private / "real.py")
        path = "safe.py"
    with pytest.raises(MachineActionError):
        code_reader.read_code_file(tmp_path, path)


@pytest.mark.parametrize("data", [b"\xff", b"abc\x00def", b"abc\x01def"])
def test_refuses_binary_content(tmp_path: Path, data: bytes) -> None:
    (tmp_path / "robot.py").write_bytes(data)
    with pytest.raises(MachineActionError):
        code_reader.read_code_file(tmp_path, "robot.py")


def test_actual_read_is_bounded_even_when_file_grows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "robot.py").write_bytes(b"a")
    monkeypatch.setattr(code_reader, "MAX_CODE_BYTES", 8)
    calls: list[int] = []

    def growing(fd: int, count: int) -> bytes:
        calls.append(count)
        return b"x" * count

    monkeypatch.setattr(os, "read", growing)
    with pytest.raises(MachineActionError):
        code_reader.read_code_file(tmp_path, "robot.py")
    assert sum(calls) == 9


async def test_server_registers_separate_read_only_code_capability(tmp_path: Path) -> None:
    (tmp_path / "robot.py").write_text("pass")
    server = MachineServer(tmp_path)
    inventory = server.inventory()
    assert inventory is not None
    assert "read_code_file" in {item["name"] for item in inventory["tools"]}
    result = await server.call_tool("read_code_file", {"path": "robot.py"})
    assert not result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["content"] == "pass"


def test_size_boundary_and_oversized_file(tmp_path: Path) -> None:
    target = tmp_path / "robot.py"
    target.write_bytes(b"x" * code_reader.MAX_CODE_BYTES)
    assert (
        code_reader.read_code_file(tmp_path, "robot.py")["size_bytes"] == code_reader.MAX_CODE_BYTES
    )
    target.write_bytes(b"x" * (code_reader.MAX_CODE_BYTES + 1))
    with pytest.raises(MachineActionError):
        code_reader.read_code_file(tmp_path, "robot.py")


def test_symlinked_workspace_root_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "robot.py").write_text("pass")
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(MachineActionError):
        code_reader.read_code_file(link, "robot.py")


def test_unsupported_platform_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "supports_dir_fd", set())
    with pytest.raises(MachineActionError, match="unavailable on this platform"):
        code_reader.read_code_file(tmp_path, "robot.py")


def test_fifo_cannot_block_reader(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe.py")
    with pytest.raises(MachineActionError, match="regular file"):
        code_reader.read_code_file(tmp_path, "pipe.py")


def test_directory_replacement_cannot_redirect_read_to_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "robot.py").write_text("public code")
    private = tmp_path / "secrets"
    private.mkdir()
    (private / "robot.py").write_text("private content")
    original = os.open
    swapped = False

    def racing(path: str, flags: int, *, dir_fd: int | None = None) -> int:
        nonlocal swapped
        fd = original(path, flags, dir_fd=dir_fd)
        if path == "src" and not swapped:
            swapped = True
            source.rename(tmp_path / "old-src")
            source.symlink_to(private, target_is_directory=True)
        return fd

    monkeypatch.setattr(os, "open", racing)
    monkeypatch.setattr(os, "supports_dir_fd", {*os.supports_dir_fd, racing})
    assert code_reader.read_code_file(tmp_path, "src/robot.py")["content"] == "public code"
