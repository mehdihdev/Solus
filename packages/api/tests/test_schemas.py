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


def test_existing_onshape_connection_never_displays_opaque_account_id() -> None:
    from solus_api.models import AccountConnection, ConnectionStatus, SourceType
    from solus_api.schemas import serialize_connection

    connection = AccountConnection(
        provider=SourceType.ONSHAPE,
        status=ConnectionStatus.CONNECTED,
        account_login="opaque-provider-id",
        account_external_id="opaque-provider-id",
    )
    assert serialize_connection(connection)["account_login"] == "Onshape account"


@pytest.mark.parametrize(
    ("stored_name", "display_name"),
    [("Onshape · opaque-provider-id", "Onshape account"), ("Arm CAD", "Arm CAD")],
)
def test_legacy_onshape_generated_source_name_is_readable(
    stored_name: str, display_name: str
) -> None:
    from solus_api.models import Source, SourceStatus, SourceType
    from solus_api.schemas import serialize_source

    source = Source(
        type=SourceType.ONSHAPE,
        status=SourceStatus.CONNECTED,
        name=stored_name,
        config={},
        account_login="opaque-provider-id",
        account_external_id="opaque-provider-id",
    )
    assert serialize_source(source)["name"] == display_name
    assert source.name == stored_name


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
