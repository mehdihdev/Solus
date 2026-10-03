"""SOLUSDEV-312 (ADR-037) — the live change-hint frame contract, Python half.

Validates the SAME fixtures the TypeScript suite reads
(packages/shared-types/fixtures/live-events/) and regenerates the ``_fields.json``
manifest the TS field lists are compared against.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError
from solus_contracts import live_events as le

FIXTURES = Path(__file__).resolve().parents[3] / "shared-types" / "fixtures" / "live-events"

MODELS: list[type[BaseModel]] = [
    le.GraphChangeCounts,
    le.GraphChanged,
    le.HardwareDevicesChanged,
    le.LayoutChanged,
    le.SourcesChanged,
    le.ProjectUpdated,
    le.JobUpdated,
    le.ProjectStreamReady,
    le.TeamUpdated,
    le.TeamMembersChanged,
    le.TeamInvitesChanged,
    le.TeamProjectsChanged,
    le.TeamActivity,
    le.NotificationCreated,
    le.MembershipChanged,
    le.AccessRevoked,
    le.AccountStreamReady,
]

_ANY_FRAME: TypeAdapter[le.ProjectFrame | le.AccountFrame] = TypeAdapter(
    le.ProjectFrame | le.AccountFrame
)
_READY: dict[str, type[BaseModel]] = {
    "account-ready": le.AccountStreamReady,
    "project-ready": le.ProjectStreamReady,
}


def _fixtures(valid: bool) -> list[Path]:
    return sorted(
        p
        for p in FIXTURES.glob("*.json")
        if not p.name.startswith("_") and p.name.endswith(".invalid.json") is not valid
    )


def _validate(path: Path) -> BaseModel:
    data = json.loads(path.read_text())
    ready = _READY.get(path.stem)
    if ready is not None:
        validated: BaseModel = ready.model_validate(data)
        return validated
    result: BaseModel = _ANY_FRAME.validate_python(data)
    return result


@pytest.mark.parametrize("path", _fixtures(valid=True), ids=lambda p: p.stem)
def test_valid_fixtures_parse(path: Path) -> None:
    _validate(path)


@pytest.mark.parametrize("path", _fixtures(valid=False), ids=lambda p: p.stem)
def test_invalid_fixtures_are_rejected(path: Path) -> None:
    with pytest.raises(ValidationError):
        _validate(path)


def test_every_frame_type_has_a_valid_fixture() -> None:
    seen = {json.loads(p.read_text()).get("type") for p in _fixtures(valid=True)}
    expected = set(le.PROJECT_EVENT_TYPES) | set(le.ACCOUNT_EVENT_TYPES)
    # hardware.devices_changed is local-only and already pinned by SOLUSDEV-250's tests.
    assert expected - {"hardware.devices_changed"} <= seen


def test_event_type_lists_match_the_frame_literals() -> None:
    def literal_types(union: object) -> set[str]:
        return {m.model_fields["type"].default for m in union.__args__}  # type: ignore[attr-defined]

    assert literal_types(le.ProjectFrame) == set(le.PROJECT_EVENT_TYPES)
    assert literal_types(le.AccountFrame) == set(le.ACCOUNT_EVENT_TYPES)


def test_frames_carry_no_content_fields() -> None:
    """ADR-037 §2: hints only. A name/email/token/title field on any frame is a breach."""
    banned = {"name", "email", "title", "body", "token", "payload", "description"}
    for model in MODELS:
        assert banned.isdisjoint(model.model_fields), model.__name__


def test_channel_name_is_structural() -> None:
    scope = uuid.UUID("11111111-1111-4111-8111-111111111111")
    assert le.channel_name("team", scope) == f"solus:live:team:{scope}"


def test_the_field_manifest_is_current() -> None:
    path = FIXTURES / "_fields.json"
    expected = {m.__name__: sorted(m.model_fields) for m in MODELS}
    committed = json.loads(path.read_text()) if path.is_file() else None
    if committed != expected:
        path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    assert committed == expected, f"{path} was stale and has been regenerated; commit it"
