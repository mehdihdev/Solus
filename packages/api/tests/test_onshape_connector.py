"""The Onshape connector — thin REST acquisition + the shared CAD parser (CAD-01).

`docs/contracts/metadata-extraction.md` §2 fixes the shape of this connector:

> **Thin API** — auth + detect change + fetch/generate STEP/STL export → shared
> parser. Onshape is **NOT** a deep live-API integration.

So the tests here cover exactly that surface: OAuth (including the 60-minute
token refresh Onshape forces), microversion change detection, the
translation → poll → download export dance, and the hand-off into
`parse_step` + `build_mechanical_graph`. No network: every call is respx-mocked.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx
from fixtures.onshape_sample import (
    CURRENT_MICROVERSION,
    CURRENT_MICROVERSION_NEXT,
    PARTS_METADATA,
    SESSION_INFO,
    STEP_EXPORT,
    TRANSLATION_ACTIVE,
    TRANSLATION_DONE,
    TRANSLATION_FAILED,
    TRANSLATION_STARTED,
)
from solus_api.connectors.conformance import assert_connector_contract
from solus_api.connectors.contracts import (
    NO_SIGNAL_CODES,
    AuthKind,
    ConnectorError,
    Credentials,
    Domain,
    SyncContext,
)
from solus_api.connectors.onshape import (
    ONSHAPE_API_BASE,
    ONSHAPE_MAX_PAGE_LIMIT,
    ONSHAPE_OAUTH_BASE,
    OnshapeConnector,
)

DID, WID, EID = "d1", "w1", "e1"
#: CAD-01 config named ONE element by its three ids. Kept as the default fixture
#: because the read-time legacy shim must go on working (see
#: `test_legacy_three_id_config_still_syncs`).
CONFIG = {"document_id": DID, "workspace_id": WID, "element_id": EID}
#: Entity keys are namespaced by (document, element) now that one source spans
#: many documents.
SCOPE = f"{DID}:{EID}"

from conftest import requires_occt as _requires_occt  # noqa: E402  (single definition)

requires_occt: pytest.MarkDecorator = _requires_occt


def _connector() -> OnshapeConnector:
    return OnshapeConnector(client_id="cid", client_secret="csecret")


def _ctx(cursor: dict[str, object] | None = None) -> SyncContext:
    return SyncContext(
        credentials=Credentials(token="access", refresh_token="refresh"),
        config=dict(CONFIG),
        cursor=dict(cursor or {}),
    )


def _mock_export(poll_payloads: list[Any] | None = None) -> None:
    """Wire the full acquisition path: microversion → translate → poll → download."""
    respx.get(f"{ONSHAPE_API_BASE}/api/users/sessioninfo").mock(
        return_value=httpx.Response(200, json=SESSION_INFO)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION)
    )
    respx.post(f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/w/{WID}/e/{EID}/translations").mock(
        return_value=httpx.Response(200, json=TRANSLATION_STARTED)
    )
    payloads = poll_payloads or [TRANSLATION_DONE]
    respx.get(f"{ONSHAPE_API_BASE}/api/v8/translations/translation-req-1").mock(
        side_effect=[httpx.Response(200, json=p) for p in payloads]
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/externaldata/external-data-1").mock(
        return_value=httpx.Response(200, text=STEP_EXPORT)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/parts/d/{DID}/w/{WID}/e/{EID}").mock(
        return_value=httpx.Response(200, json=PARTS_METADATA)
    )


# --------------------------------------------------------------- metadata


def test_provider_metadata_matches_the_source_type() -> None:
    connector = _connector()

    assert connector.provider == "onshape"
    assert connector.auth_kind is AuthKind.OAUTH
    # EMPTY: the OAuth grant is account-level, so connecting requires no typed
    # config at all. What to track is a SELECTION made after connect.
    assert connector.config_fields == ()
    assert connector.selection == {
        "mode": "multi",
        "config_key": "documents",
        "label": "document",
    }


def test_is_oauth_only_so_a_pat_cannot_bypass_the_flow() -> None:
    """An API key pair acts as the DEVELOPER and reaches only our own documents,
    so the token-connect path must stay shut for Onshape (CLAUDE.md §7)."""
    assert _connector().supports_token_connect is False


def test_requests_read_scope_only() -> None:
    """Security review MED-5: every operation is a read (the translation POST
    sets storeInDocument=False), so asking customers to grant mutate rights over
    their CAD would be unearned blast radius on a leaked token."""
    assert _connector().scopes == ("OAuth2Read",)


# --------------------------------------------------------------- oauth


def test_authorize_url_targets_onshapes_oauth_host() -> None:
    url = _connector().authorize_url(state="st4te", redirect_uri="http://localhost:9999/cb")

    assert url.startswith(f"{ONSHAPE_OAUTH_BASE}/oauth/authorize?")
    assert "client_id=cid" in url
    assert "response_type=code" in url
    assert "state=st4te" in url
    assert "OAuth2Read" in url


def test_authorize_url_refuses_when_oauth_is_unconfigured() -> None:
    connector = OnshapeConnector(client_id="", client_secret="")

    with pytest.raises(ConnectorError) as excinfo:
        connector.authorize_url(state="s", redirect_uri="http://localhost/cb")

    assert excinfo.value.code == "oauth_not_configured"


@respx.mock
async def test_exchange_code_returns_both_tokens() -> None:
    respx.post(f"{ONSHAPE_OAUTH_BASE}/oauth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
        )
    )

    creds = await _connector().exchange_code(code="c0de", redirect_uri="http://localhost/cb")

    assert creds.token == "at"
    assert creds.refresh_token == "rt"


@respx.mock
async def test_exchange_code_failure_is_a_typed_error() -> None:
    respx.post(f"{ONSHAPE_OAUTH_BASE}/oauth/token").mock(return_value=httpx.Response(400))

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().exchange_code(code="bad", redirect_uri="http://localhost/cb")

    assert excinfo.value.code == "oauth_exchange_failed"


@respx.mock
async def test_refresh_returns_the_rotated_refresh_token() -> None:
    """Onshape rotates the refresh token on every use — the connector must
    surface the new one so the runtime can persist it."""
    route = respx.post(f"{ONSHAPE_OAUTH_BASE}/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "at2", "refresh_token": "rt2"})
    )

    creds = await _connector().refresh_credentials(Credentials(token="old", refresh_token="rt1"))

    assert (creds.token, creds.refresh_token) == ("at2", "rt2")
    assert "grant_type=refresh_token" in route.calls[0].request.content.decode()


@respx.mock
async def test_refresh_failure_is_a_typed_error() -> None:
    respx.post(f"{ONSHAPE_OAUTH_BASE}/oauth/token").mock(return_value=httpx.Response(401))

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().refresh_credentials(Credentials(token="o", refresh_token="rt"))

    assert excinfo.value.code == "oauth_refresh_failed"


async def test_refresh_without_a_stored_refresh_token_fails_fast() -> None:
    with pytest.raises(ConnectorError) as excinfo:
        await _connector().refresh_credentials(Credentials(token="o"))

    assert excinfo.value.code == "oauth_refresh_failed"


@respx.mock
async def test_validate_credentials_reports_the_onshape_identity() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/users/sessioninfo").mock(
        return_value=httpx.Response(200, json=SESSION_INFO)
    )

    account = await _connector().validate_credentials(Credentials(token="at"))

    assert account.external_id == SESSION_INFO["id"]
    assert account.login


@respx.mock
async def test_expired_token_surfaces_as_invalid_credentials() -> None:
    """The exact code the runtime's refresh-and-retry seam keys off."""
    respx.get(f"{ONSHAPE_API_BASE}/api/users/sessioninfo").mock(return_value=httpx.Response(401))

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().validate_credentials(Credentials(token="stale"))

    assert excinfo.value.code == "invalid_credentials"


