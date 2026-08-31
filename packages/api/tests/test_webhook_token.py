"""SOLUSDEV-167: the per-source webhook credential."""

from __future__ import annotations

from solus_api.connectors.webhook_token import (
    mint_webhook_token,
    token_matches,
    webhook_token_digest,
)


def test_only_the_digest_is_storable() -> None:
    token, digest = mint_webhook_token()

    assert token != digest
    assert digest == webhook_token_digest(token)
    assert len(digest) == 64


def test_a_source_with_no_registered_token_matches_nothing() -> None:
    """Fail closed: an unregistered source must not be pokeable by anyone who
    guesses its id."""
    token, _ = mint_webhook_token()

    assert token_matches(token, None) is False
    assert token_matches(token, "") is False


def test_a_wrong_token_does_not_match() -> None:
    _, digest = mint_webhook_token()
    other, _ = mint_webhook_token()

    assert token_matches(other, digest) is False


def test_the_right_token_matches() -> None:
    token, digest = mint_webhook_token()

    assert token_matches(token, digest) is True


def test_tokens_are_unique() -> None:
    tokens = {mint_webhook_token()[0] for _ in range(200)}

    assert len(tokens) == 200
