"""SOLUS-FND-09 — Foundation integration checkpoint (SOLUSDEV-89).

A scripted end-to-end proof of the foundation path, in ticket order:

    signup/verify -> create team -> invite + accept -> create project -> credited op

with assertions on subscription state, the credit ledger, and cross-team scope.

WHAT RUNS TODAY vs. WHAT IS BLOCKED
-----------------------------------
The signup->team->invite->project path and the scope-isolation checks run fully
against the shipped Phase 1 foundation (API.md §8 Phase 1).

The "credited model operation" half of the gate — running a metered op and
asserting the credit ledger deducts — depends on the metered layer that is
**Phase 5 and not yet deployed**: the SOL Agent (§2.9), the usage/credit ledger
(§2.14, ADR-018/019), and MO-03 cost tracking. ``reasoning/agent`` is an empty
stub and no credit/usage router exists. That test therefore **feature-detects and
skips with a BLOCKING message** rather than passing silently. The skip is the
gate's honest readout: this half cannot be signed off until Phase 5 ships. See
``docs/qa/COWORK_QA_foundation_path.md`` for the filing.

Auth note (ADR-009): Solus exposes no signup/verify endpoints — those happen
against Supabase. The Solus-side equivalent, asserted here, is that the first
authenticated request auto-provisions the user and their personal team.

Run it:
    # in-process (default; green in CI)
    uv run pytest tests/e2e/foundation_path.py -v
    # against deployed staging
    SOLUS_E2E_BASE_URL=https://staging.example \
      SOLUS_E2E_TOKEN_ALICE=... SOLUS_E2E_TOKEN_BOB=... SOLUS_E2E_TOKEN_CAROL=... \
      uv run pytest tests/e2e/foundation_path.py -v
"""

from collections.abc import Callable
from typing import Any, Protocol

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


class Identity(Protocol):
    """Structural view of the identities produced by the ``get_identity`` fixture
    (see conftest). Kept local to avoid a cross-package conftest import."""

    name: str
    sub: str
    email: str
    headers: dict[str, str]


async def _provision(client: AsyncClient, identity: Identity) -> dict[str, Any]:
    """First authenticated call — the ADR-009 auto-provision (the signup/verify
    equivalent). Returns the ``/users/me`` data payload."""
    r = await client.get("/api/v1/users/me", headers=identity.headers)
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()["data"]
    return data