# --------------------------------------------------------------- change detection


@respx.mock
async def test_detect_changes_is_false_when_the_microversion_is_unchanged() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION)
    )

    changed = await _connector().detect_changes(_ctx({"microversion": "abc123def456"}))

    assert changed is False


@respx.mock
async def test_detect_changes_is_true_when_the_microversion_moves() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION_NEXT)
    )

    changed = await _connector().detect_changes(_ctx({"microversion": "abc123def456"}))

    assert changed is True


@respx.mock
async def test_the_probe_costs_one_call_once_the_workspace_is_known() -> None:
    """SOLUSDEV-167. The microversion URL needs a workspace id, and resolving it
    was a second `GET /documents/{did}` on EVERY probe — for a value that never
    changes. Against an ANNUAL 2,500-call allowance that doubling is the whole
    difference between affordable and not, so it is asserted as a call count.
    """
    mv = respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION)
    )
    workspace = respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/{DID}").mock(
        return_value=httpx.Response(200, json={"defaultWorkspace": {"id": WID}})
    )
    ctx = SyncContext(
        credentials=Credentials(token="at"),
        config={"documents": [DID]},
        cursor={"microversions": {DID: "abc123def456"}, "workspaces": {DID: WID}},
    )

    assert await _connector().detect_changes(ctx) is False

    assert mv.call_count == 1
    assert workspace.call_count == 0, "re-resolved a workspace the cursor already knew"


@respx.mock
async def test_the_probe_re_resolves_a_stale_workspace_before_declaring_gone() -> None:
    """A remembered workspace that 404s must not tombstone a live document: the
    probe re-resolves once and retries."""
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/stale/currentmicroversion").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/{DID}").mock(
        return_value=httpx.Response(200, json={"defaultWorkspace": {"id": WID}})
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION_NEXT)
    )
    ctx = SyncContext(
        credentials=Credentials(token="at"),
        config={"documents": [DID]},
        cursor={"microversions": {DID: "old"}, "workspaces": {DID: "stale"}},
    )

    assert await _connector().detect_changes(ctx) is True


@respx.mock
async def test_a_402_is_quota_exhausted_not_a_generic_api_error() -> None:
    """SOLUSDEV-167. Onshape answers 402 when the account's ANNUAL allowance is
    spent. It had no branch, so it read as `api_error` — which `detect_changes`
    swallowed into "changed", enqueuing a full sync. Being out of quota must
    never buy more requests, so it is its own terminal, no-signal code."""
    respx.get(f"{ONSHAPE_API_BASE}/api/users/sessioninfo").mock(return_value=httpx.Response(402))

    with pytest.raises(ConnectorError) as caught:
        await _connector().validate_credentials(Credentials(token="at"))

    assert caught.value.code == "quota_exhausted"
    assert caught.value.code in NO_SIGNAL_CODES


