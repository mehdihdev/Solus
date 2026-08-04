"""Companion-side ArtifactRef path: bulk tool output → HTTPS upload → reference.

When a fork tool result carries a non-null `artifact_path` (workspace-relative,
the kicad export shape), the dispatcher hands it here. The file is resolved
with the same paranoia as `config._launch_command` — symlinks resolved FIRST,
then `is_relative_to` the workspace the companion passed to that server — and
size-capped by stat WITHOUT reading. Upload goes to
`POST {origin}/api/v1/projects/{project_id}/artifacts` (docs/api/artifacts.md),
but ONLY when the API host passes the same allowed-hosts allowlist guarding the
WS URL: the bearer token never rides to a non-allowlisted host, and is never
logged. A 201 yields the W0-04 `ArtifactRef` that replaces `artifact_path` in
the tool result; every failure is one stable reason string (retryable frames).
"""

import asyncio
import json
import logging
import mimetypes
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from solus_companion.config import (
    CompanionConfig,
    ServerLaunch,
    api_endpoint_from_ws_url,
)

logger = logging.getLogger("solus.companion.artifacts")

ARTIFACT_MAX_BYTES = 8 * 1024 * 1024  # artifacts.md §4.4 `artifact_max_bytes` default
UPLOAD_TIMEOUT_SECONDS = 30.0
FALLBACK_MEDIA_TYPE = "application/octet-stream"

# Stable failure reasons — the tool_result error message the cloud sees.
REASON_UPLOAD_UNAVAILABLE = "artifact_upload_unavailable"
REASON_WORKSPACE_UNKNOWN = "artifact_workspace_unknown"
REASON_PATH_ESCAPES = "artifact_path_escapes_workspace"
REASON_FILE_MISSING = "artifact_file_missing"
REASON_FILE_TOO_LARGE = "artifact_file_too_large"
REASON_HOST_NOT_ALLOWLISTED = "api_host_not_allowlisted"
REASON_UNAUTHORIZED = "upload_unauthorized"
REASON_PAYLOAD_TOO_LARGE = "upload_payload_too_large"
REASON_RATE_LIMITED = "upload_rate_limited"
REASON_FAILED = "upload_failed"
REASON_TIMEOUT = "upload_timeout"
REASON_CONNECTION = "upload_connection_error"
REASON_BAD_REF = "artifact_ref_invalid"

_STATUS_REASONS = {
    401: REASON_UNAUTHORIZED,
    413: REASON_PAYLOAD_TOO_LARGE,
    429: REASON_RATE_LIMITED,
}

# post(url, headers, body, timeout) -> (status, response_body); tests inject fakes.
PostFn = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]