async def test_foundation_path_signup_to_project(
    client: AsyncClient,
    get_identity: Callable[[str], Identity],
    unique_name: Callable[[str], str],
) -> None:
    """The full happy path: identity -> team -> invite+accept -> project."""
    alice = get_identity("alice")
    bob = get_identity("bob")

    # Step 1 — "signup + verify": an authenticated identity (Supabase JWT) makes
    # its first call; Solus auto-provisions the user + a personal team.
    me = await _provision(client, alice)
    assert me["email"] == alice.email
    personal = [t for t in me["teams"] if t["is_personal"]]
    assert len(personal) == 1, "first login must create exactly one personal team"
    # Subscription state: placeholder trial until ADR-017 billing (Phase 5).
    assert personal[0]["plan_status"] == "trial"
    assert personal[0]["trial_ends_at"] is not None
    assert personal[0]["role"] == "owner"

    # Step 2 — create a (shared) team.
    r = await client.post(
        "/api/v1/teams", headers=alice.headers, json={"name": unique_name("Rover Lab")}
    )
    assert r.status_code == 201, r.text
    team = r.json()["data"]
    team_id = team["id"]
    assert team["role"] == "owner"
    assert team["is_personal"] is False

    # Step 3 — invite Bob. The invite must target Bob's real identity email so
    # acceptance is authorized; the token is returned once, here.
    r = await client.post(
        f"/api/v1/teams/{team_id}/invites",
        headers=alice.headers,
        json={"email": bob.email, "role": "member"},
    )
    assert r.status_code == 201, r.text
    invite = r.json()["data"]
    invite_token = invite["token"]
    assert invite_token, "invite token is returned once at creation"
    assert invite["role"] == "member"
    assert invite["status"] == "pending"

    # Step 4 — Bob provisions, then accepts the invite.
    await _provision(client, bob)
    r = await client.post(f"/api/v1/invites/{invite_token}/accept", headers=bob.headers)
    assert r.status_code == 200, r.text
    acceptance = r.json()["data"]
    assert acceptance["team_id"] == team_id
    assert acceptance["role"] == "member"

    # Bob now appears in the members list with the member role.
    r = await client.get(f"/api/v1/teams/{team_id}/members", headers=alice.headers)
    assert r.status_code == 200, r.text
    members = {m["email"]: m["role"] for m in r.json()["data"]}
    assert members.get(bob.email) == "member"

    # Step 5 — create a project under the team.
    r = await client.post(
        f"/api/v1/teams/{team_id}/projects",
        headers=alice.headers,
        json={"name": "Rover MK2", "description": "six-wheel autonomous rover"},
    )
    assert r.status_code == 201, r.text
    project = r.json()["data"]
    project_id = project["id"]
    assert project["team_id"] == team_id

    # Bob (a member) can read the project — shared-team access works.
    r = await client.get(f"/api/v1/projects/{project_id}", headers=bob.headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["id"] == project_id


async def test_scope_holds_no_cross_team_leak(
    client: AsyncClient,
    get_identity: Callable[[str], Identity],
    unique_name: Callable[[str], str],
) -> None:
    """Cross-tenant isolation across the path: a non-member (Carol) can neither
    read nor mutate Alice's team/project. Non-membership returns 404 (no
    existence leak), never 200/403 — the highest-severity invariant (CLAUDE.md §7)."""
    alice = get_identity("alice")
    carol = get_identity("carol")
    await _provision(client, alice)
    await _provision(client, carol)

    r = await client.post(
        "/api/v1/teams", headers=alice.headers, json={"name": unique_name("Private Lab")}
    )
    assert r.status_code == 201, r.text
    team_id = r.json()["data"]["id"]
    r = await client.post(
        f"/api/v1/teams/{team_id}/projects",
        headers=alice.headers,
        json={"name": "Confidential Rover"},
    )
    assert r.status_code == 201, r.text
    project_id = r.json()["data"]["id"]

    # Carol cannot see the team or project.
    r = await client.get(f"/api/v1/teams/{team_id}", headers=carol.headers)
    assert r.status_code == 404, f"cross-team read leaked: {r.status_code} {r.text}"
    r = await client.get(f"/api/v1/projects/{project_id}", headers=carol.headers)
    assert r.status_code == 404, f"cross-team read leaked: {r.status_code} {r.text}"

    # Carol cannot create a project in Alice's team.
    r = await client.post(
        f"/api/v1/teams/{team_id}/projects",
        headers=carol.headers,
        json={"name": "intrusion"},
    )
    assert r.status_code == 404, f"cross-team write leaked: {r.status_code} {r.text}"


async def test_credited_model_operation_deducts_credits(
    client: AsyncClient,
    get_identity: Callable[[str], Identity],
    unique_name: Callable[[str], str],
) -> None:
    """Gate AC 1–2: run a credited model op; assert the credit ledger deducts and
    usage/subscription state matches.

    BLOCKING GAP — the metered credit layer is Phase 5 and not deployed (SOL Agent
    §2.9; usage/credit ledger §2.14, ADR-018/019; MO-03 cost tracking). We
    feature-detect the endpoints and skip loudly so the gate readout records the
    gap. The forward-looking assertions below activate automatically once the
    endpoints exist.
    """
    alice = get_identity("alice")
    await _provision(client, alice)
    r = await client.post(
        "/api/v1/teams", headers=alice.headers, json={"name": unique_name("Credit Lab")}
    )
    assert r.status_code == 201, r.text
    team_id = r.json()["data"]["id"]
    r = await client.post(
        f"/api/v1/teams/{team_id}/projects",
        headers=alice.headers,
        json={"name": "Credited Ops"},
    )
    assert r.status_code == 201, r.text
    project_id = r.json()["data"]["id"]

    # Feature-detect the metered layer. The usage meter (§2.14) is the ledger
    # read; the agent conversation (§2.9) is the credited op that should deduct.
    usage_before = await client.get("/api/v1/users/me/usage", headers=alice.headers)
    convo = await client.post(
        f"/api/v1/projects/{project_id}/agent/conversations",
        headers=alice.headers,
        json={"message": "Diagnose this project."},
    )

    if usage_before.status_code == 404 or convo.status_code == 404:
        pytest.skip(
            "BLOCKING (gate): metered credit layer not deployed. The SOL Agent "
            "(API.md §2.9) and the usage/credit ledger (§2.14, ADR-018/019, MO-03 "
            "cost tracking) are Phase 5. Cannot verify 'credit deducts correctly' "
            "or 'webhook/DB state matches'. File as a blocking bug before gate "
            "sign-off — see docs/qa/COWORK_QA_foundation_path.md."
        )

    # --- Activates when Phase 5 lands ---
    assert convo.status_code in (200, 201, 202), convo.text
    before = usage_before.json()["data"]
    usage_after = await client.get("/api/v1/users/me/usage", headers=alice.headers)
    assert usage_after.status_code == 200, usage_after.text
    after = usage_after.json()["data"]
    assert after["credits_used"] > before["credits_used"], "credited op did not deduct"
