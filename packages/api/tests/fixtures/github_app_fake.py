"""A network-free fake GitHub for the GitHub App auth tests (SOLUSDEV-216).

The RSA key pair is generated at runtime; no PEM is ever committed. `respx` mocks the
endpoints the App client calls, and the fake records every call so tests can assert on
call COUNTS ("served from cache" is measured, never claimed).
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from solus_api.core.config import Settings

API = "https://api.github.com"
WEB = "https://github.com"
APP_ID = "424242"
CLIENT_ID = "Iv1.testclientid"
CLIENT_SECRET = "test-client-secret-value"  # placeholder, not a real secret


def generate_key_pair() -> tuple[str, str]:
    """(private PEM, public PEM), generated fresh for each call."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, public.decode()


def app_settings(base: Settings, private_pem: str) -> Settings:
    """`base` plus a complete GitHub App configuration."""
    return base.model_copy(
        update={
            "github_app_id": APP_ID,
            "github_app_slug": "solus-test",
            "github_app_client_id": CLIENT_ID,
            "github_app_client_secret": _secret(CLIENT_SECRET),
            "github_app_private_key": _secret(private_pem),
            "github_app_webhook_secret": _secret("whsec-app-test"),
        }
    )


def _secret(value: str) -> Any:
    from pydantic import SecretStr

    return SecretStr(value)


def installation_record(
    installation_id: int,
    *,
    login: str = "acme-robotics",
    account_id: int = 777,
    account_type: str = "Organization",
    selection: str = "selected",
    suspended_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": installation_id,
        "account": {
            "login": login,
            "id": account_id,
            "type": account_type,
            "avatar_url": f"https://avatars.githubusercontent.com/u/{account_id}",
        },
        "repository_selection": selection,
        "suspended_at": suspended_at,
    }


def basic_auth_user(request: httpx.Request) -> tuple[str, str] | None:
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return None
    user, _, password = base64.b64decode(header[6:]).decode().partition(":")
    return user, password


class FakeGitHubApp:
    """Records calls and serves scripted responses for the endpoints the client uses."""

    def __init__(self, router: respx.MockRouter) -> None:
        self.router = router
        self.clock: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.token_lifetime = timedelta(hours=1)
        self.installations: dict[int, dict[str, Any]] = {}
        #: per-installation mint override, e.g. {5: 404}
        self.mint_status: dict[int, int] = {}
        self.mint_delay = 0.0
        self.mint_calls: list[int] = []
        self.minted_tokens: list[str] = []
        self.jwts_seen: list[str] = []
        self.user_pages: list[list[int]] = [[]]
        self.user_installations_requests: list[httpx.Request] = []
        #: replaces the Link header on /user/installations page 1
        self.next_link_override: str | None = None
        self.code_response: dict[str, Any] = {
            "access_token": "ghu_usertoken",
            "token_type": "bearer",
        }
        self.code_requests: list[httpx.Request] = []
        self.revoke_requests: list[httpx.Request] = []
        self.revoke_status = 204
        self.repo_pages: list[list[dict[str, Any]]] = [[]]
        self.member_pages: list[list[dict[str, Any]]] = [[]]
        self.list_requests: list[httpx.Request] = []
        self._counter = itertools.count(1)
        self._install_routes()

    # -- scripting ---------------------------------------------------------------
    def add_installation(self, installation_id: int, **kwargs: Any) -> None:
        self.installations[installation_id] = installation_record(installation_id, **kwargs)

    # -- handlers ----------------------------------------------------------------
    def _install_routes(self) -> None:
        r = self.router
        self.installation_route = r.get(url__regex=rf"{API}/app/installations/(\d+)$").mock(
            side_effect=self._get_installation
        )
        self.mint_route = r.post(url__regex=rf"{API}/app/installations/(\d+)/access_tokens$").mock(
            side_effect=self._mint
        )
        self.user_route = r.get(url__regex=rf"{API}/user/installations(\?.*)?$").mock(
            side_effect=self._user_installations
        )
        r.post(f"{WEB}/login/oauth/access_token").mock(side_effect=self._exchange)
        r.delete(url__regex=rf"{API}/applications/[^/]+/token$").mock(side_effect=self._revoke)
        r.get(url__regex=rf"{API}/installation/repositories(\?.*)?$").mock(side_effect=self._repos)
        r.get(url__regex=rf"{API}/orgs/[^/]+/members(\?.*)?$").mock(side_effect=self._members)

    @staticmethod
    def _iid(request: httpx.Request) -> int:
        parts = request.url.path.split("/")
        return int(parts[3])

    def _get_installation(self, request: httpx.Request) -> httpx.Response:
        self.jwts_seen.append(request.headers["authorization"].removeprefix("Bearer "))
        record = self.installations.get(self._iid(request))
        if record is None:
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json=record)

    async def _mint(self, request: httpx.Request) -> httpx.Response:
        iid = self._iid(request)
        self.jwts_seen.append(request.headers["authorization"].removeprefix("Bearer "))
        self.mint_calls.append(iid)
        if self.mint_delay:
            await asyncio.sleep(self.mint_delay)
        status = self.mint_status.get(iid)
        if status is not None:
            return httpx.Response(status, json={"message": "nope"})
        token = f"ghs_{next(self._counter)}_{secrets.token_hex(12)}"
        self.minted_tokens.append(token)
        expires = (self.clock() + self.token_lifetime).strftime("%Y-%m-%dT%H:%M:%SZ")
        return httpx.Response(
            201, json={"token": token, "expires_at": expires, "permissions": {"contents": "read"}}
        )

    def _user_installations(self, request: httpx.Request) -> httpx.Response:
        self.user_installations_requests.append(request)
        page = int(request.url.params.get("page", "1"))
        ids = self.user_pages[page - 1] if page <= len(self.user_pages) else []
        headers: dict[str, str] = {}
        if page < len(self.user_pages):
            headers["Link"] = f'<{API}/user/installations?page={page + 1}>; rel="next"'
        if page == 1 and self.next_link_override is not None:
            headers["Link"] = self.next_link_override
        body = {"total_count": len(ids), "installations": [{"id": i} for i in ids]}
        return httpx.Response(200, json=body, headers=headers)

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        self.code_requests.append(request)
        return httpx.Response(200, json=self.code_response)

    def _revoke(self, request: httpx.Request) -> httpx.Response:
        self.revoke_requests.append(request)
        return httpx.Response(self.revoke_status)

    def _paged(self, request: httpx.Request, pages: list[Any], key: str | None) -> httpx.Response:
        self.list_requests.append(request)
        page = int(request.url.params.get("page", "1"))
        items = pages[page - 1] if page <= len(pages) else []
        headers = {}
        if page < len(pages):
            nxt = request.url.copy_set_param("page", str(page + 1))
            headers["Link"] = f'<{nxt}>; rel="next"'
        body: Any = {"total_count": len(items), key: items} if key else items
        return httpx.Response(200, json=body, headers=headers)

    def _repos(self, request: httpx.Request) -> httpx.Response:
        return self._paged(request, self.repo_pages, "repositories")

    def _members(self, request: httpx.Request) -> httpx.Response:
        return self._paged(request, self.member_pages, None)


def decode_jwt_unverified(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    decoded: dict[str, Any] = json.loads(base64.urlsafe_b64decode(payload))
    return decoded


__all__ = [
    "API",
    "APP_ID",
    "CLIENT_ID",
    "CLIENT_SECRET",
    "WEB",
    "FakeGitHubApp",
    "app_settings",
    "basic_auth_user",
    "decode_jwt_unverified",
    "generate_key_pair",
    "installation_record",
]
