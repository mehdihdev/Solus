"""SOLUS-TU-04/TU-06 — the /api/v1/toolkb HTTP surface (Phase-4 hardened).

Structural properties under test: HTTP submissions are PINNED to the operator
tier (a client cannot pick its own trust tier, claim api_geometry/global
scope, or reach confidence 0.9); a client can never publish; rejected content
never echoes back in an error body — including bodies whose shape dies before
the guard; and GET serves published rows only, omitting any row that fails
CTR-05 re-validation without leaking its content. The GET is deliberately
team-unscoped — the store is cross-tenant BY DESIGN.
"""

from typing import Any

from httpx import AsyncClient
from solus_api.toolkb.guard import IngestContext, ingest
from solus_api.toolkb.schema import AcquisitionMethod
from sqlalchemy.ext.asyncio import AsyncSession

DOCS_CTX = IngestContext(
    acquired_via=AcquisitionMethod.DOCS,
    doc_url="https://docs.kicad.org/8.0/en/eeschema/eeschema.html",
)


def _entry_payload(**overrides: object) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "tool": "kicad",
        "version_range": ">=8.0 <9.0",
        "surface": "menu",
        "control_id": "kicad.eeschema.place_net_label",
        "label": "Add Net Label",
        "effect": "create_feature",
        "description": "Places a named net label on the current wire.",
        "invocation": {"menu_path": ["Place", "Net Label"], "shortcut": "L"},
        "locator": None,
        "provenance": "operator_authored",
    }
    entry.update(overrides)
    return entry


def _submission(**entry_overrides: object) -> dict[str, Any]:
    return {"entry": _entry_payload(**entry_overrides)}


