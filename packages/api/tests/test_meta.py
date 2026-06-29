"""§2.0 Infrastructure & meta — /healthz, /readyz, /api/v1/version."""

from httpx import AsyncClient


async def test_healthz_returns_ok_without_auth(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"data": {"status": "ok"}}


async def test_readyz_reports_dependency_checks(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    # Redis/queue are not configured in tests (ARQ wiring lands with the
    # first job-producing endpoint, Phase 3).
    assert body["checks"]["redis"] == "not_configured"
    assert body["checks"]["queue"] == "not_configured"


async def test_version_is_unversioned_path_and_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/version")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["version"] == "0.1.0"
    assert body["build_sha"] == "dev"
