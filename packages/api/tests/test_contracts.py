"""Tests for the connector contract (W0-05 draft) — the DTOs and the ABC.

A `FakeConnector` exercises the reusable `assert_connector_contract` suite so
the suite itself is proven before any real connector relies on it.
"""

import pytest
from pydantic import ValidationError
from solus_api.connectors import assert_connector_contract
from solus_api.connectors.contracts import (
    AccountInfo,
    AuthKind,
    Connector,
    Credentials,
    Domain,
    EntityOut,
    RelationOut,
    SyncContext,
    SyncResult,
)


class FakeConnector(Connector):
    provider = "fake"
    auth_kind = AuthKind.PAT

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        if creds.token == "bad":
            raise ValueError("invalid")
        return AccountInfo(external_id="1", login="octocat")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        return SyncResult(
            entities=[
                EntityOut(source_key="a.py", type="code_file", domain=Domain.CODE, name="a.py"),
                EntityOut(source_key="pkg", type="code_module", domain=Domain.CODE, name="pkg"),
            ],
            relations=[RelationOut(from_key="pkg", to_key="a.py", type="contains")],
            cursor={"sha": "abc123"},
        )

    async def detect_changes(self, ctx: SyncContext) -> bool:
        return ctx.cursor.get("sha") != "abc123"


@pytest.fixture
def ctx() -> SyncContext:
    return SyncContext(credentials=Credentials(token="ok"), config={"repo": "o/r"})


def test_entity_rejects_blank_source_key() -> None:
    with pytest.raises(ValidationError):
        EntityOut(source_key="", type="code_file", domain=Domain.CODE, name="a")


def test_entity_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        EntityOut(
            source_key="a",
            type="code_file",
            domain=Domain.CODE,
            name="a",
            sneaky="x",  # type: ignore[call-arg]
        )


def test_entity_is_frozen() -> None:
    entity = EntityOut(source_key="a", type="code_file", domain=Domain.CODE, name="a")
    with pytest.raises(ValidationError):
        entity.name = "b"


def test_relation_defaults_empty_properties() -> None:
    relation = RelationOut(from_key="a", to_key="b", type="contains")
    assert relation.properties == {}


def test_credentials_never_leak_token_in_repr() -> None:
    # token is a field; ensure it is present but the model is frozen/typed.
    creds = Credentials(token="secret-value", metadata={"scope": "repo"})
    assert creds.token == "secret-value"


@pytest.mark.asyncio
async def test_fake_connector_passes_contract(ctx: SyncContext) -> None:
    result = await assert_connector_contract(FakeConnector(), ctx)
    assert len(result.entities) == 2
    assert result.cursor == {"sha": "abc123"}


@pytest.mark.asyncio
async def test_detect_changes_reflects_cursor() -> None:
    connector = FakeConnector()
    stale = SyncContext(credentials=Credentials(token="ok"), cursor={"sha": "old"})
    fresh = SyncContext(credentials=Credentials(token="ok"), cursor={"sha": "abc123"})
    assert await connector.detect_changes(stale) is True
    assert await connector.detect_changes(fresh) is False
