"""Complete, confined text-write plans through the real builtin tool boundary."""

import os

import pytest
from solus_companion.machine.server import MachineServer


async def preview(server, args):
    result = await server.call_tool("write_file", {**args, "dry_run": True})
    assert not result.isError
    return result.structuredContent


async def apply(server, args, plan):
    return await server.call_tool(
        "write_file", {**args, "expected_fingerprint": plan["fingerprint"]}
    )


async def test_complete_preview_then_verified_create_and_edit(tmp_path):
    server = MachineServer(tmp_path)
    args = {"path": "src/main.py", "content": "print('hello')\n", "create_dirs": True}
    plan = await preview(server, args)
    assert list(tmp_path.iterdir()) == []
    assert plan["dry_run"] is True
    assert plan["preview"][0]["after"] == "src/main.py"
    assert (
        "".join(row["after"] or "" for row in plan["preview"] if row["label"].startswith("Content"))
        == args["content"]
    )
    result = await apply(server, args, plan)
    assert not result.isError
    assert result.structuredContent["verified"] is True
    assert (tmp_path / args["path"]).read_text() == args["content"]
    edited = {**args, "content": "print('updated')\n"}
    plan = await preview(server, edited)
    assert (
        "".join(
            row["before"] or "" for row in plan["preview"] if row["label"].startswith("Content")
        )
        == args["content"]
    )
    assert not (await apply(server, edited, plan)).isError


async def test_write_without_fingerprint_refused(tmp_path):
    result = await MachineServer(tmp_path).call_tool(
        "write_file", {"path": "new.py", "content": "x"}
    )
    assert result.isError
    assert not (tmp_path / "new.py").exists()


@pytest.mark.parametrize("change", ["bytes", "inode", "symlink", "parent"])
async def test_changed_state_refused_before_write(tmp_path, change):
    folder = tmp_path / "src"
    folder.mkdir()
    target = folder / "main.py"
    target.write_text("before")
    server = MachineServer(tmp_path)
    args = {"path": "src/main.py", "content": "after"}
    plan = await preview(server, args)
    outside = tmp_path.parent / (tmp_path.name + "-sentinel")
    outside.write_text("outside")
    if change == "bytes":
        target.write_text("changed")
    elif change == "inode":
        target.unlink()
        target.write_text("before")
    elif change == "symlink":
        target.unlink()
        target.symlink_to(outside)
    else:
        folder.rename(tmp_path / "old")
        folder.mkdir()
        target.write_text("before")
    assert (await apply(server, args, plan)).isError
    assert outside.read_text() == "outside"
    assert target.read_text() != "after"


@pytest.mark.parametrize(
    "path", ["../x.py", "/tmp/x.py", "src/../x.py", ".env", ".git/config", ".ssh/key", "a\\b.py"]
)
async def test_unsafe_paths_refused(tmp_path, path):
    result = await MachineServer(tmp_path).call_tool(
        "write_file", {"path": path, "content": "x", "dry_run": True}
    )
    assert result.isError
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "before,after", [(b"\xff", "text"), (b"\x00", "text"), (b"x" * 20001, "x"), (b"x", "y" * 20001)]
)
async def test_binary_and_incomplete_previews_refused(tmp_path, before, after):
    target = tmp_path / "main.py"
    target.write_bytes(before)
    result = await MachineServer(tmp_path).call_tool(
        "write_file", {"path": "main.py", "content": after, "dry_run": True}
    )
    assert result.isError
    assert target.read_bytes() == before


async def test_parent_swap_at_publication_never_changes_external_file(tmp_path, monkeypatch):
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "main.py").write_text("before")
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    sentinel = outside / "main.py"
    sentinel.write_text("outside")
    server = MachineServer(tmp_path)
    args = {"path": "src/main.py", "content": "after"}
    plan = await preview(server, args)
    replace = os.replace

    def swapping(*args, **kwargs):
        folder.rename(tmp_path / "moved")
        folder.symlink_to(outside, target_is_directory=True)
        return replace(*args, **kwargs)

    monkeypatch.setattr(os, "replace", swapping)
    result = await apply(server, args, plan)
    assert result.isError
    assert sentinel.read_text() == "outside"


async def test_publication_error_after_replace_reports_uncertain(tmp_path, monkeypatch):
    target = tmp_path / "main.py"
    target.write_text("before")
    server = MachineServer(tmp_path)
    args = {"path": "main.py", "content": "after"}
    plan = await preview(server, args)
    replace = os.replace

    def applied_then_failed(*args, **kwargs):
        replace(*args, **kwargs)
        raise OSError("injected failure after publication")

    monkeypatch.setattr(os, "replace", applied_then_failed)
    result = await apply(server, args, plan)
    assert result.isError
    assert target.read_text() == "after"
    assert "mutation_unverified" in result.content[0].text


async def test_final_namespace_swap_never_returns_verified(tmp_path, monkeypatch):
    import stat

    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "main.py").write_text("before")
    outside = tmp_path.parent / (tmp_path.name + "-outside-final")
    outside.mkdir()
    (outside / "main.py").write_text("outside")
    server = MachineServer(tmp_path)
    args = {"path": "src/main.py", "content": "after"}
    plan = await preview(server, args)
    sync = os.fsync

    def swapped_after_sync(fd):
        sync(fd)
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            folder.rename(tmp_path / "moved")
            folder.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(os, "fsync", swapped_after_sync)
    result = await apply(server, args, plan)
    assert result.isError
    assert "mutation_unverified" in result.content[0].text
    assert (outside / "main.py").read_text() == "outside"
