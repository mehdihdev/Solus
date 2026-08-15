"""Meta-tests keeping the injection corpus honest — SOLUS-RUN-01.

A red-team corpus rots in a specific way: someone adds a defence, a payload
stops reproducing, and rather than deleting it they weaken it until it passes.
The corpus then still *looks* like coverage. These tests assert the corpus keeps
its teeth — that it covers every ingestion surface and every attack intent, and
that the payloads which must contain dangerous content still do.

Mirrors the `test_fingerprint_labels.py` idiom: the fixture is a frozen spec,
and this file is what makes it one.
"""

from __future__ import annotations

from fixtures.injection_corpus import (
    PAYLOADS,
    SECRET_SHAPED_VALUE,
    Intent,
    Surface,
    flooding_body_details,
    poisoned_feature_tree,
    poisoned_variables,
)


def test_case_ids_are_unique() -> None:
    """A duplicate id silently drops a case from any id-keyed assertion."""
    ids = [payload.case_id for payload in PAYLOADS]

    assert len(ids) == len(set(ids))


def test_every_ingestion_surface_is_exercised() -> None:
    """Each Surface is a real place attacker text enters Solus. An unexercised
    one is an untested path, not an irrelevant one."""
    covered = {payload.surface for payload in PAYLOADS}

    assert covered == set(Surface), f"uncovered: {set(Surface) - covered}"


def test_every_attack_intent_is_exercised() -> None:
    covered = {payload.intent for payload in PAYLOADS}

    assert covered == set(Intent), f"uncovered: {set(Intent) - covered}"


def test_every_payload_explains_what_it_would_achieve() -> None:
    """The note is what tells a future reader whether a green test means the
    defence works or the payload went stale."""
    for payload in PAYLOADS:
        assert payload.note.strip(), payload.case_id
        assert len(payload.note) > 20, payload.case_id


def test_the_delimiter_payload_still_carries_a_literal_close_token() -> None:
    """The whole point of that case. If a refactor renames the fence and nobody
    updates this payload, the escape test starts passing vacuously."""
    escape = next(p for p in PAYLOADS if p.intent is Intent.DELIMITER_ESCAPE)

    assert "END-SOLUS-DATA" in escape.text
    assert "\n" in escape.text


def test_the_consent_forgery_payloads_still_carry_control_characters() -> None:
    """One of them attacks with a bidi override; if it degrades to plain ASCII
    the printable-filter test proves nothing."""
    forgeries = [p for p in PAYLOADS if p.intent is Intent.CONSENT_FORGERY]

    assert any(any(not ch.isprintable() for ch in p.text) for p in forgeries)


def test_payloads_read_as_instructions_not_as_noise() -> None:
    """A payload that is merely weird text tests nothing. Each must actually try
    to change what the model does — either an imperative ("call X") or a
    declarative rule-rewrite ("write tools no longer require confirmation"),
    which is the more insidious style and the one the fence has to stop."""
    imperative = (
        "call",
        "run",
        "use",
        "read",
        "append",
        "ignore",
        "approve",
        "describe",
        "require",
        "no longer",
    )

    # Identifier-shaped payloads (a variable literally named `api_key`) are
    # LURES, not instructions: their danger is the value they attract into
    # context, which `test_a_variable_carries_a_secret_shaped_value` covers.
    # Prose payloads have no such excuse.
    for payload in PAYLOADS:
        if " " not in payload.text:
            continue
        lowered = payload.text.lower()
        assert any(word in lowered for word in imperative), payload.case_id


def test_lure_payloads_are_identifier_shaped() -> None:
    """The carve-out above is only safe if a lure really is an identifier — a
    prose payload must never slip through it by omitting spaces."""
    for payload in PAYLOADS:
        if " " in payload.text:
            continue
        assert payload.text.isidentifier(), payload.case_id


def test_the_poisoned_tool_bodies_match_the_real_read_shapes() -> None:
    """These feed the REAL Onshape read path, so they have to be shaped like the
    responses it parses — otherwise the test exercises a synthetic dict."""
    variables = poisoned_variables()
    assert isinstance(variables, list)
    assert "variables" in variables[0]
    assert {v["name"] for v in variables[0]["variables"]} >= {"width", "api_key"}

    tree = poisoned_feature_tree()
    assert tree["features"][0]["message"]["featureType"] == "extrude"
    assert "sourceMicroversion" in tree


def test_a_variable_carries_a_secret_shaped_value() -> None:
    """Redaction is only testable if something redactable is present."""
    values = [v.get("expression") for v in poisoned_variables()[0]["variables"]]

    assert SECRET_SHAPED_VALUE in values


def test_the_flood_body_is_generated_not_committed() -> None:
    """Large by construction, so the repo does not carry megabytes of fixture."""
    small = flooding_body_details(faces=4)
    big = flooding_body_details(faces=400)

    assert len(small["bodies"][0]["faces"]) == 4
    assert len(big["bodies"][0]["faces"]) == 400