@requires_occt
@respx.mock
async def test_the_translation_poll_backs_off_instead_of_spending_a_call_a_second() -> None:
    """The dominant per-sync cost. A flat 1 s interval over 30 attempts meant up
    to 30 QUOTA-COUNTED GETs per assembly; backing off makes a slow translation
    cost a handful. Asserted as a CALL COUNT, since that is what the quota
    charges for."""
    _mock_export(poll_payloads=[TRANSLATION_ACTIVE] * 6 + [TRANSLATION_DONE])
    connector = OnshapeConnector(client_id="cid", client_secret="csecret", poll_interval=0.0)

    await connector.sync(_ctx())

    polls = respx.calls.call_count and sum(
        1 for call in respx.calls if "/api/v8/translations/" in call.request.url.path
    )
    assert polls == 7, f"expected the scripted 7 polls, saw {polls}"
    # The knob that bounds the worst case, asserted so a future edit cannot
    # quietly restore a 30-deep flat poll.
    assert connector._poll_attempts <= 10


@respx.mock
async def test_detect_changes_reraises_a_transport_error_as_no_signal() -> None:
    """SOLUSDEV-167: "we could not ask" is not "it changed".

    This used to return True, so an unreachable API enqueued a FULL export. With
    a rate limit that is an amplifier — being throttled bought more upstream
    traffic. The probe now re-raises the no-signal codes so the sweep can skip
    and ask again; a user's own explicit sync is unaffected, because the gate in
    `run_sync` treats any probe failure as "go sync".
    """
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        side_effect=httpx.ConnectError("boom")
    )

    with pytest.raises(ConnectorError) as caught:
        await _connector().detect_changes(_ctx({"microversion": "x"}))
    assert caught.value.code == "api_unreachable"
    assert caught.value.code in NO_SIGNAL_CODES


@respx.mock
async def test_detect_changes_defers_on_an_ambiguous_error() -> None:
    """An ambiguous failure cannot spend quota on an export without change evidence."""
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(500)
    )

    with pytest.raises(ConnectorError):
        await _connector().detect_changes(_ctx({"microversion": "x"}))


async def test_an_empty_selection_is_a_connected_idle_source_not_an_error() -> None:
    """Selecting nothing is valid: the account is connected, nothing is tracked."""
    ctx = SyncContext(credentials=Credentials(token="at"), config={}, cursor={})

    result = await _connector().sync(ctx)

    assert result.entities == []
    assert result.relations == []
    assert result.cursor == {"microversions": {}, "workspaces": {}}


@pytest.mark.parametrize("bad", [{"documents": "d1"}, {"documents": [1]}, {"documents": ["../x"]}])
async def test_a_malformed_selection_is_a_typed_error_not_a_key_error(
    bad: dict[str, object],
) -> None:
    ctx = SyncContext(credentials=Credentials(token="at"), config=bad, cursor={})

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(ctx)

    assert excinfo.value.code == "config_invalid"


async def test_an_oversized_selection_is_refused() -> None:
    connector = OnshapeConnector(client_id="c", client_secret="s", max_documents=2)
    ctx = SyncContext(
        credentials=Credentials(token="at"), config={"documents": ["a", "b", "c"]}, cursor={}
    )

    with pytest.raises(ConnectorError) as excinfo:
        await connector.sync(ctx)

    assert excinfo.value.code == "config_invalid"


@pytest.mark.parametrize("bad", ["../etc", "d1/w1", "d 1", "d1?x=1"])
async def test_config_ids_are_validated_before_url_interpolation(bad: str) -> None:
    """Ingested config is untrusted input — an id with a path separator must not
    be able to reshape the request URL (CLAUDE.md §7)."""
    ctx = SyncContext(
        credentials=Credentials(token="at"),
        config={"document_id": bad, "workspace_id": WID, "element_id": EID},
        cursor={},
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(ctx)

    assert excinfo.value.code == "config_invalid"


# --------------------------------------------------------------- sync


@requires_occt
@respx.mock
async def test_sync_lands_the_assembly_tree_in_the_graph() -> None:
    _mock_export()

    result = await _connector().sync(_ctx())

    assert {e.source_key for e in result.entities} == {
        f"{DID}:document",
        f"{SCOPE}:Bracket",
        f"{SCOPE}:Bracket/BasePlate",
        f"{SCOPE}:Bracket/PegPair",
        f"{SCOPE}:Bracket/PegPair/Peg[0]",
        f"{SCOPE}:Bracket/PegPair/Peg[1]",
    }
    assert all(e.domain is Domain.MECHANICAL for e in result.entities)
    assert {r.type for r in result.relations} == {"part_of", "contains"}
    wrappers = [r for r in result.relations if r.type == "contains"]
    assert [(r.from_key, r.to_key) for r in wrappers] == [(f"{DID}:document", f"{SCOPE}:Bracket")]


@requires_occt
@respx.mock
async def test_sync_cursors_on_the_microversion() -> None:
    _mock_export()

    result = await _connector().sync(_ctx())

    assert result.cursor["microversions"] == {DID: "abc123def456"}


@requires_occt
@respx.mock
async def test_part_numbers_from_metadata_reach_the_fingerprint_channel() -> None:
    """STEP carries no MPN; Onshape's parts metadata does. This join is the whole
    reason a CAD part can ever collapse onto its schematic symbol (D-D)."""
    _mock_export()

    by_key = {e.source_key: e for e in (await _connector().sync(_ctx())).entities}

    assert by_key[f"{SCOPE}:Bracket/BasePlate"].modality_hints["part_number"] == "AL-6061-PLATE"
    assert by_key[f"{SCOPE}:Bracket/PegPair/Peg[0]"].modality_hints["part_number"] == "DIN-912-M4"
    # Both occurrences of one product carry the same MPN.
    assert by_key[f"{SCOPE}:Bracket/PegPair/Peg[1]"].modality_hints["part_number"] == "DIN-912-M4"


@requires_occt
@respx.mock
async def test_an_empty_part_number_is_never_invented() -> None:
    _mock_export()

    by_key = {e.source_key: e for e in (await _connector().sync(_ctx())).entities}

    assert "part_number" not in by_key[f"{SCOPE}:Bracket"].modality_hints


@requires_occt
@respx.mock
async def test_material_from_metadata_rides_properties() -> None:
    _mock_export()

    by_key = {e.source_key: e for e in (await _connector().sync(_ctx())).entities}

    assert by_key[f"{SCOPE}:Bracket/BasePlate"].properties["material"] == "Aluminium 6061"


@requires_occt
@respx.mock
async def test_sync_polls_until_the_translation_completes() -> None:
    _mock_export([TRANSLATION_ACTIVE, TRANSLATION_ACTIVE, TRANSLATION_DONE])

    result = await _connector().sync(_ctx())

    assert result.entities


@respx.mock
async def test_a_failed_translation_is_a_typed_error() -> None:
    _mock_export([TRANSLATION_FAILED])

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(_ctx())

    assert excinfo.value.code == "export_unavailable"


@respx.mock
async def test_a_translation_that_never_finishes_gives_up_bounded() -> None:
    """No unbounded poll loop against a third-party API (CLAUDE.md §7)."""
    connector = OnshapeConnector(client_id="cid", client_secret="csecret", poll_attempts=3)
    _mock_export([TRANSLATION_ACTIVE] * 3)

    with pytest.raises(ConnectorError) as excinfo:
        await connector.sync(_ctx())

    assert excinfo.value.code == "export_timeout"


@respx.mock
async def test_a_rate_limited_request_is_retried_after_the_wait() -> None:
    """Onshape rate-caps private OAuth apps, so a 429 is an expected operating
    condition — the call retries after the server's wait instead of failing."""
    respx.get(f"{ONSHAPE_API_BASE}/api/users/sessioninfo").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=SESSION_INFO),
        ]
    )

    account = await _connector().validate_credentials(
        Credentials(token="access", refresh_token="refresh")
    )

    assert account.external_id


