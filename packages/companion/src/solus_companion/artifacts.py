"""Bulk tool output leaving the customer machine — BOTH transports.

Two paths land here because tools produce bulk bytes two different ways, and
neither subsumes the other:

* **PULL / staged (SOLUS-CAD-00c)** — a tool returns non-text content blocks
  INLINE. `ArtifactStore` holds the bytes in memory, the result carries a handle,
  and the cloud fetches them over the channel (`artifact_fetch` →
  `artifact_chunk`) only when a connector actually needs them.
* **PUSH / uploaded (SOLUSDEV-100)** — a tool writes a FILE to disk and returns
  `structuredContent.artifact_path`. `ArtifactUploader` POSTs it to the API and
  the result is rewritten with an `artifact_ref`.

They were written independently on two branches and merged here deliberately
rather than one replacing the other: a fork that streams inline bytes has no
file to upload, and a fork that writes a 200 MB STEP file to disk should not
have it staged in companion memory. `Dispatcher` accepts both seams and uses
whichever the result shape calls for.

Nothing in the staged path touches the filesystem: those bytes live in memory
only, so a crash leaves nothing behind on a customer's machine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import urllib.error
import urllib.request
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from solus_companion.config import (
    CompanionConfig,
    ServerLaunch,
    api_endpoint_from_ws_url,
)

# --- PULL: inline content blocks staged for the cloud to fetch (CAD-00c) ---

#: One artifact larger than this is refused outright. Matches the cloud's CAD
#: export bound so the two ends agree on what is transferable.
MAX_ARTIFACT_BYTES: Final = 64 * 1024 * 1024

#: Total staged bytes across all artifacts.
MAX_TOTAL_BYTES: Final = 128 * 1024 * 1024

#: Most artifacts held at once, regardless of size.
MAX_ARTIFACTS: Final = 16


@dataclass(frozen=True)
class StagedArtifact:
    """The handle that travels in a tool result; the bytes stay behind."""

    artifact_id: str
    media_type: str
    size_bytes: int


class ArtifactStore:
    def __init__(
        self,
        *,
        max_artifact_bytes: int = MAX_ARTIFACT_BYTES,
        max_total_bytes: int = MAX_TOTAL_BYTES,
        max_artifacts: int = MAX_ARTIFACTS,
    ) -> None:
        self._max_artifact_bytes = max_artifact_bytes
        self._max_total_bytes = max_total_bytes
        self._max_artifacts = max_artifacts
        self._items: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._total = 0

    def __len__(self) -> int:
        return len(self._items)

    def stage(self, payload: bytes, *, media_type: str) -> StagedArtifact:
        """Hold `payload` and return the handle to advertise to the cloud.

        Raises `ValueError` when the artifact alone exceeds the per-artifact
        budget — the caller turns that into a note on the tool result rather
        than a failed call.
        """
        if len(payload) > self._max_artifact_bytes:
            raise ValueError(
                f"artifact of {len(payload)} bytes exceeds the "
                f"{self._max_artifact_bytes} byte staging limit"
            )
        artifact_id = uuid.uuid4().hex
        self._items[artifact_id] = (payload, media_type)
        self._total += len(payload)
        self._evict()
        return StagedArtifact(
            artifact_id=artifact_id, media_type=media_type, size_bytes=len(payload)
        )

    def _evict(self) -> None:
        while self._items and (
            self._total > self._max_total_bytes or len(self._items) > self._max_artifacts
        ):
            _oldest, (payload, _media) = self._items.popitem(last=False)
            self._total -= len(payload)

    def get(self, artifact_id: str) -> bytes | None:
        item = self._items.get(artifact_id)
        return None if item is None else item[0]

    def chunks(self, artifact_id: str, *, chunk_bytes: int) -> Iterator[tuple[bytes, bool]]:
        """Yield `(chunk, is_final)` for one artifact; nothing for an unknown id.

        An EMPTY artifact still yields exactly one final chunk — otherwise the
        cloud would wait for a `final` frame that never arrives.
        """
        payload = self.get(artifact_id)
        if payload is None:
            return
        if not payload:
            yield b"", True
            return
        for offset in range(0, len(payload), chunk_bytes):
            chunk = payload[offset : offset + chunk_bytes]
            yield chunk, offset + chunk_bytes >= len(payload)

    def clear(self) -> None:
        self._items.clear()
        self._total = 0


# --- PUSH: a file the fork wrote to disk, uploaded to the API (SOLUSDEV-100) ---

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


def server_workspace(launch: ServerLaunch) -> Path | None:
    """The workspace the companion passed to that server: its declared
    `SOLUS_MCP_WORKSPACE`, else the fork dir (`bin/launch`'s own fallback).

    `None` for a VENDOR-RUN server (CAD-02): it has a `url:` and no launcher, so
    there is no fork directory to fall back to and Solus never chose its
    workspace. Callers must treat that as "cannot resolve a path here" — a
    vendor-run server's `artifact_path` cannot be confined and is refused
    (`REASON_WORKSPACE_UNKNOWN`), rather than being resolved against a guess.
    """
    raw = launch.env.get("SOLUS_MCP_WORKSPACE", "")
    if raw:
        return Path(raw)
    if launch.command is None:
        return None
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
    def from_config(cls, config: CompanionConfig) -> ArtifactUploader | None:
        """Build from the companion config; None when the WS URL is not a
        project bridge URL (uploads stay disabled, dispatch fails closed)."""
        endpoint = api_endpoint_from_ws_url(config.url)
        if endpoint is None:
            logger.warning("companion URL is not a project bridge URL; artifact uploads disabled")
            return None
        # A vendor-run (`url:`) server has no resolvable workspace, so it gets no
        # entry — `_resolve_file` then refuses it with REASON_WORKSPACE_UNKNOWN,
        # which is the behaviour we want and already have.
        workspaces = {
            launch.name: workspace
            for launch in config.servers
            if (workspace := server_workspace(launch)) is not None
        }
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
