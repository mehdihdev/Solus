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


# SOLUSDEV-317 — Home marks a local folder that is a clone of the project's
# GitHub/GitLab repo, so a local source exposes its NORMALISED remote (the sync
# cursor's `remote`/`host`, never the raw URL) and nothing else of the cursor.
def test_local_source_exposes_its_normalised_remote_only() -> None:
    from solus_api.models import Source, SourceStatus, SourceType
    from solus_api.schemas import serialize_source

    source = Source(
        type=SourceType.LOCAL,
        status=SourceStatus.CONNECTED,
        name="mehdi-mbp",
        config={"machine_name": "mehdi-mbp", "folder_name": "lerobot"},
        cursor={
            "remote": "mehdihdev/lerobot-arm",
            "host": "github",
            "branch": "main",
            "digest": "abc",
            "detected": [{"entity_key": "kicad:hw"}],
        },
    )
    data = serialize_source(source)
    assert data["remote"] == {"repo": "mehdihdev/lerobot-arm", "host": "github"}
    assert "cursor" not in data
    assert "digest" not in str(data)


@pytest.mark.parametrize(
    "cursor",
    [{}, {"remote": None, "host": None}, {"remote": "", "host": "github"}, {"remote": 3}],
)
def test_local_source_without_a_usable_remote_says_nothing(cursor: dict[str, object]) -> None:
    from solus_api.models import Source, SourceStatus, SourceType
    from solus_api.schemas import serialize_source

    source = Source(
        type=SourceType.LOCAL,
        status=SourceStatus.CONNECTED,
        name="m",
        config={},
        cursor=cursor,
    )
    assert "remote" not in serialize_source(source)


def test_non_local_sources_never_carry_a_remote() -> None:
    from solus_api.models import Source, SourceStatus, SourceType
    from solus_api.schemas import serialize_source

    source = Source(
        type=SourceType.GITHUB,
        status=SourceStatus.CONNECTED,
        name="fw",
        config={"repo": "org/fw"},
        cursor={"remote": "org/fw", "host": "github"},
    )
    assert "remote" not in serialize_source(source)
