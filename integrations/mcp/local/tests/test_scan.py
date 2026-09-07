"""SOLUSDEV-249 — `scan_folder` / `folder_digest` per §4: sorted relative
paths reported as SPLIT `parts`, skip dirs, suffix filter, streamed
blake2b-128 file hash with the 32 MiB cap, blake2b-128 digest (stable;
changes on one edit), truncation at MAX_FILES, empty folder, hostile
symlinks — and a redaction-safety pin: no wire string is 40+ chars."""

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from .local_paths import overlay_module  # isort: skip

scan = overlay_module("scan")
toolmap = overlay_module("toolmap")

NO_TOOLS = {"kicad": False, "altium": False, "vscode": False}


def _tools() -> dict[str, bool]:
    return dict(NO_TOOLS)


def _b2(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def _write(root: Path, rel: str, content: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _sample(root: Path) -> None:
    _write(root, "hw/main/main.kicad_pro", b'{"meta": {}}')
    _write(root, "hw/main/main.kicad_sch", b"(kicad_sch)")
    _write(root, "fw/blink/blink.ino", b"void setup() {}")
    _write(root, "tools/flash.py", b"print(1)")
    _write(root, "mech/frame.step", b"ISO-10303-21;")
    _write(root, "README.md", b"# nope")
    _write(root, "node_modules/pkg/index.py", b"skip")
    _write(root, ".git/config", b"skip")
    _write(root, "build/out.kicad_pcb", b"skip")
    _write(root, "solus-artifacts/x.py", b"skip")


def _joined(result: dict[str, Any]) -> list[str]:
    return ["/".join(entry["parts"]) for entry in result["files"]]


def test_scan_lists_only_tool_files_sorted_as_parts(tmp_path: Path) -> None:
    _sample(tmp_path)
    result = scan.scan_folder(tmp_path, tools=_tools())
    assert result["schema_version"] == 1
    assert result["root_name"] == tmp_path.name
    assert result["git"] is None
    assert result["truncated"] is False
    assert result["tools_installed"] == NO_TOOLS
    paths = _joined(result)
    assert paths == sorted(paths)
    assert paths == [
        "fw/blink/blink.ino",
        "hw/main/main.kicad_pro",
        "hw/main/main.kicad_sch",
        "mech/frame.step",
        "tools/flash.py",
    ]
    by_path = {"/".join(entry["parts"]): entry for entry in result["files"]}
    assert by_path["hw/main/main.kicad_pro"]["parts"] == ["hw", "main", "main.kicad_pro"]
    assert by_path["hw/main/main.kicad_pro"]["tool"] == "kicad"
    assert by_path["fw/blink/blink.ino"]["tool"] == "arduino"
    assert by_path["tools/flash.py"]["tool"] == "python"
    assert by_path["mech/frame.step"]["tool"] == "cad"
    assert by_path["tools/flash.py"]["size"] == len(b"print(1)")
    assert by_path["tools/flash.py"]["hash"] == _b2(b"print(1)")
    for entry in result["files"]:
        assert set(entry) == {"parts", "size", "hash", "tool"}
        assert all("/" not in part and part for part in entry["parts"])


def test_no_wire_string_is_redaction_shaped(tmp_path: Path) -> None:
    """The cloud masks any 40+ char string over [A-Za-z0-9+/=_.-] with 16+
    distinct chars: hashes are 32 hex, paths are split, git head is short."""
    _write(tmp_path, "firmware/src/controllers/motor_controller_calibration/main.py", b"x")
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "config").write_text('[remote "origin"]\n\turl = https://github.com/org/x.git\n')
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs" / "heads" / "main").write_text("0123456789abcdef" * 2 + "01234567" + "\n")
    result = scan.scan_folder(tmp_path, tools=_tools())

    def strings(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [s for item in value.values() for s in strings(item)]
        if isinstance(value, list):
            return [s for item in value for s in strings(item)]
        return [value] if isinstance(value, str) else []

    for text in strings(result):
        assert len(text) < 40, text
    assert len(result["digest"]) == 32
    assert result["git"]["head"] == "0123456789ab"


def test_scan_reads_git_when_present(tmp_path: Path) -> None:
    _sample(tmp_path)
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "config").write_text('[remote "origin"]\n\turl = https://github.com/org/x.git\n')
    (git / "HEAD").write_text("ref: refs/heads/dev\n")
    (git / "refs" / "heads" / "dev").write_text("c" * 40 + "\n")
    result = scan.scan_folder(tmp_path, tools=_tools())
    assert result["git"] == {
        "remote_url": "https://github.com/org/x.git",
        "branch": "dev",
        "head": "c" * 12,
    }


def test_digest_is_blake2b_128_over_joined_parts_and_hash_or_size(tmp_path: Path) -> None:
    _sample(tmp_path)
    result = scan.scan_folder(tmp_path, tools=_tools())
    expected = hashlib.blake2b(digest_size=16)
    for entry in result["files"]:
        joined = "/".join(entry["parts"])
        expected.update(f"{joined}:{entry['hash'] or entry['size']}\n".encode())
    assert result["digest"] == expected.hexdigest()
    assert len(result["digest"]) == 32


def test_folder_digest_matches_scan_and_is_stable(tmp_path: Path) -> None:
    _sample(tmp_path)
    first = scan.folder_digest(tmp_path)
    second = scan.folder_digest(tmp_path)
    assert first == second
    assert set(first) == {"digest", "truncated"}
    assert first["digest"] == scan.scan_folder(tmp_path, tools=_tools())["digest"]


def test_digest_changes_on_one_edit_and_ignores_irrelevant_files(tmp_path: Path) -> None:
    _sample(tmp_path)
    before = scan.folder_digest(tmp_path)["digest"]
    _write(tmp_path, "README.md", b"# changed but irrelevant")
    assert scan.folder_digest(tmp_path)["digest"] == before
    _write(tmp_path, "tools/flash.py", b"print(2)")
    assert scan.folder_digest(tmp_path)["digest"] != before


def test_empty_folder(tmp_path: Path) -> None:
    result = scan.scan_folder(tmp_path, tools=_tools())
    assert result["files"] == []
    assert result["truncated"] is False
    assert result["git"] is None
    assert result["digest"] == hashlib.blake2b(digest_size=16).hexdigest()
    assert scan.folder_digest(tmp_path) == {"digest": result["digest"], "truncated": False}


def test_hash_is_null_over_the_cap_and_digest_uses_the_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(scan, "MAX_HASH_BYTES", 8)
    _write(tmp_path, "big.py", b"0123456789")  # 10 bytes > 8
    _write(tmp_path, "small.py", b"01234567")  # 8 bytes == cap: hashed
    result = scan.scan_folder(tmp_path, tools=_tools())
    by_path = {"/".join(entry["parts"]): entry for entry in result["files"]}
    assert by_path["big.py"]["hash"] is None
    assert by_path["big.py"]["size"] == 10
    assert by_path["small.py"]["hash"] == _b2(b"01234567")
    expected = hashlib.blake2b(digest_size=16)
    expected.update(b"big.py:10\n")
    expected.update(f"small.py:{by_path['small.py']['hash']}\n".encode())
    assert result["digest"] == expected.hexdigest()


def test_file_hash_streams_in_chunks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scan, "HASH_CHUNK_BYTES", 3)
    content = b"abcdefghij"
    path = _write(tmp_path, "s.py", content)
    assert scan.file_hash(path) == _b2(content)