async def test_unauthenticated_is_401(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/toolkb/entries", json=_submission())).status_code == 401
    assert (await client.get("/api/v1/toolkb/entries", params={"tool": "kicad"})).status_code == 401


async def test_unverified_email_cannot_submit(
    client: AsyncClient, unverified_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/toolkb/entries", json=_submission(), headers=unverified_headers
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"


async def test_submit_lands_as_operator_tier_candidate(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.post("/api/v1/toolkb/entries", json=_submission(), headers=alice_headers)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["status"] == "candidate"
    assert data["confidence"] == 0.7  # operator tier — the ceiling for HTTP
    assert data["id"]

    # candidates are never served
    listed = await client.get(
        "/api/v1/toolkb/entries", params={"tool": "kicad"}, headers=alice_headers
    )
    assert listed.status_code == 200
    assert listed.json()["data"] == []


async def test_trust_tier_cannot_be_forged(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    # The old attack: claim api_geometry with "global" scope to skip the
    # vendor-control allowlist and land at confidence 0.9. The fields no
    # longer exist; any extra field dies in the sanitized shape check.
    forged = {
        "entry": _entry_payload(provenance="observed_ui"),
        "acquired_via": "api_geometry",
        "endpoint_scope": "global",
    }
    resp = await client.post("/api/v1/toolkb/entries", json=forged, headers=alice_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "contract_validation"
    assert "api_geometry" not in resp.text  # nothing from the body echoes

    # and a docs claim is equally unreachable
    docs_claim = {"entry": _entry_payload(), "acquired_via": "docs"}
    resp = await client.post("/api/v1/toolkb/entries", json=docs_claim, headers=alice_headers)
    assert resp.status_code == 422

    # a well-formed submission carrying probe provenance is a provenance
    # mismatch against the pinned operator tier — not an escalation path
    probe_prov = await client.post(
        "/api/v1/toolkb/entries",
        json=_submission(provenance="observed_ui"),
        headers=alice_headers,
    )
    assert probe_prov.status_code == 422
    assert probe_prov.json()["error"]["code"] == "provenance_mismatch"


async def test_rejected_content_never_echoes(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    poisoned = _submission(
        invocation={"menu_path": ["File", "Open Recent", "~/designs/arm_v3.f3d"], "shortcut": None}
    )
    resp = await client.post("/api/v1/toolkb/entries", json=poisoned, headers=alice_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "contract_validation"
    assert "arm_v3" not in resp.text


async def test_non_object_bodies_never_echo(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    # entry as a bare string — previously died in the framework validator,
    # whose 422 echoes the input back (review finding)
    resp = await client.post(
        "/api/v1/toolkb/entries",
        json={"entry": "~/designs/arm_v3.f3d"},
        headers=alice_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "contract_validation"
    assert "arm_v3" not in resp.text

    # whole body as an array
    resp = await client.post(
        "/api/v1/toolkb/entries", json=["~/designs/arm_v3.f3d"], headers=alice_headers
    )
    assert resp.status_code == 422
    assert "arm_v3" not in resp.text

    # customer-shaped KEY name on the wrapper — keys are attacker-chosen too
    resp = await client.post(
        "/api/v1/toolkb/entries",
        json={"entry": _entry_payload(), "~/designs/arm_v3.f3d": 1},
        headers=alice_headers,
    )
    assert resp.status_code == 422
    assert "arm_v3" not in resp.text


async def test_get_requires_tool_and_valid_version(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    assert (await client.get("/api/v1/toolkb/entries", headers=alice_headers)).status_code == 422
    bad_version = await client.get(
        "/api/v1/toolkb/entries",
        params={"tool": "kicad", "version": "latest"},
        headers=alice_headers,
    )
    assert bad_version.status_code == 422
    assert bad_version.json()["error"]["code"] == "invalid_version"


async def test_get_serves_published_entries_with_contract_fields(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    payload = _entry_payload(provenance="vendor_docs")
    await ingest(db, entry=payload, ctx=DOCS_CTX)
    await db.commit()  # the app serves from its own sessions

    resp = await client.get(
        "/api/v1/toolkb/entries",
        params={"tool": "kicad", "version": "8.0.6", "surface": "menu"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    (item,) = body["data"]
    assert item["control_id"] == "kicad.eeschema.place_net_label"
    assert item["label"] == "Add Net Label"
    assert item["confidence"] == 0.8
    assert item["invocation"] == {"menu_path": ["Place", "Net Label"], "shortcut": "L"}
    assert item["id"]
    assert body["meta"]["has_next"] is False

    # outside the version window → empty
    outside = await client.get(
        "/api/v1/toolkb/entries",
        params={"tool": "kicad", "version": "9.1"},
        headers=alice_headers,
    )
    assert outside.json()["data"] == []


async def test_get_omits_rows_failing_revalidation_without_leaking(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession, make_entry: Any
) -> None:
    # A published row whose prose would no longer pass CTR-05 (e.g. after a
    # pattern tightening) — direct construction, bypassing the guard, is a
    # test-only privilege. The read path must withhold it AND not echo it.
    db.add(make_entry(label="~/designs/arm_v3.f3d"))
    await db.commit()

    resp = await client.get(
        "/api/v1/toolkb/entries", params={"tool": "kicad"}, headers=alice_headers
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []
    assert "arm_v3" not in resp.text


# --------------------------------------------------------------- TU-09 guides
async def _ingest_kicad(db: AsyncSession) -> None:
    from pathlib import Path

    from solus_api.toolkb.ingest.kicad import ingest_kicad_actions

    src = (Path(__file__).parent / "fixtures" / "kicad" / "sch_actions_9.0.cpp").read_text()
    await ingest_kicad_actions(
        db,
        sources=[src],
        version_range=">=9.0 <10.0",
        source_url="https://gitlab.com/kicad/code/kicad/-/raw/9.0/eeschema/tools/sch_actions.cpp",
    )
    await db.commit()


async def test_list_guides_requires_auth_and_tool_version(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    assert (
        await client.get("/api/v1/toolkb/guides", params={"tool": "kicad", "version": "9.0.4"})
    ).status_code == 401
    # tool + version required
    assert (
        await client.get("/api/v1/toolkb/guides", params={"tool": "kicad"}, headers=alice_headers)
    ).status_code == 422

    resp = await client.get(
        "/api/v1/toolkb/guides",
        params={"tool": "kicad", "version": "9.0.4"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    guides = resp.json()["data"]
    assert any(g["id"] == "kicad.eeschema.first_schematic" for g in guides)
    assert all("step_count" in g and g["title"] for g in guides)


async def test_get_guide_resolves_against_live_kb(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await _ingest_kicad(db)
    resp = await client.get(
        "/api/v1/toolkb/guides/kicad.eeschema.first_schematic",
        params={"version": "9.0.4"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    guide = resp.json()["data"]
    assert guide["title"]
    steps = guide["steps"]
    assert [s["step_number"] for s in steps] == list(range(1, len(steps) + 1))
    available = [s for s in steps if s["available"]]
    assert available, "steps must resolve against the ingested KiCad KB"
    first = available[0]
    assert first["label"] and first["note_guide"] and first["note_expert"]
    assert 0.0 <= first["confidence"] <= 1.0


async def test_get_guide_exposes_the_locator_the_overlay_needs(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """SOLUS-TU-10 / SOLX-03: geometry must survive the route, or reach the wire.

    `locator` is present on every step, `None` included — the overlay branches on
    the key, and an absent key is indistinguishable from a box at the origin.
    None is the COMMON case: vendor documentation carries no coordinates.
    """
    await _ingest_kicad(db)
    resp = await client.get(
        "/api/v1/toolkb/guides/kicad.eeschema.first_schematic",
        params={"version": "9.0.4"},
        headers=alice_headers,
    )
    steps = resp.json()["data"]["steps"]
    assert steps and all("locator" in s for s in steps)
    for box in (s["locator"] for s in steps if s["locator"] is not None):
        assert set(box) == {"x", "y", "w", "h"}
        assert all(0.0 <= box[k] <= 1.0 for k in box)


async def test_get_guide_degrades_when_kb_empty(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    # nothing ingested → every step unavailable, narration still present
    resp = await client.get(
        "/api/v1/toolkb/guides/kicad.eeschema.first_schematic",
        params={"version": "9.0.4"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    steps = resp.json()["data"]["steps"]
    assert steps and all(not s["available"] for s in steps)
    assert all(s["label"] is None and s["note_guide"] for s in steps)


async def test_get_unknown_guide_is_404(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    resp = await client.get(
        "/api/v1/toolkb/guides/no.such.guide",
        params={"version": "9.0.4"},
        headers=alice_headers,
    )
    assert resp.status_code == 404
