"""The connector conformance suite proven both ways (W0-05 §10, Decision B).

A well-formed connector PASSES; deliberately-broken ones FAIL — proving the suite actually
catches the invariants that keep connectors parallelizable and the graph sound (unique
`source_key`s, intra-source-only relations) and guards the credential boundary (no plaintext
credential in `SyncContext.config`). This is the negative-path proof the suite is not a
rubber stamp. Pure unit — no DB. The suite is imported from the package, proving it ships
importable per contract §10.
"""

from typing import Any

import pytest
from solus_api.connectors import assert_connector_contract
from solus_api.connectors.contracts import (
    AccountInfo,
    Connector,
    Credentials,
    Domain,
    EntityOut,
    RelationOut,
    SyncContext,
    SyncResult,
)


def _ctx(config: dict[str, str] | None = None) -> SyncContext:
    return SyncContext(credentials=Credentials(token="ok"), config=config or {"repo": "o/r"})


def _entity(key: str, modality_hints: dict[str, Any] | None = None) -> EntityOut:
    return EntityOut(
        source_key=key,
        type="component",
        domain=Domain.ELECTRICAL,
        name=key,
        modality_hints=modality_hints or {},
    )


class _StubConnector(Connector):
    """Returns canned entities/relations, to drive the suite in both directions."""

    provider = "stub"

    def __init__(
        self,
        entities: list[EntityOut],
        relations: list[RelationOut],
        version: str = "v1",
    ) -> None:
        self._entities = entities
        self._relations = relations
        self._version = version

    async def validate_credentials(self, creds: Credentials) -> AccountInfo:
        return AccountInfo(external_id="1", login="octocat")

    async def sync(self, ctx: SyncContext) -> SyncResult:
        # SOLUSDEV-167: a non-empty cursor is part of the contract now, and this
        # stub is the reference implementation — so it models the real shape: a
        # change token round-tripped through the cursor.
        return SyncResult(
            entities=self._entities, relations=self._relations, cursor={"version": self._version}
        )

    async def detect_changes(self, ctx: SyncContext) -> bool:
        """The whole point of the contract: answer WITHOUT doing the sync."""
        return ctx.cursor.get("version") != self._version


async def test_wellformed_connector_passes() -> None:
    good = _StubConnector(
        entities=[_entity("U1"), _entity("R1")],
        relations=[RelationOut(from_key="U1", to_key="R1", type="soldered_to")],
    )
    result = await assert_connector_contract(good, _ctx())
    assert {e.source_key for e in result.entities} == {"U1", "R1"}


async def test_rejects_cross_source_relations() -> None:
    # A relation whose endpoint is not an entity this connector produced = a cross-source leak.
    bad = _StubConnector(
        entities=[_entity("U1")],
        relations=[RelationOut(from_key="U1", to_key="OTHER-CONNECTOR-PART", type="references")],
    )
    with pytest.raises(AssertionError):
        await assert_connector_contract(bad, _ctx())


async def test_rejects_duplicate_source_keys() -> None:
    bad = _StubConnector(entities=[_entity("U1"), _entity("U1")], relations=[])
    with pytest.raises(AssertionError):
        await assert_connector_contract(bad, _ctx())


async def test_rejects_a_credential_stashed_in_config() -> None:
    # `SyncContext.config` is free-form — the natural place a token accidentally lands. The suite
    # must scan its keys (substring match, so `client_secret` is caught too), never trusting the
    # connector. Credentials come from the secret store as `Credentials` (CLAUDE.md §7).
    good = _StubConnector(entities=[_entity("U1")], relations=[])
    for leaky in (
        {"token": "ghp_fake"},
        {"password": "x"},
        {"private_key": "x"},
        {"client_secret": "x"},
    ):
        with pytest.raises(AssertionError):
            await assert_connector_contract(good, _ctx(leaky))


def test_entityout_modality_hints_bridge_to_fingerprint() -> None:
    entity = _entity("U1", modality_hints={"part_number": "LM358"})
    assert entity.modality_hints["part_number"] == "LM358"  # feeds the fingerprint matcher (W0-06)
    assert _entity("U2").modality_hints == {}  # optional, default empty


# --------------------------------------------- SOLUSDEV-167: the anti-bespoke lever


async def test_rejects_a_connector_that_returns_no_cursor() -> None:
    """A connector with no cursor can never answer "nothing changed", so every
    sync pays full price forever. That is what emptied ~80% of an ANNUAL Onshape
    allowance in one afternoon, so it is a contract failure, not a style note."""

    class _Cursorless(_StubConnector):
        async def sync(self, ctx: SyncContext) -> SyncResult:
            return SyncResult(entities=self._entities, relations=self._relations)

    with pytest.raises(AssertionError, match="non-empty cursor"):
        await assert_connector_contract(_Cursorless(entities=[_entity("U1")], relations=[]), _ctx())


async def test_rejects_a_connector_that_always_reports_changed() -> None:
    """Handed the cursor its own sync just produced, a connector must say
    "unchanged". One that always says "changed" re-syncs on every sweep forever
    — the amplifier, expressed as a contract violation."""

    class _AlwaysChanged(_StubConnector):
        async def detect_changes(self, ctx: SyncContext) -> bool:
            return True

    with pytest.raises(AssertionError, match="must return False"):
        await assert_connector_contract(
            _AlwaysChanged(entities=[_entity("U1")], relations=[]), _ctx()
        )


async def test_rejects_a_connector_that_never_reports_changed() -> None:
    """The other failure: an empty cursor means "never synced" and must report
    changed, or a brand-new source never makes its first sync at all."""

    class _NeverChanged(_StubConnector):
        async def detect_changes(self, ctx: SyncContext) -> bool:
            return False

    with pytest.raises(AssertionError, match="must report changed"):
        await assert_connector_contract(
            _NeverChanged(entities=[_entity("U1")], relations=[]), _ctx()
        )
