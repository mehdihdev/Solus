"""Managed Python — mcp-fork-runtime.md §7: manifest, capped download,
hash-before-extract, and a refusing tar extractor."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from solus_companion.runtime.errors import RuntimeSetupError
from solus_companion.runtime.managed import (
    ALLOWED_DOWNLOAD_HOSTS,
    ManagedAsset,
    ManagedInstaller,
    ManagedManifest,
    load_manifest,
    managed_interpreter,
    platform_key,
    redirect_allowed,
    safe_extract,
)
from solus_companion.runtime.ownership import PosixOwnerOnly
from solus_companion.runtime.protocol import ProgressLine, RuntimeLine

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mcp_runtime"
URL = "https://github.com/astral-sh/python-build-standalone/releases/download/r1/cpython.tar.gz"


def _tar(entries: list[tarfile.TarInfo | tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for entry in entries:
            if isinstance(entry, tarfile.TarInfo):
                tar.addfile(entry)
            else:
                info = tarfile.TarInfo(entry[0])
                info.size = len(entry[1])
                info.mode = 0o755
                tar.addfile(info, io.BytesIO(entry[1]))
    return buf.getvalue()


def _python_tree() -> bytes:
    link = tarfile.TarInfo("python/bin/python3")
    link.type = tarfile.SYMTYPE
    link.linkname = "python3.12"
    return _tar([("python/bin/python3.12", b"#!/bin/sh\n"), link, ("python/lib/x.py", b"")])


def _manifest(
    data: bytes, *, verified: bool = True, max_bytes: int = 10_000_000, sha: str | None = None
) -> ManagedManifest:
    asset = ManagedAsset(
        url=URL, sha256=sha or hashlib.sha256(data).hexdigest(), max_bytes=max_bytes
    )
    return ManagedManifest(
        schema_version=1,
        release="r1",
        python_version="3.12.7",
        verified=verified,
        assets={"darwin-arm64": asset},
    )


class _Stream:
    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)
        self.closed = False

    def read(self, n: int, /) -> bytes:
        return self._buf.read(n)

    def close(self) -> None:
        self.closed = True


class _Fetcher:
    def __init__(self, data: bytes, length: int | None = None, fail: bool = False) -> None:
        self.data = data
        self.length = length
        self.fail = fail
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float) -> tuple[_Stream, int | None]:
        self.urls.append(url)
        if self.fail:
            raise OSError("connection refused")
        return _Stream(self.data), self.length


def _installer(
    tmp_path: Path,
    manifest: ManagedManifest,
    fetcher: _Fetcher,
    emitted: list[RuntimeLine] | None = None,
) -> ManagedInstaller:
    sink = emitted if emitted is not None else []
    return ManagedInstaller(
        python_root=tmp_path / "mcp-python",
        manifest=manifest,
        fetcher=fetcher,
        policy=PosixOwnerOnly(),
        emit=sink.append,
        platform="darwin",
        asset_key="darwin-arm64",
    )


def _code(exc: pytest.ExceptionInfo[RuntimeSetupError]) -> str:
    return exc.value.code


# --------------------------------------------------------------- manifest


def test_shipped_manifest_is_the_unverified_placeholder() -> None:
    manifest = load_manifest()
    assert manifest.verified is False
    assert set(manifest.assets) == {
        "darwin-arm64",
        "darwin-x64",
        "win32-x64",
        "linux-x64",
        "linux-arm64",
    }
    assert all(a.sha256 == "0" * 64 for a in manifest.assets.values())


def test_fixture_example_manifest_validates_once_comment_is_dropped() -> None:
    data = json.loads((FIXTURES / "managed_manifest.example.json").read_text())
    data.pop("_comment")
    assert ManagedManifest.model_validate(data).release == "PLACEHOLDER"


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/astral-sh/python-build-standalone/releases/download/r/x.tar.gz",
        "https://evil.example/astral-sh/python-build-standalone/releases/download/r/x.tar.gz",
        "https://github.com/someone-else/python-build-standalone/releases/download/r/x.tar.gz",
    ],
)
def test_manifest_urls_are_pinned_to_the_release_host(url: str) -> None:
    with pytest.raises(ValueError):
        ManagedAsset(url=url, sha256="a" * 64, max_bytes=1000)


def test_platform_keys() -> None:
    assert platform_key("darwin", "arm64") == "darwin-arm64"
    assert platform_key("darwin", "x86_64") == "darwin-x64"
    assert platform_key("win32", "AMD64") == "win32-x64"
    assert platform_key("linux", "aarch64") == "linux-arm64"
    assert platform_key("linux", "x86_64") == "linux-x64"
    assert platform_key("freebsd", "x86_64") is None


def test_managed_interpreter_paths(tmp_path: Path) -> None:
    assert managed_interpreter(tmp_path, "darwin") == tmp_path / "python" / "bin" / "python3"
    assert managed_interpreter(tmp_path, "win32") == tmp_path / "python" / "python.exe"


# --------------------------------------------------------------- install


def test_unverified_manifest_is_refused_before_any_network(tmp_path: Path) -> None:
    fetcher = _Fetcher(b"")
    with pytest.raises(RuntimeSetupError) as caught:
        _installer(tmp_path, load_manifest(), fetcher).install()
    assert _code(caught) == "managed_hash_mismatch"
    assert fetcher.urls == []


def test_zero_hash_is_refused_even_if_flagged_verified(tmp_path: Path) -> None:
    fetcher = _Fetcher(b"")
    with pytest.raises(RuntimeSetupError) as caught:
        _installer(tmp_path, _manifest(b"", sha="0" * 64), fetcher).install()
    assert _code(caught) == "managed_hash_mismatch" and fetcher.urls == []


def test_no_asset_for_this_platform(tmp_path: Path) -> None:
    installer = ManagedInstaller(
        python_root=tmp_path / "mcp-python",
        manifest=_manifest(b"x"),
        fetcher=_Fetcher(b""),
        policy=PosixOwnerOnly(),
        emit=lambda line: None,
        platform="linux",
        asset_key="linux-x64",
    )
    with pytest.raises(RuntimeSetupError) as caught:
        installer.install()
    assert _code(caught) == "managed_download_failed"


def test_happy_path_downloads_verifies_and_extracts(tmp_path: Path) -> None:
    data = _python_tree()
    emitted: list[RuntimeLine] = []

    interpreter = _installer(
        tmp_path, _manifest(data), _Fetcher(data, len(data)), emitted
    ).install()

    assert interpreter == tmp_path / "mcp-python" / "r1" / "python" / "bin" / "python3"
    assert interpreter.resolve().name == "python3.12"
    assert PosixOwnerOnly().check(tmp_path / "mcp-python")
    assert sorted(p.name for p in (tmp_path / "mcp-python").iterdir()) == ["r1"]
    steps = [e.step for e in emitted if isinstance(e, ProgressLine)]
    assert steps[0] == "download" and steps[-2:] == ["verify", "extract"]


def test_reinstall_replaces_the_release_dir(tmp_path: Path) -> None:
    data = _python_tree()
    stale = tmp_path / "mcp-python" / "r1" / "stale"
    stale.parent.mkdir(parents=True)
    stale.write_text("x")
    _installer(tmp_path, _manifest(data), _Fetcher(data)).install()
    assert not stale.exists()


def test_hash_mismatch_aborts_before_extraction(tmp_path: Path) -> None:
    data = _python_tree()
    with pytest.raises(RuntimeSetupError) as caught:
        _installer(tmp_path, _manifest(data, sha="e" * 64), _Fetcher(data)).install()
    assert _code(caught) == "managed_hash_mismatch"
    assert list((tmp_path / "mcp-python").iterdir()) == []


def test_oversize_download_is_refused_while_streaming(tmp_path: Path) -> None:
    data = b"x" * 5000
    with pytest.raises(RuntimeSetupError) as caught:
        _installer(tmp_path, _manifest(data, max_bytes=4096), _Fetcher(data)).install()
    assert _code(caught) == "managed_too_large"
    assert list((tmp_path / "mcp-python").iterdir()) == []


def test_declared_oversize_length_is_refused_up_front(tmp_path: Path) -> None:
    with pytest.raises(RuntimeSetupError) as caught:
        _installer(tmp_path, _manifest(b"x", max_bytes=4096), _Fetcher(b"x", 10**9)).install()
    assert _code(caught) == "managed_too_large"


def test_network_failure_is_download_failed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeSetupError) as caught:
        _installer(tmp_path, _manifest(b"x"), _Fetcher(b"", fail=True)).install()
    assert _code(caught) == "managed_download_failed"


def _interrupted(tmp_path: Path, *, target_too: bool) -> Path:
    """A run killed between "old release aside" and "new release in"."""
    root = tmp_path / "mcp-python"
    root.mkdir(mode=0o700)
    (root / ".r1.old" / "python" / "bin").mkdir(parents=True)
    (root / ".r1.old" / "python" / "bin" / "python3").write_text("old")
    if target_too:
        (root / "r1" / "python").mkdir(parents=True)
    return root


def test_an_interrupted_swap_restores_the_old_release(tmp_path: Path) -> None:
    root = _interrupted(tmp_path, target_too=False)
    with pytest.raises(RuntimeSetupError):
        _installer(tmp_path, _manifest(b"x"), _Fetcher(b"", fail=True)).install()
    assert sorted(p.name for p in root.iterdir()) == ["r1"]
    assert (root / "r1" / "python" / "bin" / "python3").read_text() == "old"


def test_an_interrupted_swap_leftover_is_removed_when_the_release_exists(tmp_path: Path) -> None:
    root = _interrupted(tmp_path, target_too=True)
    with pytest.raises(RuntimeSetupError):
        _installer(tmp_path, _manifest(b"x"), _Fetcher(b"", fail=True)).install()
    assert sorted(p.name for p in root.iterdir()) == ["r1"]
    assert not (root / "r1" / "python" / "bin").exists()


def test_archive_without_an_interpreter_is_refused(tmp_path: Path) -> None:
    data = _tar([("python/README", b"hi")])
    with pytest.raises(RuntimeSetupError) as caught:
        _installer(tmp_path, _manifest(data), _Fetcher(data)).install()
    assert _code(caught) == "managed_extract_refused"


# --------------------------------------------------------------- redirects


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://objects.githubusercontent.com/x", True),
        ("https://release-assets.githubusercontent.com/x", True),
        ("https://github.com/x", True),
        ("http://objects.githubusercontent.com/x", False),
        ("https://evil.example/x", False),
        ("https://github.com.evil.example/x", False),
        ("file:///etc/passwd", False),
    ],
)
def test_redirects_only_to_https_github_release_hosts(url: str, ok: bool) -> None:
    assert redirect_allowed(url) is ok
    assert "github.com" in ALLOWED_DOWNLOAD_HOSTS


# --------------------------------------------------------------- extraction


def _member(name: str, kind: bytes = tarfile.REGTYPE, link: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = link
    return info


@pytest.mark.parametrize(
    "entry",
    [
        ("/etc/evil", b"x"),
        ("python/../../evil", b"x"),
        ("..\\evil", b"x"),
        _member("python/bin/esc", tarfile.SYMTYPE, "../../../etc/passwd"),
        _member("python/bin/abs", tarfile.SYMTYPE, "/etc/passwd"),
        _member("python/bin/hard", tarfile.LNKTYPE, "../outside"),
        _member("python/dev", tarfile.CHRTYPE),
        _member("python/fifo", tarfile.FIFOTYPE),
    ],
    ids=[
        "absolute",
        "dotdot",
        "backslash",
        "symlink-escape",
        "symlink-abs",
        "hardlink",
        "device",
        "fifo",
    ],
)
def test_hostile_archives_are_refused(
    tmp_path: Path, entry: tarfile.TarInfo | tuple[str, bytes]
) -> None:
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(_tar([("python/ok", b"ok"), entry]))
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(RuntimeSetupError) as caught:
        safe_extract(archive, dest)
    assert _code(caught) == "managed_extract_refused"
    assert not (tmp_path / "evil").exists()
    assert not (dest / "python" / "ok").exists()  # vetted BEFORE anything is written


def test_internal_links_are_allowed(tmp_path: Path) -> None:
    hard = _member("python/bin/python3-hard", tarfile.LNKTYPE, "python/bin/python3.12")
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(_tar([("python/bin/python3.12", b"x"), hard]))
    safe_extract(archive, tmp_path)
    assert (tmp_path / "python" / "bin" / "python3-hard").read_bytes() == b"x"


def test_corrupt_archive_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(b"not a tarball")
    with pytest.raises(RuntimeSetupError) as caught:
        safe_extract(archive, tmp_path)
    assert _code(caught) == "managed_extract_refused"