@respx.mock
async def test_rate_limiting_that_never_lifts_is_a_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bounded retries (§7 — never an unbounded loop against a third-party API),
    then a `rate_limited` error the UI can render as 'try again shortly' rather
    than a generic API failure."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION)
    )
    respx.post(f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/w/{WID}/e/{EID}/translations").mock(
        return_value=httpx.Response(429)
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(_ctx())

    assert excinfo.value.code == "rate_limited"


@respx.mock
async def test_the_retry_wait_honors_but_bounds_the_retry_after_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry-After is untrusted upstream input: honored when sane, capped always,
    so a hostile header can never park a sync worker."""
    waits: list[float] = []

    async def _record(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr("asyncio.sleep", _record)
    respx.get(f"{ONSHAPE_API_BASE}/api/users/sessioninfo").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "999999"}),
            httpx.Response(200, json=SESSION_INFO),
        ]
    )

    await _connector().validate_credentials(Credentials(token="access", refresh_token="refresh"))

    assert waits and all(wait <= 30.0 for wait in waits)


@requires_occt
@respx.mock
async def test_a_rate_limited_download_is_retried() -> None:
    """The externaldata download sits outside `request()`, so it carries its own
    429 handling — a transient cap must not abort a sync whose translation
    already succeeded."""
    _mock_export()
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/externaldata/external-data-1").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, text=STEP_EXPORT),
        ]
    )

    result = await _connector().sync(_ctx())

    assert result.entities


async def _no_sleep(_delay: float) -> None:
    return None


@respx.mock
async def test_expired_token_during_sync_is_invalid_credentials() -> None:
    """Lets the runtime refresh and retry rather than recording a hard failure."""
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(401)
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(_ctx())

    assert excinfo.value.code == "invalid_credentials"


@respx.mock
async def test_an_oversized_export_is_refused_before_parsing() -> None:
    from solus_api.connectors.mechanical import MAX_CAD_EXPORT_BYTES

    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION)
    )
    respx.post(f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/w/{WID}/e/{EID}/translations").mock(
        return_value=httpx.Response(200, json=TRANSLATION_STARTED)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v8/translations/translation-req-1").mock(
        return_value=httpx.Response(200, json=TRANSLATION_DONE)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/externaldata/external-data-1").mock(
        return_value=httpx.Response(200, text="x" * (MAX_CAD_EXPORT_BYTES + 1))
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(_ctx())

    assert excinfo.value.code == "export_too_large"


@requires_occt
@respx.mock
async def test_passes_the_connector_conformance_suite() -> None:
    _mock_export()

    await assert_connector_contract(_connector(), _ctx())


@requires_occt
@respx.mock
async def test_metadata_failure_degrades_rather_than_failing_the_sync() -> None:
    """Structure is the point; part numbers are an enrichment. Losing the
    metadata call must not cost the team their assembly tree."""
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION)
    )
    respx.post(f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/w/{WID}/e/{EID}/translations").mock(
        return_value=httpx.Response(200, json=TRANSLATION_STARTED)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v8/translations/translation-req-1").mock(
        return_value=httpx.Response(200, json=TRANSLATION_DONE)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/externaldata/external-data-1").mock(
        return_value=httpx.Response(200, text=STEP_EXPORT)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/parts/d/{DID}/w/{WID}/e/{EID}").mock(
        return_value=httpx.Response(500)
    )

    result = await _connector().sync(_ctx())

    assert len([e for e in result.entities if e.type == "part"]) == 5
    assert len([e for e in result.entities if e.type == "cad_document"]) == 1
    assert any("metadata" in e.message for e in result.errors)


@respx.mock
async def test_the_access_token_never_appears_in_an_error_message() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(500, text="upstream exploded")
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(_ctx())

    assert "access" not in excinfo.value.message


# --------------------------------------------------------------- hardening


@respx.mock
async def test_streaming_download_aborts_before_buffering_the_whole_body() -> None:
    """Buffering then measuring cannot work: the bound exists to stop a huge body
    exhausting the worker, and by the time `.content` is populated the damage is
    done. The stream must stop the moment the running total crosses the cap."""
    from solus_api.connectors.mechanical import MAX_CAD_EXPORT_BYTES

    chunk = b"x" * (1024 * 1024)

    class _EndlessStream(httpx.AsyncByteStream):
        """Yields far more than the cap and counts what was actually pulled — if
        the connector buffers before measuring, `drained` blows past the limit."""

        def __init__(self) -> None:
            self.drained = 0

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range((MAX_CAD_EXPORT_BYTES // len(chunk)) * 3):
                self.drained += len(chunk)
                yield chunk

    stream = _EndlessStream()

    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION)
    )
    respx.post(f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/w/{WID}/e/{EID}/translations").mock(
        return_value=httpx.Response(200, json=TRANSLATION_STARTED)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v8/translations/translation-req-1").mock(
        return_value=httpx.Response(200, json=TRANSLATION_DONE)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/externaldata/external-data-1").mock(
        return_value=httpx.Response(200, stream=stream)
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(_ctx())

    assert excinfo.value.code == "export_too_large"
    # Stopped promptly rather than draining three times the cap.
    assert stream.drained <= MAX_CAD_EXPORT_BYTES + len(chunk) * 2


@respx.mock
async def test_a_declared_oversized_content_length_is_refused_up_front() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION)
    )
    respx.post(f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/w/{WID}/e/{EID}/translations").mock(
        return_value=httpx.Response(200, json=TRANSLATION_STARTED)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v8/translations/translation-req-1").mock(
        return_value=httpx.Response(200, json=TRANSLATION_DONE)
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/externaldata/external-data-1").mock(
        return_value=httpx.Response(200, text="tiny", headers={"content-length": "999999999999"})
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(_ctx())

    assert excinfo.value.code == "export_too_large"


@requires_occt
@respx.mock
async def test_oversized_metadata_values_are_truncated_at_ingestion() -> None:
    """`properties`/`modality_hints` are unbounded dicts that flow into the graph
    AND into model context via `get_entity` — a 5 MB partNumber would be DB bloat
    and a token-cost channel sourced entirely from ingested content."""
    _mock_export()
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/parts/d/{DID}/w/{WID}/e/{EID}").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "name": "BasePlate",
                    "partNumber": "P" * 50_000,
                    "material": {"displayName": "M" * 50_000},
                }
            ],
        )
    )

    by_key = {e.source_key: e for e in (await _connector().sync(_ctx())).entities}
    plate = by_key[f"{SCOPE}:Bracket/BasePlate"]

    assert len(plate.modality_hints["part_number"]) < 200
    assert len(plate.properties["material"]) < 200


@respx.mock
async def test_an_unusable_upstream_id_is_refused_rather_than_interpolated() -> None:
    """Onshape-returned ids reach a request path just like config ids, so they
    get the same validation instead of being trusted for being ours-adjacent."""
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/{DID}/w/{WID}/currentmicroversion").mock(
        return_value=httpx.Response(200, json=CURRENT_MICROVERSION)
    )
    respx.post(f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/w/{WID}/e/{EID}/translations").mock(
        return_value=httpx.Response(200, json={"id": "../../admin", "requestState": "ACTIVE"})
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(_ctx())

    assert excinfo.value.code == "export_unavailable"


# ------------------------------------------------- account-level (multi-document)


def _mock_account_document(
    document_id: str,
    element_id: str,
    *,
    workspace_id: str = "wsA",
    microversion: str = "mv-1",
    part_studio_id: str | None = None,
    extra_elements: list[dict[str, Any]] | None = None,
) -> None:
    """Wire one document end to end for the account-level path: resolve default
    workspace → list elements → microversion → translate → poll → download.

    `part_studio_id` adds a PARTSTUDIO tab exported through the `/partstudios/`
    collection; `extra_elements` adds tabs that are NOT exportable, so a test can
    prove they are skipped rather than spending a translation job to fail.
    """
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/{document_id}").mock(
        return_value=httpx.Response(
            200, json={"id": document_id, "defaultWorkspace": {"id": workspace_id}}
        )
    )
    # `elementType`, not `type` — the connector reads the real Onshape key now
    # that the element family decides which collection the export posts to.
    elements: list[dict[str, Any]] = [{"id": element_id, "elementType": "ASSEMBLY"}]
    if part_studio_id:
        elements.append({"id": part_studio_id, "elementType": "PARTSTUDIO"})
    elements.extend(extra_elements or [])
    respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/documents/d/{document_id}/w/{workspace_id}/elements"
    ).mock(return_value=httpx.Response(200, json=elements))
    respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/documents/d/{document_id}/w/{workspace_id}/currentmicroversion"
    ).mock(return_value=httpx.Response(200, json={"microversion": microversion}))
    respx.post(
        f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{document_id}"
        f"/w/{workspace_id}/e/{element_id}/translations"
    ).mock(return_value=httpx.Response(200, json=TRANSLATION_STARTED))
    if part_studio_id:
        respx.post(
            f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/{document_id}"
            f"/w/{workspace_id}/e/{part_studio_id}/translations"
        ).mock(return_value=httpx.Response(200, json=TRANSLATION_STARTED))
        respx.get(
            f"{ONSHAPE_API_BASE}/api/v6/parts/d/{document_id}/w/{workspace_id}/e/{part_studio_id}"
        ).mock(return_value=httpx.Response(200, json=PARTS_METADATA))
    respx.get(f"{ONSHAPE_API_BASE}/api/v8/translations/translation-req-1").mock(
        return_value=httpx.Response(200, json=TRANSLATION_DONE)
    )
    respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/documents/d/{document_id}/externaldata/external-data-1"
    ).mock(return_value=httpx.Response(200, text=STEP_EXPORT))
    respx.get(
        f"{ONSHAPE_API_BASE}/api/v6/parts/d/{document_id}/w/{workspace_id}/e/{element_id}"
    ).mock(return_value=httpx.Response(200, json=PARTS_METADATA))


def _selection_ctx(document_ids: list[str], cursor: dict[str, Any] | None = None) -> SyncContext:
    return SyncContext(
        credentials=Credentials(token="access", refresh_token="refresh"),
        config={"documents": document_ids},
        cursor=dict(cursor or {}),
    )


@respx.mock
async def test_connecting_needs_no_typed_config_only_the_oauth_grant() -> None:
    """The whole point: `validate_credentials` never reads config, so OAuth alone
    produces a connected source with nothing to paste in."""
    respx.get(f"{ONSHAPE_API_BASE}/api/users/sessioninfo").mock(
        return_value=httpx.Response(200, json=SESSION_INFO)
    )

    account = await _connector().validate_credentials(Credentials(token="at"))

    assert account.login


@respx.mock
async def test_list_selectable_returns_the_accounts_documents() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {"id": "docA", "name": "Rover chassis", "owner": {"name": "Maya"}},
                    {"id": "docB", "name": "Arm", "owner": {"name": "Maya"}},
                ]
            },
        )
    )

    items = await _connector().list_selectable(Credentials(token="at"))

    assert [i["id"] for i in items] == ["docA", "docB"]
    assert items[0]["name"] == "Rover chassis"


@respx.mock
async def test_list_selectable_asks_for_no_more_than_onshape_allows() -> None:
    """Onshape caps `limit` at 20 on /documents and answers 400 above it — which
    is exactly how the picker failed against a real tenant."""
    route = respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    await _connector().list_selectable(Credentials(token="at"))

    limit = int(route.calls[0].request.url.params["limit"])
    assert 0 < limit <= ONSHAPE_MAX_PAGE_LIMIT


@respx.mock
async def test_a_rejected_document_listing_is_a_typed_error() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(400, json={})
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().list_selectable(Credentials(token="at"))

    assert excinfo.value.code == "api_error"
    # Upstream text is untrusted and never echoed (CLAUDE.md §7) — but the
    # endpoint and status must still be nameable from the message.
    assert "documents" in excinfo.value.message


@respx.mock
async def test_list_selectable_paging_is_bounded() -> None:
    """A `next` link that never ends must not loop forever against Onshape (§7)."""
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"id": "docA", "name": "A"}],
                "next": f"{ONSHAPE_API_BASE}/api/v6/documents?offset=1",
            },
        )
    )

    connector = OnshapeConnector(client_id="c", client_secret="s", max_document_pages=3)
    items = await connector.list_selectable(Credentials(token="at"))

    assert len(items) == 3  # one per page, then the page bound stops it


@respx.mock
async def test_list_selectable_skips_a_document_with_an_unusable_id() -> None:
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents").mock(
        return_value=httpx.Response(
            200, json={"items": [{"id": "../etc", "name": "evil"}, {"id": "docB", "name": "ok"}]}
        )
    )

    items = await _connector().list_selectable(Credentials(token="at"))

    assert [i["id"] for i in items] == ["docB"]


@requires_occt
@respx.mock
async def test_two_documents_sharing_a_part_name_never_collide_on_one_key() -> None:
    """The false-merge guard. STEP occurrence paths are unique only WITHIN an
    export; the runtime upserts on (source_id, external_ref). Without the
    per-document scope both documents' `Bracket` would become ONE graph row —
    a merge no fingerprint guard can see, because it happens at the key."""
    _mock_account_document("docA", "elemA")
    _mock_account_document("docB", "elemB")

    result = await _connector().sync(_selection_ctx(["docA", "docB"]))

    keys = [e.source_key for e in result.entities]
    assert len(keys) == len(set(keys)), "source_keys must be unique within a sync"
    assert "docA:elemA:Bracket" in keys
    assert "docB:elemB:Bracket" in keys


@requires_occt
@respx.mock
async def test_part_studios_are_ingested_alongside_assemblies() -> None:
    """SOLUSDEV-168. Part Studios are where people model and where FeatureScript
    lives, but element discovery asked Onshape for `elementType=ASSEMBLY`, so
    they never entered the graph at all — which is why the Onshape panel shows
    zero rows when it is open on one, and why there is nothing to @-mention."""
    _mock_account_document("docA", "elemA", part_studio_id="psA")

    result = await _connector().sync(_selection_ctx(["docA"]))

    scopes = {e.source_key.rsplit(":", 1)[0] for e in result.entities if e.type == "part"}
    assert scopes == {"docA:elemA", "docA:psA"}


@respx.mock
async def test_a_part_studio_translates_through_the_partstudios_collection() -> None:
    """The ONLY element-type-specific URL in the ingest path. Posting a Part
    Studio to `/assemblies/.../translations` 404s, so the collection segment has
    to follow the element's type rather than being hardcoded."""
    _mock_account_document("docA", "elemA", part_studio_id="psA")

    await _connector().sync(_selection_ctx(["docA"]))

    posted = {
        str(call.request.url.path)
        for call in respx.calls
        if call.request.method == "POST" and "translations" in str(call.request.url.path)
    }
    assert any("/api/v6/partstudios/d/docA/w/wsA/e/psA/translations" == p for p in posted), posted
    assert any("/api/v6/assemblies/d/docA/w/wsA/e/elemA/translations" == p for p in posted), posted


@respx.mock
async def test_element_discovery_costs_one_call_for_both_types() -> None:
    """`elementType` is single-valued, so asking for two types would mean two
    requests per document against an ANNUAL allowance. The filter is dropped and
    applied client-side instead — same one call, both families."""
    _mock_account_document("docA", "elemA", part_studio_id="psA")

    await _connector().sync(_selection_ctx(["docA"]))

    element_calls = [
        call for call in respx.calls if str(call.request.url.path).endswith("/elements")
    ]
    assert len(element_calls) == 1
    assert "elementType" not in str(element_calls[0].request.url)


@respx.mock
async def test_element_types_we_cannot_export_are_skipped() -> None:
    """A document holds drawings, BOMs and blobs too. Only the two families the
    mechanical parser can read are exported — anything else would spend a
    translation job to fail."""
    _mock_account_document(
        "docA", "elemA", extra_elements=[{"id": "bom1", "elementType": "BILLOFMATERIALS"}]
    )

    await _connector().sync(_selection_ctx(["docA"]))

    posted = " ".join(str(c.request.url.path) for c in respx.calls if c.request.method == "POST")
    assert "bom1" not in posted


@respx.mock
async def test_a_selection_too_large_to_snapshot_fails_instead_of_tombstoning() -> None:
    """Overflowing the element cap used to `return` a PARTIAL target list.

    Every document past the cap was then absent from `workspaces`, which `sync`
    reads as GONE — so it cursored `_GONE` and its entities were soft-deleted by
    the complete-snapshot rule, while the document was alive and untouched. The
    next `detect_changes` then compared that stored `_GONE` against a real
    microversion, found them different, and reported "changed" — forever. Silent
    data loss plus an endless re-sync loop, on an ANNUAL call allowance.

    `sync`'s own partial-failure rule already says a document that could not be
    fetched must never be silently omitted. A snapshot that cannot be complete
    must therefore fail rather than truncate.
    """
    _mock_account_document("docA", "elemA")
    _mock_account_document("docB", "elemB")
    connector = OnshapeConnector(client_id="cid", client_secret="csecret", max_elements=1)

    with pytest.raises(ConnectorError) as excinfo:
        await connector.sync(_selection_ctx(["docA", "docB"]))

    assert excinfo.value.code == "selection_too_large"
    # Names the cap and the remedy — this reaches the user on the source card.
    assert "1" in excinfo.value.message


@requires_occt
@respx.mock
async def test_a_selection_exactly_at_the_cap_still_syncs() -> None:
    """The cap is a bound, not an off-by-one refusal."""
    _mock_account_document("docA", "elemA")
    connector = OnshapeConnector(client_id="cid", client_secret="csecret", max_elements=1)

    result = await connector.sync(_selection_ctx(["docA"]))

    assert [e.source_key for e in result.entities]


@requires_occt
@respx.mock
async def test_each_entity_records_the_document_it_came_from() -> None:
    _mock_account_document("docA", "elemA")
    _mock_account_document("docB", "elemB")

    result = await _connector().sync(_selection_ctx(["docA", "docB"]))

    by_doc: dict[str, set[str]] = {}
    for entity in result.entities:
        by_doc.setdefault(entity.properties["document_id"], set()).add(entity.source_key)
    assert set(by_doc) == {"docA", "docB"}
    assert all(k.startswith("docA:") for k in by_doc["docA"])


@requires_occt
@respx.mock
async def test_resync_of_an_unchanged_selection_is_idempotent() -> None:
    _mock_account_document("docA", "elemA")

    first = await _connector().sync(_selection_ctx(["docA"]))
    second = await _connector().sync(_selection_ctx(["docA"]))

    assert [e.source_key for e in first.entities] == [e.source_key for e in second.entities]
    assert first.cursor == second.cursor


@requires_occt
@respx.mock
async def test_deselecting_a_document_drops_only_its_own_entities() -> None:
    """The runtime soft-deletes whatever is absent from the snapshot, so a
    narrowed selection must emit exactly the remaining document's keys — and
    nothing of the other document's."""
    _mock_account_document("docA", "elemA")
    _mock_account_document("docB", "elemB")

    both = await _connector().sync(_selection_ctx(["docA", "docB"]))
    narrowed = await _connector().sync(_selection_ctx(["docA"]))

    kept = {e.source_key for e in narrowed.entities}
    assert kept == {k for k in (e.source_key for e in both.entities) if k.startswith("docA:")}
    assert not any(k.startswith("docB:") for k in kept)


@requires_occt
@respx.mock
async def test_a_document_deleted_upstream_is_skipped_rather_than_failing_the_sync() -> None:
    """404 means GONE, so dropping it — and letting the runtime reconcile its
    entities away — is the correct reading."""
    _mock_account_document("docA", "elemA")
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/docGone").mock(
        return_value=httpx.Response(404, json={})
    )

    result = await _connector().sync(_selection_ctx(["docA", "docGone"]))

    assert any(k.startswith("docA:") for k in (e.source_key for e in result.entities))
    assert any("no longer available" in e.message for e in result.errors)