def test_truncates_at_max_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scan, "MAX_FILES", 3)
    for index in range(5):
        _write(tmp_path, f"f{index}.py", b"x")
    result = scan.scan_folder(tmp_path, tools=_tools())
    assert _joined(result) == ["f0.py", "f1.py", "f2.py"]
    assert result["truncated"] is True
    assert scan.folder_digest(tmp_path) == {"digest": result["digest"], "truncated": True}


def test_collection_stops_at_the_cap_during_the_walk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Memory is bounded by MAX_FILES, not the tree: the walk is abandoned
    once MAX_FILES + 1 candidates are seen."""
    monkeypatch.setattr(scan, "MAX_FILES", 3)
    for index in range(10):
        _write(tmp_path, f"f{index}.py", b"x")
    seen: list[str] = []
    real_walk = scan._walk

    def counting_walk(root: Path) -> Any:
        for item in real_walk(root):
            seen.append(item[0])
            yield item

    monkeypatch.setattr(scan, "_walk", counting_walk)
    result = scan.scan_folder(tmp_path, tools=_tools())
    assert result["truncated"] is True
    assert len(result["files"]) == 3
    assert len(seen) == 4, "the walk must stop at MAX_FILES + 1"


def test_file_hash_stops_at_the_byte_budget_when_the_file_grows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """stat said 4 bytes, the handle keeps producing: over-cap → null."""
    monkeypatch.setattr(scan, "MAX_HASH_BYTES", 8)
    monkeypatch.setattr(scan, "HASH_CHUNK_BYTES", 3)
    path = _write(tmp_path, "grow.py", b"0123")

    class Growing:
        def __init__(self) -> None:
            self.served = 0

        def read(self, n: int) -> bytes:
            self.served += n
            return b"x" * n if self.served <= 30 else b""

        def __enter__(self) -> "Growing":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(scan, "_open_for_hash", lambda _p: Growing())
    assert scan.file_hash(path, size=4) is None


def test_exactly_max_files_is_not_truncated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(scan, "MAX_FILES", 3)
    for index in range(3):
        _write(tmp_path, f"f{index}.py", b"x")
    assert scan.scan_folder(tmp_path, tools=_tools())["truncated"] is False


def test_symlinks_are_neither_followed_nor_hashed(tmp_path: Path) -> None:
    """A hostile folder: a symlinked file and a symlinked directory that both
    point OUTSIDE the workspace must not appear (and must never be read)."""
    outside = tmp_path / "outside"
    outside.mkdir()
    _write(outside, "secret.py", b"secret")
    _write(outside, "dir/leak.kicad_pro", b"leak")
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "ok.py", b"ok")
    os.symlink(outside / "secret.py", root / "link.py")
    os.symlink(outside / "dir", root / "linkdir")
    result = scan.scan_folder(root, tools=_tools())
    assert _joined(result) == ["ok.py"]


def test_unreadable_file_reports_size_with_null_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write(tmp_path, "a.py", b"abc")

    def boom(*_args: object, **_kwargs: object) -> object:
        raise PermissionError("nope")

    monkeypatch.setattr(scan, "_open_for_hash", boom)
    result = scan.scan_folder(tmp_path, tools=_tools())
    assert result["files"] == [{"parts": ["a.py"], "size": 3, "hash": None, "tool": "python"}]


def test_missing_root_is_the_empty_shape(tmp_path: Path) -> None:
    result = scan.scan_folder(tmp_path / "gone", tools=_tools())
    assert result["files"] == [] and result["truncated"] is False and result["git"] is None


def test_scan_probes_tools_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    probed = {"kicad": True, "altium": False, "vscode": True}
    monkeypatch.setattr(scan, "tools_installed", lambda: probed)
    assert scan.scan_folder(tmp_path)["tools_installed"] == probed
