"""Open-in-KiCad conflict: a write must never clobber, or be clobbered by, a
schematic the user is editing in the KiCad GUI (stable `stale_plan` refusal)."""
# mypy: disable-error-code="import-not-found,no-untyped-def"

import shutil
from pathlib import Path
from typing import Any

import pytest

from paths import SOLUS_SAMPLE_SCH  # isort: skip

from solus.development.models import DevelopmentError, fingerprint  # isort: skip
from solus.write.set_symbol_property import set_symbol_property_impl  # isort: skip


def _copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(workspace))
    target = workspace / SOLUS_SAMPLE_SCH.name
    shutil.copyfile(SOLUS_SAMPLE_SCH, target)
    return target


def _edit(target: Path, fp: str, dry_run: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = set_symbol_property_impl(
        target.name, "U1", "MPN", "NEW-123", fp, dry_run
    )
    return result


def test_write_refused_when_file_changed_since_it_was_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = _copy(monkeypatch, tmp_path)
    observed = fingerprint(target.read_bytes())
    saved_from_gui = target.read_bytes() + b"\n"  # KiCad saved after Solus read
    target.write_bytes(saved_from_gui)
    with pytest.raises(DevelopmentError, match="stale_plan"):
        _edit(target, observed)
    assert target.read_bytes() == saved_from_gui


@pytest.mark.parametrize("lock", ["~{name}.lck", "{name}.lck"])
def test_write_refused_while_kicad_holds_the_editor_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lock: str
) -> None:
    target = _copy(monkeypatch, tmp_path)
    before = target.read_bytes()
    (target.parent / lock.format(name=target.name)).write_text("user@host")
    with pytest.raises(DevelopmentError, match="stale_plan"):
        _edit(target, fingerprint(before))
    assert target.read_bytes() == before


def test_write_proceeds_when_no_editor_holds_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = _copy(monkeypatch, tmp_path)
    result = _edit(target, fingerprint(target.read_bytes()))
    assert result["changed"] is True
    assert b"NEW-123" in target.read_bytes()
