"""Unit tests for the Supabase Admin client (SOLUSDEV-82)."""

from typing import Any

import httpx
import pytest
from solus_api.services.supabase_admin import SupabaseAdmin


class _RecordingClient:
    """Stands in for httpx.AsyncClient; records the DELETE and returns a canned status."""

    calls: list[tuple[str, dict[str, str]]] = []

    def __init__(self, status: int) -> None:
        self._status = status

    def __call__(self, *_args: Any, **_kwargs: Any) -> "_RecordingClient":
        return self

    async def __aenter__(self) -> "_RecordingClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def delete(self, url: str, headers: dict[str, str]) -> httpx.Response:
        _RecordingClient.calls.append((url, headers))
        return httpx.Response(self._status, request=httpx.Request("DELETE", url))


def _patch_client(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    _RecordingClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _RecordingClient(status))


def test_unconfigured_is_not_configured() -> None:
    assert SupabaseAdmin(None, None).configured is False
    assert SupabaseAdmin("https://x.supabase.co", None).configured is False


async def test_delete_user_noop_when_unconfigured() -> None:
    assert await SupabaseAdmin(None, None).delete_user("sub-1") is False


async def test_delete_user_calls_admin_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, 200)
    admin = SupabaseAdmin("https://proj.supabase.co/", "service-key")  # noqa: S106
    assert await admin.delete_user("sub-42") is True
    url, headers = _RecordingClient.calls[0]
    assert url == "https://proj.supabase.co/auth/v1/admin/users/sub-42"
    assert headers["apikey"] == "service-key"
    assert headers["Authorization"] == "Bearer service-key"


async def test_delete_user_treats_404_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, 404)
    admin = SupabaseAdmin("https://proj.supabase.co", "service-key")  # noqa: S106
    assert await admin.delete_user("gone") is True


async def test_delete_user_returns_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, 500)
    admin = SupabaseAdmin("https://proj.supabase.co", "service-key")  # noqa: S106
    assert await admin.delete_user("sub") is False


class _GetClient:
    """Stands in for httpx.AsyncClient for a GET of one auth user (SOLUSDEV-319)."""

    def __init__(self, status: int, body: object) -> None:
        self._status, self._body = status, body

    def __call__(self, *_args: Any, **_kwargs: Any) -> "_GetClient":
        return self

    async def __aenter__(self) -> "_GetClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str]) -> httpx.Response:
        return httpx.Response(self._status, json=self._body, request=httpx.Request("GET", url))


async def test_confirmed_email_returns_the_confirmed_address_lowercased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"email": "Bob@Example.com", "email_confirmed_at": "2026-11-01T00:00:00Z"}
    monkeypatch.setattr(httpx, "AsyncClient", _GetClient(200, body))
    admin = SupabaseAdmin("https://x.supabase.co", "service-key")
    assert await admin.confirmed_email("0b0b0b0b-0000-0000-0000-000000000000") == "bob@example.com"


async def test_confirmed_email_is_none_until_confirmed_or_on_any_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = SupabaseAdmin("https://x.supabase.co", "service-key")
    uid = "0b0b0b0b-0000-0000-0000-000000000000"
    for status, body in (
        (200, {"email": "bob@example.com", "email_confirmed_at": None}),
        (200, {"email_confirmed_at": "2026-11-01T00:00:00Z"}),
        (200, ["not", "an", "object"]),
        (404, {}),
        (500, {}),
    ):
        monkeypatch.setattr(httpx, "AsyncClient", _GetClient(status, body))
        assert await admin.confirmed_email(uid) is None
    assert await SupabaseAdmin(None, None).confirmed_email(uid) is None
    assert await admin.confirmed_email("../../etc") is None
