"""Guards the human-owned solus-contracts Python package (SOLUSDEV-100 fix,
tier-2 approved in-session per ADR-032).

The package previously shipped an `__init__.py` importing a `connector` module
that did not exist, so `import solus_contracts` failed everywhere. These tests
pin (a) importability of every re-exported name and (b) shape parity with the
in-tree draft (`solus_api.connectors.contracts`) that implementations actually
import today — so the canonical package and the draft cannot drift apart
silently until the draft is formally retired.
"""

import solus_contracts
from solus_api.connectors import contracts as draft
from solus_api.models import Domain as ApiDomain


def test_all_declared_names_are_importable() -> None:
    for name in solus_contracts.__all__:
        assert getattr(solus_contracts, name, None) is not None, name


def test_entity_and_relation_shapes_match_the_draft() -> None:
    assert set(solus_contracts.EntityOut.model_fields) == set(draft.EntityOut.model_fields)
    assert set(solus_contracts.RelationOut.model_fields) == set(draft.RelationOut.model_fields)
    assert set(solus_contracts.SyncResult.model_fields) == set(draft.SyncResult.model_fields)
    assert set(solus_contracts.SyncContext.model_fields) == set(draft.SyncContext.model_fields)
    assert set(solus_contracts.Credentials.model_fields) == set(draft.Credentials.model_fields)
    assert set(solus_contracts.AccountInfo.model_fields) == set(draft.AccountInfo.model_fields)
    assert set(solus_contracts.SyncError.model_fields) == set(draft.SyncError.model_fields)


def test_domain_vocabulary_matches_adr027_canonical_set() -> None:
    from solus_contracts.connector import Domain as ContractDomain

    assert {d.value for d in ContractDomain} == {d.value for d in ApiDomain}


def test_auth_kinds_match_the_draft() -> None:
    assert {k.value for k in solus_contracts.AuthKind} == {k.value for k in draft.AuthKind}


def test_connector_abc_declares_the_w005_surface() -> None:
    abstract = solus_contracts.Connector.__abstractmethods__
    assert abstract == draft.Connector.__abstractmethods__
    oauth_abstract = solus_contracts.OAuthConnector.__abstractmethods__
    assert oauth_abstract == draft.OAuthConnector.__abstractmethods__


def test_connector_error_carries_stable_code() -> None:
    err = solus_contracts.ConnectorError("invalid_credentials", "nope")
    assert err.code == "invalid_credentials"
    assert str(err) == "nope"
