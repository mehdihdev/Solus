"""Explicit source-part proposal route auth and isolation."""

import uuid

from conftest import BOB, add_member, me
from test_hardware_detect import _detect_project


async def test_part_suggestion_route_requires_project_member(client, alice_headers, bob_headers):
    project, team = await _detect_project(client, alice_headers)
    url = f"/api/v1/projects/{project}/hardware/parts/{uuid.uuid4()}/suggestions"
    assert (await client.post(url)).status_code == 401
    await me(client, bob_headers)
    assert (await client.post(url, headers=bob_headers)).status_code == 404
    await add_member(client, alice_headers, bob_headers, BOB, team, role="viewer")
    assert (await client.post(url, headers=bob_headers)).status_code == 403
    assert (await client.post(url, headers=alice_headers)).status_code == 404
