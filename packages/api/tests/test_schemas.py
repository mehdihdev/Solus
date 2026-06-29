"""Request schemas reject unknown fields (CLAUDE.md §7 input handling)."""

import pytest
from pydantic import ValidationError
from solus_api.schemas import (
    InviteCreate,
    MemberRoleUpdate,
    ProjectCreate,
    SettingsUpdate,
    TeamCreate,
    UserUpdate,
)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (UserUpdate, {"name": "x", "hax": 1}),
        (SettingsUpdate, {"sol_mode": "guide", "hax": 1}),
        (TeamCreate, {"name": "x", "hax": 1}),
        (MemberRoleUpdate, {"role": "member", "hax": 1}),
        (InviteCreate, {"email": "a@b.co", "hax": 1}),
        (ProjectCreate, {"name": "x", "hax": 1}),
    ],
)
def test_unknown_fields_rejected(model: type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model(**payload)


def test_invite_role_cannot_be_owner() -> None:
    with pytest.raises(ValidationError):
        InviteCreate(email="a@b.co", role="owner")  # type: ignore[arg-type]


def test_invite_email_validated() -> None:
    with pytest.raises(ValidationError):
        InviteCreate(email="not-an-email")


def test_team_name_not_blank() -> None:
    with pytest.raises(ValidationError):
        TeamCreate(name="   ")