@respx.mock
async def test_a_transient_failure_aborts_rather_than_tombstoning_the_other_documents() -> None:
    """The dangerous case: `apply_sync_result` treats the result as a COMPLETE
    snapshot, so quietly omitting a document that merely failed would soft-delete
    its whole subtree. A non-404 failure must abort the sync instead."""
    _mock_account_document("docA", "elemA")
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/docFlaky").mock(
        return_value=httpx.Response(503, json={})
    )

    with pytest.raises(ConnectorError) as excinfo:
        await _connector().sync(_selection_ctx(["docA", "docFlaky"]))

    assert excinfo.value.code == "api_error"


@respx.mock
async def test_detect_changes_is_true_when_any_selected_document_moves() -> None:
    _mock_account_document("docA", "elemA", microversion="mv-1")
    _mock_account_document("docB", "elemB", microversion="mv-CHANGED")

    ctx = _selection_ctx(["docA", "docB"], {"microversions": {"docA": "mv-1", "docB": "mv-1"}})

    assert await _connector().detect_changes(ctx) is True


@respx.mock
async def test_detect_changes_is_false_when_every_document_is_unchanged() -> None:
    _mock_account_document("docA", "elemA", microversion="mv-1")
    _mock_account_document("docB", "elemB", microversion="mv-2")

    ctx = _selection_ctx(["docA", "docB"], {"microversions": {"docA": "mv-1", "docB": "mv-2"}})

    assert await _connector().detect_changes(ctx) is False