class ArtifactUploadError(Exception):
    """One stable machine-readable reason; never carries paths or tokens."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ArtifactRef(BaseModel):
    """Mirror of the W0-04 `ArtifactRef` (agent-tool.md §4) — the companion is
    bundled standalone, so the cloud schema is mirrored, never imported."""

    model_config = ConfigDict(frozen=True)

    artifact_id: uuid.UUID
    uri: str
    media_type: str
    storage: str
    size_bytes: int | None = None
    summary: str | None = None


def server_workspace(launch: ServerLaunch) -> Path:
    """The workspace the companion passed to that server: its declared
    `SOLUS_MCP_WORKSPACE`, else the fork dir (`bin/launch`'s own fallback)."""
    raw = launch.env.get("SOLUS_MCP_WORKSPACE", "")
    if raw:
        return Path(raw)
    return launch.command.parent.parent  # <fork>/bin/launch → <fork>


def _default_post(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> tuple[int, bytes]:
    """stdlib transport (the companion adds no HTTP dependency). The URL is
    always built from the allowlist-checked origin — never from tool output —
    and the scheme is re-guarded here so this function is safe in isolation."""
    if not url.startswith(("https://", "http://")):
        raise urllib.error.URLError("unsupported scheme")
    request = urllib.request.Request(  # noqa: S310 — scheme guarded above; host allowlisted by _check_host
        url, data=body, headers=dict(headers), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — see above
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _multipart_body(
    fields: Mapping[str, str], filename: str, media_type: str, payload: bytes
) -> tuple[bytes, str]:
    """Encode the artifacts.md §2 form: text fields + one `file` part."""
    boundary = uuid.uuid4().hex
    safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
    lines: list[str] = []
    for name, value in fields.items():
        lines.extend((f"--{boundary}", f'Content-Disposition: form-data; name="{name}"', "", value))
    lines.extend(
        (
            f"--{boundary}",
            f'Content-Disposition: form-data; name="file"; filename="{safe_name}"',
            f"Content-Type: {media_type}",
            "",
        )
    )
    head = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("ascii")
    return head + payload + tail, f"multipart/form-data; boundary={boundary}"


def _parse_ref(raw: bytes, call_id: str) -> dict[str, Any]:
    """201 body → schema-valid ArtifactRef dict, or one stable failure."""
    try:
        envelope = json.loads(raw)
        ref = ArtifactRef.model_validate(envelope["data"])
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        logger.warning(
            "artifact upload for call %.64s returned an invalid envelope: %s",
            call_id,
            type(exc).__name__,
        )
        raise ArtifactUploadError(REASON_BAD_REF) from exc
    return ref.model_dump(mode="json")


class ArtifactUploader:
    """Uploads one workspace artifact per call and returns its ArtifactRef."""

    def __init__(
        self,
        *,
        origin: str,
        project_id: str,
        token_source: Callable[[], str],
        allowed_hosts: frozenset[str],
        workspaces: Mapping[str, Path],
        post: PostFn = _default_post,
        max_bytes: int = ARTIFACT_MAX_BYTES,
        timeout: float = UPLOAD_TIMEOUT_SECONDS,
    ) -> None:
        self._origin = origin.rstrip("/")
        self._project_id = project_id
        self._token_source = token_source
        self._allowed_hosts = allowed_hosts
        self._workspaces = dict(workspaces)
        self._post = post
        self._max_bytes = max_bytes
        self._timeout = timeout

    @classmethod
    def from_config(cls, config: CompanionConfig) -> "ArtifactUploader | None":
        """Build from the companion config; None when the WS URL is not a
        project bridge URL (uploads stay disabled, dispatch fails closed)."""
        endpoint = api_endpoint_from_ws_url(config.url)
        if endpoint is None:
            logger.warning("companion URL is not a project bridge URL; artifact uploads disabled")
            return None
        workspaces = {launch.name: server_workspace(launch) for launch in config.servers}
        return cls(
            origin=endpoint.origin,
            project_id=endpoint.project_id,
            token_source=config.token_source,
            allowed_hosts=config.allowed_hosts,
            workspaces=workspaces,
        )

    @property
    def upload_url(self) -> str:
        return f"{self._origin}/api/v1/projects/{self._project_id}/artifacts"

    def _resolve_file(self, server: str, artifact_path: str) -> Path:
        """config._launch_command paranoia: resolve symlinks FIRST, then
        containment; stat (never read) enforces the size cap."""
        workspace = self._workspaces.get(server)
        if workspace is None:
            raise ArtifactUploadError(REASON_WORKSPACE_UNKNOWN)
        root = workspace.resolve()
        candidate = (workspace / artifact_path).resolve()
        if not candidate.is_relative_to(root):
            raise ArtifactUploadError(REASON_PATH_ESCAPES)
        if not candidate.is_file():
            raise ArtifactUploadError(REASON_FILE_MISSING)
        if candidate.stat().st_size > self._max_bytes:
            raise ArtifactUploadError(REASON_FILE_TOO_LARGE)
        return candidate

    def _check_host(self) -> None:
        """SEC-M2 for the HTTP leg: the token only ever rides http(s) to a
        host on the SAME allowlist that guards the WS URL."""
        parsed = urlparse(self._origin)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or host not in self._allowed_hosts:
            raise ArtifactUploadError(REASON_HOST_NOT_ALLOWLISTED)

    async def _send(self, headers: Mapping[str, str], body: bytes) -> tuple[int, bytes]:
        try:
            return await asyncio.to_thread(
                self._post, self.upload_url, headers, body, self._timeout
            )
        except TimeoutError as exc:
            raise ArtifactUploadError(REASON_TIMEOUT) from exc
        except urllib.error.URLError as exc:
            reason = REASON_TIMEOUT if isinstance(exc.reason, TimeoutError) else REASON_CONNECTION
            raise ArtifactUploadError(reason) from exc
        except Exception as exc:
            logger.warning("artifact upload transport error: %s", type(exc).__name__)
            raise ArtifactUploadError(REASON_CONNECTION) from exc

    async def upload(
        self, *, server: str, artifact_path: str, source_tool: str, call_id: str
    ) -> dict[str, Any]:
        """Validate → upload → ArtifactRef dict. Raises ArtifactUploadError
        with one stable reason on ANY failure; refusals make zero HTTP calls."""
        file = self._resolve_file(server, artifact_path)  # zero HTTP on refusal
        self._check_host()  # before the token is even read
        token = self._token_source()
        if not token:
            raise ArtifactUploadError(REASON_UNAUTHORIZED)
        media_type = mimetypes.guess_type(file.name)[0] or FALLBACK_MEDIA_TYPE
        fields = {"media_type": media_type, "source_tool": source_tool, "call_id": call_id}
        body, content_type = _multipart_body(fields, file.name, media_type, file.read_bytes())
        headers = {"Authorization": f"Bearer {token}", "Content-Type": content_type}
        status, raw = await self._send(headers, body)
        if status != 201:
            reason = _STATUS_REASONS.get(status, REASON_FAILED)
            logger.warning(
                "artifact upload for call %.64s failed: HTTP %d -> %s", call_id, status, reason
            )
            raise ArtifactUploadError(reason)
        logger.info(
            "artifact for call %.64s uploaded (%d bytes, %s)", call_id, len(body), media_type
        )
        return _parse_ref(raw, call_id)
