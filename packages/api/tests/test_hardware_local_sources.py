"""Local runner private-source authorization and verified-byte boundaries."""

import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from solus_api.hardware.local_sources import LocalHardwareSources, LocalSourceError

SourceFixture = tuple[LocalHardwareSources, Path, Path, uuid.UUID, uuid.UUID, str]


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """These filesystem tests never use or initialize a database."""


@pytest.fixture
def source(tmp_path: Path) -> tuple[LocalHardwareSources, Path, Path, uuid.UUID, uuid.UUID, str]:
    project, account, ref = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    selected = tmp_path / "calibration.json"
    selected.write_bytes(b'{"offset":3}')
    state = tmp_path / ".solus" / "projects" / str(project) / "hardware.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "accounts": {
                    str(account): {
                        "sources": {
                            str(ref): {
                                "path": str(selected),
                                "contentSha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
                            }
                        },
                        "bindings": {str(ref): {"lastSeenPath": "/dev/fixture"}},
                    }
                },
            }
        )
    )
    state.chmod(0o600)
    return (
        LocalHardwareSources.for_local_runner(object(), home=tmp_path),
        selected,
        state,
        project,
        account,
        f"source:{ref}",
    )


def test_cloud_has_no_home_or_filesystem_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> Path:
        pytest.fail("cloud must not resolve a local home")

    monkeypatch.setattr(Path, "home", forbidden)
    with pytest.raises(LocalSourceError, match="unavailable"):
        LocalHardwareSources.for_local_runner(None)


def test_verified_bytes_are_portable_and_hints_remain_local(source: SourceFixture) -> None:
    reader, selected, _, project, account, ref = source
    result = reader.read_source(project, account, ref)
    assert result.content == selected.read_bytes()
    assert result.source_ref == ref and result.suffix == ".json"
    assert str(selected) not in repr(result)
    assert reader.binding_hint(project, account, uuid.UUID(ref[7:])) == "/dev/fixture"


@pytest.mark.parametrize("scope", ["project", "account", "reference"])
def test_other_scopes_never_resolve_source(source: SourceFixture, scope: str) -> None:
    reader, _, _, project, account, ref = source
    if scope == "project":
        project = uuid.uuid4()
    elif scope == "account":
        account = uuid.uuid4()
    else:
        ref = f"source:{uuid.uuid4()}"
    with pytest.raises(LocalSourceError) as failure:
        reader.read_source(project, account, ref)
    assert failure.value.code == "not_found"


@pytest.mark.parametrize(
    "fault", ["digest", "missing", "link", "parent_link", "large", "utf8", "fifo", "format"]
)
def test_unsafe_source_never_returns_bytes(source: SourceFixture, fault: str) -> None:
    reader, selected, state, project, account, ref = source
    if fault == "digest":
        selected.write_text('{"offset":4}')
    elif fault == "missing":
        selected.unlink()
    elif fault == "link":
        other = selected.with_name("other.json")
        selected.rename(other)
        selected.symlink_to(other)
    elif fault == "parent_link":
        alias = selected.parent / "alias"
        alias.symlink_to(selected.parent, target_is_directory=True)
        document = json.loads(state.read_text())
        document["accounts"][str(account)]["sources"][ref[7:]]["path"] = str(alias / selected.name)
        state.write_text(json.dumps(document))
    elif fault == "large":
        selected.write_bytes(b"x" * (256 * 1024 + 1))
    elif fault == "utf8":
        selected.write_bytes(b"\xff")
    elif fault == "fifo":
        selected.unlink()
        os.mkfifo(selected)
    else:
        unsupported = selected.with_suffix(".sh")
        selected.rename(unsupported)
        document = json.loads(state.read_text())
        document["accounts"][str(account)]["sources"][ref[7:]]["path"] = str(unsupported)
        state.write_text(json.dumps(document))
    with pytest.raises(LocalSourceError) as failure:
        reader.read_source(project, account, ref)
    assert str(selected) not in str(failure.value)


@pytest.mark.parametrize("fault", ["corrupt", "newer", "oversized", "unknown", "symlink"])
def test_invalid_private_state_is_not_rewritten(source: SourceFixture, fault: str) -> None:
    reader, _, state, project, account, ref = source
    if fault == "corrupt":
        state.write_text("bad")
    elif fault == "newer":
        state.write_text('{"schema_version":2,"future":true}')
    elif fault == "oversized":
        state.write_text(" " * (256 * 1024 + 1))
    elif fault == "unknown":
        state.write_text('{"schema_version":1,"accounts":{},"extra":true}')
    else:
        original = state.with_suffix(".original")
        state.rename(original)
        state.symlink_to(original)
    before = state.read_bytes()
    with pytest.raises(LocalSourceError) as failure:
        reader.read_source(project, account, ref)
    assert failure.value.code == ("newer" if fault == "newer" else "relink_required")
    assert state.read_bytes() == before


def test_invalid_reference_rejected_before_state_read(source: SourceFixture) -> None:
    reader, _, _, project, account, _ = source
    with pytest.raises(LocalSourceError, match="invalid"):
        reader.read_source(project, account, "../../private")


def test_replacement_during_read_is_refused(
    source: SourceFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, selected, _, project, account, ref = source
    original = os.read
    replaced = False

    def read(fd: int, size: int) -> bytes:
        nonlocal replaced
        result = original(fd, size)
        if result == b'{"offset":3}' and not replaced:
            replacement = selected.with_suffix(".new")
            replacement.write_bytes(result)
            replacement.replace(selected)
            replaced = True
        return result

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(LocalSourceError, match="relink_required"):
        reader.read_source(project, account, ref)
