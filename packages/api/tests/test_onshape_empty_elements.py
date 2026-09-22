"""Only immutable, positively empty geometry permits omitting a failed export."""

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from solus_api.connectors.contracts import ConnectorError
from solus_api.connectors.export_common import ErrorRecorder
from solus_api.connectors.onshape import OnshapeConnector, _Target


@pytest.mark.parametrize(
    ("collection", "body"),
    [("assemblies", {"rootAssembly": {"instances": []}}), ("partstudios", [])],
)
async def test_confirmed_empty_element_does_not_fail_document(collection: str, body: Any) -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="m")
    connector._fetch_step = AsyncMock(
        side_effect=ConnectorError("export_unavailable", "Empty export")
    )
    connector.get_json = AsyncMock(return_value=body)
    async with httpx.AsyncClient() as client:
        result = await connector._ingest(
            client, _Target("d", "w", "e", collection), ErrorRecorder(), version="m"
        )
    assert result == ([], [])


@pytest.mark.parametrize(
    "body", [{}, {"rootAssembly": {}}, {"rootAssembly": {"instances": [{"id": "one"}]}}]
)
async def test_unknown_or_nonempty_assembly_preserves_export_failure(body: Any) -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="m")
    connector._fetch_step = AsyncMock(
        side_effect=ConnectorError("export_unavailable", "Original export failure")
    )
    connector.get_json = AsyncMock(return_value=body)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError, match="Original export failure"):
            await connector._ingest(client, _Target("d", "w", "e"), ErrorRecorder(), version="m")


@pytest.mark.parametrize("resource", ["request", "external"])
async def test_invalid_export_resource_never_uses_empty_geometry_fallback(resource: str) -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="m")
    connector.post_json = AsyncMock(
        return_value={"id": "../bad" if resource == "request" else "request1"}
    )
    connector._poll_translation = AsyncMock(return_value="../bad")
    empty_check = AsyncMock(return_value={"rootAssembly": {"instances": []}})
    connector.get_json = empty_check
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError, match="unusable resource id") as error:
            await connector._ingest(client, _Target("d", "w", "e"), ErrorRecorder(), version="m")
    assert error.value.code == "export_unavailable"
    empty_check.assert_not_awaited()


@pytest.mark.parametrize(
    "code", ["invalid_credentials", "api_error", "rate_limited", "export_timeout"]
)
async def test_vendor_error_during_empty_check_preserves_original_failure(code: str) -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="m")
    original = ConnectorError("export_unavailable", "Original export failure")
    connector._fetch_step = AsyncMock(side_effect=original)
    connector.get_json = AsyncMock(side_effect=ConnectorError(code, "Check failed"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError) as error:
            await connector._ingest(client, _Target("d", "w", "e"), ErrorRecorder(), version="m")
    assert error.value is original


@pytest.mark.parametrize("body", [{}, {"items": []}, None, [{"partId": "one"}], ""])
async def test_malformed_or_nonempty_part_studio_keeps_original_failure(body: Any) -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="m")
    original = ConnectorError("export_unavailable", "Original export failure")
    connector._fetch_step = AsyncMock(side_effect=original)
    connector.get_json = AsyncMock(return_value=body)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError) as error:
            await connector._ingest(
                client, _Target("d", "w", "e", "partstudios"), ErrorRecorder(), version="m"
            )
    assert error.value is original


@pytest.mark.parametrize(
    "collection,endpoint,body",
    [
        ("assemblies", "assemblies", {"rootAssembly": {"instances": []}}),
        ("partstudios", "parts", []),
    ],
)
async def test_empty_check_is_pinned_to_the_observed_immutable_version(
    collection: str, endpoint: str, body: Any
) -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="micro123")
    connector._fetch_step = AsyncMock(side_effect=ConnectorError("export_unavailable", "empty"))
    check = AsyncMock(return_value=body)
    connector.get_json = check
    async with httpx.AsyncClient() as client:
        await connector._ingest(
            client,
            _Target("doc", "liveworkspace", "element", collection),
            ErrorRecorder(),
            version="micro123",
        )
        check.assert_awaited_once_with(
            client, f"/api/v6/{endpoint}/d/doc/m/micro123/e/element", what="empty element check"
        )


