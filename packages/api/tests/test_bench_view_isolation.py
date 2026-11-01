"""Cross-team isolation for the bench view (CLAUDE.md §7): team A cannot read or
write team B's view; the response is 404 (no existence oracle)."""

from __future__ import annotations

import uuid

from conftest import create_project, create_team, me
from httpx import AsyncClient

PIN = {
    "kind": "set_display",
    "target": {"kind": "signal", "device_id": "d", "signal": "s"},
    "patch": {"pinned": True},
}


def _url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/bench/view"


async def test_other_team_cannot_get_or_patch_and_nothing_changes(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    await me(client, alice_headers)
    await me(client, bob_headers)
    team_b = await create_team(client, bob_headers, name="B")
    project_b = (await create_project(client, bob_headers, team_b["id"]))["id"]
    saved = await client.patch(
        _url(project_b), json={"version": 0, "ops": [PIN]}, headers=bob_headers
    )
    assert saved.status_code == 200, saved.text

    read = await client.get(_url(project_b), headers=alice_headers)
    assert read.status_code == 404
    assert read.json()["error"]["code"] == "not_found"
    write = await client.patch(
        _url(project_b), json={"version": 1, "ops": [PIN]}, headers=alice_headers
    )
    assert write.status_code == 404
    # Even a bad body gets 404 for a foreign project (no oracle via 422).
    junk = await client.patch(_url(project_b), json={"junk": 1}, headers=alice_headers)
    assert junk.status_code == 404

    own = (await client.get(_url(project_b), headers=bob_headers)).json()["data"]
    assert own["version"] == 1


async def test_unknown_project_is_404(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    await me(client, alice_headers)
    missing = str(uuid.uuid4())
    assert (await client.get(_url(missing), headers=alice_headers)).status_code == 404
    response = await client.patch(
        _url(missing), json={"version": 0, "ops": [PIN]}, headers=alice_headers
    )
    assert response.status_code == 404
