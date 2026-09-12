"""Bounded, immutable code reads through the connected provider's HTTP client."""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import quote

import httpx

from solus_api.connectors.contracts import Credentials
from solus_api.connectors.github import GITHUB_API, GitHubConnector
from solus_api.connectors.gitlab import GitLabConnector

MAX_CODE_BYTES: Final = 262_144
_SECRET_NAMES: Final = frozenset(
    {
        ".git",
        ".ssh",
        ".aws",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
    }
)


class CodeContentError(ValueError):
    """Safe, authored failure; never includes provider response bodies."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def safe_code_path(path: str) -> str:
    parts = path.split("/")
    if (
        not path
        or len(path) > 1024
        or "\\" in path
        or ":" in parts[0]
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise CodeContentError("File path must be a valid repository-relative path.")
    if any(part.lower().startswith(".env") or part.lower() in _SECRET_NAMES for part in parts):
        raise CodeContentError("Credential files cannot be read as code context.")
    if parts[-1].lower().endswith((".pem", ".key", ".p12", ".pfx", ".keystore")):
        raise CodeContentError("Credential files cannot be read as code context.")
    return path


def decode_code(raw: bytes) -> str:
    if len(raw) > MAX_CODE_BYTES:
        raise CodeContentError("File exceeds the code context byte limit.")
    if b"\x00" in raw:
        raise CodeContentError("Binary files cannot be read as code context.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodeContentError("File is not UTF-8 text.") from exc


class CodeContentReader:
    def __init__(self, connector: GitHubConnector | GitLabConnector) -> None:
        self.connector = connector

    def _url(self, repo: str, path: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", repo) or any(
            part in {".", ".."} for part in repo.split("/")
        ):
            raise CodeContentError("The source has an invalid repository identity.")
        if isinstance(self.connector, GitHubConnector):
            if repo.count("/") != 1:
                raise CodeContentError("The source has an invalid repository identity.")
            return f"{GITHUB_API}/repos/{repo}/contents/{quote(path, safe='/')}"
        return f"{self.connector._project_url(repo)}/repository/files/{quote(path, safe='')}/raw"

    async def read(
        self,
        credentials: Credentials,
        *,
        repo: str,
        path: str,
        commit: str,
        blob_sha: str | None = None,
    ) -> str:
        safe_code_path(path)
        if re.fullmatch(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?", commit) is None:
            raise CodeContentError(
                "No immutable synced commit is available; sync this source first."
            )
        url = self._url(repo, path)
        params = {"ref": commit}
        if isinstance(self.connector, GitHubConnector) and blob_sha is not None:
            if re.fullmatch(r"[0-9a-fA-F]{40}", blob_sha) is None:
                raise CodeContentError("The graph file blob identity is invalid; sync again.")
            url = f"{GITHUB_API}/repos/{repo}/git/blobs/{blob_sha}"
            params = {}
        headers = (
            {"Accept": "application/vnd.github.raw+json"}
            if isinstance(self.connector, GitHubConnector)
            else {}
        )
        try:
            async with self.connector._http(credentials) as client:
                async with client.stream(
                    "GET", url, params=params, headers=headers, follow_redirects=False
                ) as response:
                    return await self._text(response)
        except httpx.HTTPError as exc:
            raise CodeContentError("The repository provider could not be reached.") from exc

    @staticmethod
    async def _text(response: httpx.Response) -> str:
        if response.status_code != 200:
            raise CodeContentError(
                "The repository provider refused the file read.", status=response.status_code
            )
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_CODE_BYTES:
            raise CodeContentError("File exceeds the code context byte limit.")
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            if len(raw) + len(chunk) > MAX_CODE_BYTES:
                raise CodeContentError("File exceeds the code context byte limit.")
            raw.extend(chunk)
        return decode_code(bytes(raw))