async def test_invalid_microversion_never_reaches_vendor() -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="m")
    original = ConnectorError("export_unavailable", "original")
    connector._fetch_step = AsyncMock(side_effect=original)
    check = AsyncMock()
    connector.get_json = check
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConnectorError) as error:
            await connector._ingest(
                client, _Target("d", "w", "e"), ErrorRecorder(), version="../bad"
            )
    assert error.value.code == "revision_changed"
    connector._fetch_step.assert_not_awaited()
    check.assert_not_awaited()


async def test_confirmed_empty_geometry_is_cached_only_for_that_version() -> None:
    from solus_api.connectors.httpcache import InMemoryCacheStore
    from solus_api.connectors.integration_cache import IntegrationCache

    connector = OnshapeConnector(
        client_id="id",
        client_secret="secret",
        cache=IntegrationCache(InMemoryCacheStore()),
        account_ref="account",
    )
    export = AsyncMock(side_effect=ConnectorError("export_unavailable", "empty"))
    check = AsyncMock(return_value=[])
    connector._fetch_step = export
    connector.get_json = check
    async with httpx.AsyncClient() as client:
        target = _Target("d", "w", "e", "partstudios")
        for version in ("m1", "m1", "m2"):
            connector._current_microversion = AsyncMock(return_value=version)
            assert await connector._ingest(client, target, ErrorRecorder(), version=version) == (
                [],
                [],
            )
    assert export.await_count == check.await_count == 2


@pytest.mark.parametrize("body", [[], [{"partId": "one"}], {}, None])
async def test_translation_400_requires_positive_immutable_empty_proof(body: Any) -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="micro")
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(400)
        assert request.url.path == "/api/v6/parts/d/d/m/micro/e/e"
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(
        base_url="https://cad.onshape.com", transport=httpx.MockTransport(respond)
    ) as client:
        if body == []:
            assert (
                await connector._geometry_export(
                    client, _Target("d", "w", "e", "partstudios"), "micro"
                )
                is None
            )
        else:
            with pytest.raises(ConnectorError) as error:
                await connector._geometry_export(
                    client, _Target("d", "w", "e", "partstudios"), "micro"
                )
            assert error.value.code == "api_error"
            assert "400" in str(error.value)
    assert [request.method for request in requests] == ["POST", "GET"]


@pytest.mark.parametrize("status", [401, 402, 403, 404, 500])
async def test_other_translation_http_errors_never_check_empty_geometry(status: int) -> None:
    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="micro")
    check = AsyncMock(return_value=[])
    connector.get_json = check
    async with httpx.AsyncClient(
        base_url="https://cad.onshape.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(status)),
    ) as client:
        with pytest.raises(ConnectorError):
            await connector._geometry_export(client, _Target("d", "w", "e", "partstudios"), "micro")
    check.assert_not_awaited()


@pytest.mark.parametrize("failure", ["poll_400", "malformed_json", "rate_limited"])
async def test_non_submission_failures_do_not_use_empty_geometry_fallback(failure: str) -> None:
    from unittest.mock import patch

    connector = OnshapeConnector(client_id="id", client_secret="secret")
    connector._current_microversion = AsyncMock(return_value="micro")
    check = AsyncMock(return_value=[])
    connector._confirmed_empty = check

    def respond(request: httpx.Request) -> httpx.Response:
        if failure == "rate_limited":
            return httpx.Response(429)
        if failure == "malformed_json":
            return httpx.Response(200, content=b"not json")
        if request.method == "POST":
            return httpx.Response(200, json={"id": "request1"})
        return httpx.Response(400)

    with patch("solus_api.connectors.onshape.asyncio.sleep", new=AsyncMock()):
        async with httpx.AsyncClient(
            base_url="https://cad.onshape.com", transport=httpx.MockTransport(respond)
        ) as client:
            with pytest.raises(ConnectorError):
                await connector._geometry_export(
                    client, _Target("d", "w", "e", "partstudios"), "micro"
                )
    check.assert_not_awaited()