async def test_detect_changes_is_true_when_the_selection_itself_changed() -> None:
    """A newly picked document has no cursor entry, so it must schedule a sync
    without any API call at all."""
    ctx = _selection_ctx(["docA", "docNew"], {"microversions": {"docA": "mv-1"}})

    assert await _connector().detect_changes(ctx) is True


async def test_an_idle_source_with_nothing_selected_reports_no_change() -> None:
    ctx = _selection_ctx([], {"microversions": {}})

    assert await _connector().detect_changes(ctx) is False


# ------------------------------------------------- legacy (CAD-01) compatibility


@requires_occt
@respx.mock
async def test_legacy_three_id_config_still_syncs() -> None:
    """A source created under CAD-01 keeps working, pinned to its one element."""
    _mock_export()

    result = await _connector().sync(_ctx())

    assert {e.source_key for e in result.entities}
    assert result.cursor["microversions"] == {DID: "abc123def456"}


@respx.mock
async def test_legacy_scalar_cursor_is_read_as_a_one_document_map() -> None:
    """Otherwise every legacy source would re-sync once for nothing."""
    _mock_export()

    assert await _connector().detect_changes(_ctx({"microversion": "abc123def456"})) is False


async def test_a_new_selection_wins_over_stale_legacy_keys() -> None:
    ctx = SyncContext(
        credentials=Credentials(token="at"),
        config={**CONFIG, "documents": []},
        cursor={},
    )

    result = await _connector().sync(ctx)

    assert result.entities == []


