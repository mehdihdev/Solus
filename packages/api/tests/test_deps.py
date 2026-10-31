"""Centralized auth middleware/dependencies (CLAUDE.md §7, API.md §1.2/§1.3).

Covers: bearer enforcement, auto-provisioning of the user + personal team at
first authenticated request, and team/project scoping basics.
"""

from typing import Any

import pytest
from conftest import ALICE, bearer, me
from httpx import AsyncClient
from solus_api.core.config import Settings


async def test_protected_route_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_protected_route_rejects_invalid_token(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401


async def test_protected_route_rejects_expired_token(client: AsyncClient) -> None:
    headers = bearer(ALICE["sub"], ALICE["email"], expires_in=-60)
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 401


async def test_first_login_provisions_user_and_personal_team(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    data = await me(client, alice_headers)
    assert data["email"] == ALICE["email"]
    assert len(data["teams"]) == 1
    team = data["teams"][0]
    assert team["is_personal"] is True
    assert team["role"] == "owner"


async def test_second_login_does_not_duplicate_user(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    first = await me(client, alice_headers)
    second = await me(client, alice_headers)
    assert first["id"] == second["id"]
    assert len(second["teams"]) == 1


async def test_the_sim_enqueue_queues_a_request_once_under_a_stable_id() -> None:
    """SOLUSDEV-321 P4-T4 (R110): a rung-3 job is queued on the app's ARQ pool under
    `<job>:<project>:<sha1 of the request>`, so the same request never queues twice while it waits
    (arq refuses a live id), whatever the order of its keys."""
    from types import SimpleNamespace
    from typing import Any, cast

    from fastapi import FastAPI
    from solus_api.deps import create_sim_enqueue

    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    class _Pool:
        async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> object:
            calls.append((name, args, kwargs))
            return object()

    app = cast(FastAPI, SimpleNamespace(state=SimpleNamespace(arq_pool=_Pool())))
    enqueue = create_sim_enqueue(app)
    request = {"project_id": "p", "subject_id": "s", "facts": {"b": 1, "a": 2}}

    first = await enqueue("run_mesh_sim", "p", request)
    again = await enqueue(
        "run_mesh_sim", "p", {"facts": {"a": 2, "b": 1}, "subject_id": "s", "project_id": "p"}
    )
    other = await enqueue("run_mesh_sim", "p", {**request, "subject_id": "t"})

    assert first == again != other
    job, project, digest = first.split(":")
    assert (job, project, len(digest)) == ("run_mesh_sim", "p", 12)
    assert [kwargs["_job_id"] for _, _, kwargs in calls] == [first, first, other]
    assert calls[0][:2] == ("run_mesh_sim", (request,))


async def test_the_registry_the_routes_build_carries_the_simulation_tools(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """The app's hub reaches `build_sol_registry` through `get_sol_registry`, so `simulate` and
    its gated apply are offered to the person, beside the `get_sim_result` read."""
    from conftest import create_project, create_team

    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    listing = await client.get(f"/api/v1/projects/{project['id']}/sol/tools", headers=alice_headers)
    assert listing.status_code == 200
    tools = {tool["name"]: tool for tool in listing.json()["data"]}
    assert tools["simulate"]["requires_confirmation"] is False
    assert tools["apply_sim_change"]["requires_confirmation"] is True
    assert tools["get_sim_result"]["requires_confirmation"] is False


async def test_the_routes_registry_offers_render_view_with_the_upload_cap(
    client: AsyncClient,
    alice_headers: dict[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOLUSDEV-321 P5 (D10, R124): the route's registry binds the person, their team and both
    stores, so `render_view` is offered, ungated; the artifacts route's own upload cap reaches its
    renderers, which never run an export that cap could refuse."""
    from conftest import create_project, create_team
    from solus_api.agent import runtime

    seen: list[dict[str, Any]] = []
    real = runtime.build_sol_registry

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(runtime, "build_sol_registry", spy)
    await me(client, alice_headers)
    team = await create_team(client, alice_headers)
    project = await create_project(client, alice_headers, team["id"])
    listing = await client.get(f"/api/v1/projects/{project['id']}/sol/tools", headers=alice_headers)

    assert listing.status_code == 200
    tools = {tool["name"]: tool for tool in listing.json()["data"]}
    assert tools["render_view"]["requires_confirmation"] is False
    assert seen and seen[-1]["artifact_max_bytes"] == settings.artifact_max_bytes