@requires_occt
@respx.mock
async def test_a_document_holding_no_assemblies_still_gets_a_cursor_entry() -> None:
    """Otherwise the cursor's key set never matches the selection and
    `detect_changes` reports "changed" on every poll — an endless re-sync loop."""
    _mock_account_document("docA", "elemA")
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/docEmpty").mock(
        return_value=httpx.Response(200, json={"id": "docEmpty", "defaultWorkspace": {"id": "wsA"}})
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/docEmpty/w/wsA/elements").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/d/docEmpty/w/wsA/currentmicroversion").mock(
        return_value=httpx.Response(200, json={"microversion": "mv-empty"})
    )

    result = await _connector().sync(_selection_ctx(["docA", "docEmpty"]))

    assert set(result.cursor["microversions"]) == {"docA", "docEmpty"}


@requires_occt
@respx.mock
async def test_a_deleted_document_settles_instead_of_scheduling_syncs_forever() -> None:
    """A 404 document that stays selected must reach a STABLE cursor value, or
    detect_changes fails safe to True on every poll and the worker spins."""
    _mock_account_document("docA", "elemA")
    respx.get(f"{ONSHAPE_API_BASE}/api/v6/documents/docGone").mock(
        return_value=httpx.Response(404, json={})
    )

    result = await _connector().sync(_selection_ctx(["docA", "docGone"]))
    cursor = dict(result.cursor)

    assert set(cursor["microversions"]) == {"docA", "docGone"}
    assert await _connector().detect_changes(_selection_ctx(["docA", "docGone"], cursor)) is False


@respx.mock
async def test_identity_falls_back_to_the_account_id_when_the_scope_carries_no_pii() -> None:
    """`OAuth2Read` alone returns empty email/name (confirmed on a live tenant),
    and the old code invented "onshape-user" — which became the source's display
    name and told the user nothing about which account they had connected. The
    opaque account id is at least true and distinguishable."""
    respx.get(f"{ONSHAPE_API_BASE}/api/users/sessioninfo").mock(
        return_value=httpx.Response(
            200, json={"id": "6a6119601e205a332af613d8", "email": None, "name": None}
        )
    )

    account = await _connector().validate_credentials(Credentials(token="at"))

    assert account.external_id == "6a6119601e205a332af613d8"
    assert account.login == "6a6119601e205a332af613d8"
    assert "onshape-user" not in account.login
    assert account.name is None
