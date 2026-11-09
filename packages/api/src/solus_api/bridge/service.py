"""Transport-free channel logic: dispatch, result ingress, supersede, limits.

Delivery is at-most-once (contract §5): a tool_call is written once to the live
socket; socket death fails every in-flight call fast and retryably — retry
belongs to SOL via the W0-04 `retryable` flag, never to the wire. Timeouts are
owned by `ToolRegistry.invoke`'s asyncio.wait_for — nothing here re-times.
"""

import asyncio
import base64
import binascii
import io
import logging
import time
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.command_output import STREAMING_TOOLS, current_output
from solus_api.agent.screen import _SCREENSHOT_MAGIC, ScreenshotError, _image_dims
from solus_api.agent.tools.shapes import ArtifactRef, ToolCall, ToolErrorCode, ToolResult
from solus_api.agent.tools.tool import ToolException
from solus_api.agent.tools.untrusted import call_display_paths
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.frames import (
    ArtifactChunkData,
    ToolOutputData,
    artifact_fetch_frame,
    redact_text,
    redact_value,
    tool_call_frame,
)
from solus_api.bridge.registry import BridgeSession
from solus_api.core.errors import APIError
from solus_api.models import User
from solus_api.services.artifacts import consume_tool_artifact
from solus_api.services.events import emit_event

if TYPE_CHECKING:
    from solus_api.storage import ArtifactStore

logger = logging.getLogger("solus.bridge.service")

SUPERSEDED_EVENT = "bridge.session_superseded"

#: Hard ceiling on one pulled artifact. Matches the CAD export bound so the two
#: ends agree on what is transferable (SOLUS-CAD-00c).
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

#: Whole-transfer deadline. Per-chunk stalls are covered by it too, so a
#: companion that goes quiet mid-stream cannot pin a worker.
ARTIFACT_FETCH_TIMEOUT_SECONDS = 300.0

# --------------------------------------------------------------- tool images (SOLUSDEV-321 P5)
#
# R102/R124: a `returns_image` tool's output crosses into the API as this call's one uploaded
# artifact. The bytes say what they are; the media type the companion claimed is only compared.

MAX_TOOL_IMAGE_BYTES: Final = 2 * 1024 * 1024
MAX_IMAGE_SIDE: Final = 4096
PDF_MEDIA_TYPE: Final = "application/pdf"
_PDF_MAGIC: Final = b"%PDF-"
#: The decoder's name for each type the gate admits: an image is opened only as what its bytes are.
PIL_FORMATS: Final = MappingProxyType({"image/png": "PNG", "image/jpeg": "JPEG"})


class ImageRefusedError(ValueError):
    """The bytes are not an image the API reads; the message names why, never the bytes."""


@dataclass(frozen=True)
class ToolImage:
    """A flagged tool's checked output: the type its bytes ARE, and the bytes."""

    media_type: str
    data: bytes


def sniffed_media_type(raw: bytes) -> str | None:
    """The type `raw` is by its leading bytes — PNG, JPEG or PDF — or None."""
    if raw.startswith(_PDF_MAGIC):
        return PDF_MEDIA_TYPE
    return next((kind for kind, magic in _SCREENSHOT_MAGIC.items() if raw.startswith(magic)), None)


def checked_image(raw: bytes) -> tuple[str, int, int]:
    """`(media type, width, height)` of a PNG or JPEG of at most `MAX_TOOL_IMAGE_BYTES` and
    `MAX_IMAGE_SIDE` px a side, read from its magic and its header (`agent/screen.py`) before
    anything decodes it, else `ImageRefusedError`. The one gate every image passes on its way to a
    decoder (R102): a companion's, a renderer's and a rasterised page alike.

    The header read takes the FIRST IHDR or SOF; a decoder keeps the LAST (P5 fix 1, I1). So the
    bytes are also opened lazily as that type alone (headers, no pixels), and refused unless that
    size is the header's."""
    if len(raw) > MAX_TOOL_IMAGE_BYTES:
        raise ImageRefusedError(f"the image exceeds {MAX_TOOL_IMAGE_BYTES} bytes")
    media_type = sniffed_media_type(raw)
    if media_type is None or media_type == PDF_MEDIA_TYPE:
        raise ImageRefusedError("the bytes are not a PNG or a JPEG")
    try:
        width, height = _image_dims(raw, media_type)
    except ScreenshotError:
        raise ImageRefusedError("the image header is not a valid PNG or JPEG") from None
    if max(width, height) > MAX_IMAGE_SIDE:
        raise ImageRefusedError(f"the image exceeds {MAX_IMAGE_SIDE} px a side")
    decoded = _decoded_size(raw, media_type)
    if decoded is None:
        raise ImageRefusedError("the bytes do not open as the image their header describes")
    if decoded != (width, height):
        raise ImageRefusedError(
            f"the image's headers disagree: {width}x{height} first, "
            f"{decoded[0]}x{decoded[1]} as decoded"
        )
    return media_type, width, height


def _decoded_size(raw: bytes, media_type: str) -> tuple[int, int] | None:
    """The size a decoder would allocate: `raw` opened lazily as `media_type` alone (its headers
    are read, never its pixels), or None when it does not open as that."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(raw), formats=[PIL_FORMATS[media_type]]) as opened:
            return opened.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


async def consume_tool_image(
    session: AsyncSession,
    store: "ArtifactStore",
    *,
    spec: BridgeToolSpec,
    result: ToolResult,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    ttl_seconds: int,
) -> ToolImage | None:
    """The one artifact a `returns_image` tool uploaded for this call, consumed and checked, or
    None (R102, R124).

    Only a flagged tool's output is read, and only as this result's `artifact_ref`: the companion
    uploads one file per call, so that is all a call can hand over. The artifact must pass every
    anti-forgery condition of `consume_tool_artifact` (this project and team, this user, this
    tool, this call, live, read once). Its bytes must be at most `MAX_TOOL_IMAGE_BYTES` and be
    what the companion claimed: a PNG or JPEG through `checked_image`, or a PDF by its header (a
    renderer rasterises it). Anything else is dropped with a log line naming the types, never the
    bytes."""
    name = spec.descriptor.name
    value = result.value if result.ok else None
    if not spec.returns_image or value is None:
        return None
    try:
        ref = ArtifactRef.model_validate(value.get("artifact_ref"))
    except ValidationError:
        logger.warning("bridge tool %s returned no usable artifact_ref", name)
        return None
    if ref.size_bytes is not None and ref.size_bytes > MAX_TOOL_IMAGE_BYTES:
        logger.warning("bridge tool %s artifact dropped: it claims %d bytes", name, ref.size_bytes)
        return None
    try:
        data, claimed = await consume_tool_artifact(
            session,
            store,
            project_id=project_id,
            team_id=team_id,
            artifact_id=ref.artifact_id,
            requester_id=user_id,
            source_tool=name,
            tool_call_id=result.call_id,
            ttl_seconds=ttl_seconds,
        )
    except APIError:
        logger.warning("bridge tool %s artifact missing, expired or not this call's", name)
        return None
    return _checked_tool_image(name, data, claimed)


def _checked_tool_image(tool: str, data: bytes, claimed: str) -> ToolImage | None:
    sniffed = sniffed_media_type(data)
    try:
        if len(data) > MAX_TOOL_IMAGE_BYTES or sniffed is None or sniffed != claimed.lower():
            raise ImageRefusedError("the bytes are not what the companion claimed")
        if sniffed != PDF_MEDIA_TYPE:
            checked_image(data)
    except ImageRefusedError as exc:
        # Types and a size only: the claim is bounded companion text, the bytes are never logged.
        logger.warning(
            "bridge tool %s image dropped (%s): claimed %.64r, bytes are %s, %d bytes",
            tool,
            exc,
            claimed,
            sniffed,
            len(data),
        )
        return None
    return ToolImage(sniffed, data)


async def dispatch(
    session: BridgeSession, tool_name: str, args: dict[str, object], *, call_cap_bytes: int
) -> ToolResult:
    """Send one tool_call and await its (already-redacted) result.

    Raises ToolException for: overflow (immediate, retryable), oversize args
    (permanent), send failure / disconnect / supersede (retryable). The wire
    call_id is minted HERE — the registry never forwards SOL's call_id into
    `tool.invoke`, so the two id spaces are separate by construction.
    """
    if session.entered >= session.max_inflight * 2:
        # max_inflight running + max_inflight queued; beyond that fail fast
        # (contract §7 loop-guard: bounded outstanding work).
        raise ToolException("bridge busy", retryable=True)
    call = ToolCall(tool=tool_name, args=dict(args))
    frame = tool_call_frame(call)
    if len(frame.encode()) > call_cap_bytes:
        raise ToolException(f"tool call for {tool_name!r} exceeds the size cap", retryable=False)
    session.entered += 1
    try:
        async with session.slots:
            loop = asyncio.get_running_loop()
            future: asyncio.Future[ToolResult] = loop.create_future()
            session.inflight[call.call_id] = future
            paths = call_display_paths(tool_name, call.args)
            if paths:
                session.write_paths[call.call_id] = next(iter(paths))
            sink = current_output.get()
            if tool_name in STREAMING_TOOLS and sink is not None:
                session.output_sinks[call.call_id] = sink
            try:
                try:
                    await session.send(frame)
                except Exception as exc:
                    raise ToolException("bridge disconnected", retryable=True) from exc
                return await future
            finally:
                # Timeout-cancellation or completion: a late result for this id
                # is then dropped as unknown (contract §5).
                session.inflight.pop(call.call_id, None)
                session.write_paths.pop(call.call_id, None)
                session.output_sinks.pop(call.call_id, None)
                session.output_limits.pop(call.call_id, None)
    finally:
        session.entered -= 1


def ingest_output(session: BridgeSession, output: ToolOutputData) -> None:
    future = session.inflight.get(output.call_id)
    sink = session.output_sinks.get(output.call_id)
    if future is None or future.done() or sink is None:
        return
    sequence, size = session.output_limits.get(output.call_id, (0, 0))
    next_size = size + len(output.text.encode())
    if output.sequence <= sequence:
        return
    if next_size > 262144:
        sink.truncate()
        return
    session.output_limits[output.call_id] = (output.sequence, next_size)
    # The sink buffers complete lines before redaction. Masking fragments here
    # could erase the secret's key while leaving its next-chunk value visible.
    sink.append(output.stream, output.text)
    if output.truncated:
        sink.truncate()


def ingest_result(session: BridgeSession, result: ToolResult) -> None:
    """Deliver a companion result to its waiting dispatcher. Unknown, foreign,
    or already-answered call_ids are dropped + logged (replay defense, §5);
    first result wins. `value` is redacted BEFORE it can reach a consumer."""
    path = session.write_paths.pop(result.call_id, None)
    future = session.inflight.pop(result.call_id, None)
    if future is None or future.done():
        logger.warning(
            "bridge session %s dropped result for unknown call_id %.64s",
            session.session_id,
            result.call_id,
        )
        return
    if result.ok and result.value is not None:
        result = ToolResult.success(
            result.call_id,
            redact_value(
                result.value, allowed_paths=frozenset({path}) if path is not None else frozenset()
            ),
        )
    elif result.error is not None:
        # SEC-M3: the error channel feeds model context/persistence too —
        # redact it exactly like values.
        result = ToolResult.failure(
            result.call_id,
            result.error.model_copy(update={"message": redact_text(result.error.message)}),
        )
    future.set_result(result)


def fail_inflight(session: BridgeSession, message: str) -> None:
    """Resolve every pending dispatcher with a retryable failure (§5)."""
    pending = list(session.inflight.values())
    session.inflight.clear()
    session.write_paths.clear()
    for future in pending:
        if not future.done():
            future.set_exception(ToolException(message, retryable=True))


async def supersede(
    old: BridgeSession,
    new: BridgeSession,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The §3 single-active-session sequence: close the old socket 4409, fail
    its in-flight calls fast, and emit the stolen-JWT tripwire event carrying
    BOTH instance ids."""
    from solus_api.bridge.frames import CLOSE_SUPERSEDED

    fail_inflight(old, "bridge session superseded")
    try:
        await old.close(CLOSE_SUPERSEDED)
    except Exception:  # the old socket may already be dead — that is fine
        logger.debug("bridge session %s close after supersede failed", old.session_id)
    async with sessionmaker() as db:
        user = await db.get(User, new.user_id)
        if user is None:  # pragma: no cover — scope was verified at bind
            return
        emit_event(
            db,
            user=user,
            event_type=SUPERSEDED_EVENT,
            team_id=new.team_id,
            project_id=new.project_id,
            payload={
                "old_companion_instance_id": old.companion_instance_id,
                "new_companion_instance_id": new.companion_instance_id,
                "old_session_id": old.session_id,
                "new_session_id": new.session_id,
            },
        )
        await db.commit()


@dataclass
class TokenBucket:
    """Per-session message-rate bucket (contract §7): `rate`/s sustained with
    `burst` headroom. WS scope never passes the HTTP RateLimitMiddleware, so
    the handler carries its own bucket."""

    rate: float
    burst: int
    tokens: float = field(default=0.0)
    updated: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.tokens = float(self.burst)
        self.updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(float(self.burst), self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True


class ConnectRateLimiter:
    """Fixed-window per-key connect-attempt limiter (contract §7), bounded in
    tracked keys like core/ratelimit.py. Key = user id (post-auth)."""

    _MAX_TRACKED = 10_000
    _WINDOW_SECONDS = 60.0

    def __init__(self, limit_per_minute: int) -> None:
        self._limit = limit_per_minute
        self._counts: dict[str, tuple[float, int]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start, count = self._counts.get(key, (now, 0))
        if now - window_start >= self._WINDOW_SECONDS:
            window_start, count = now, 0
        if count >= self._limit:
            self._counts[key] = (window_start, count)
            return False
        if len(self._counts) >= self._MAX_TRACKED and key not in self._counts:
            self._counts.clear()  # ponytail: crude reset at the bound, like core/ratelimit
        self._counts[key] = (window_start, count + 1)
        return True


async def fetch_artifact(
    session: BridgeSession,
    artifact_id: str,
    *,
    max_bytes: int = MAX_ARTIFACT_BYTES,
    timeout_seconds: float = ARTIFACT_FETCH_TIMEOUT_SECONDS,
) -> bytes:
    """Pull the bytes behind a staged handle (SOLUS-CAD-00c).

    The companion answers with `artifact_chunk` frames until one carries
    `final`. Bounded three ways — total size, whole-transfer deadline, and the
    session dying — because everything the companion sends is untrusted input
    (CLAUDE.md §7) and a bulk channel is the obvious place to exhaust a worker.

    Raises `ToolException` on every failure path so callers keep the W0-04
    never-raises story; nothing here returns a partial artifact.

    SOLUSDEV-321 P5 (R124): still a dormant seam. A render's export reaches the API
    by the upload path (`consume_tool_image`); a later pull-based transport would
    pass its bytes through the same `checked_image` gate.
    """
    fetch_id = uuid.uuid4().hex
    queue: asyncio.Queue[ArtifactChunkData] = asyncio.Queue()
    session.artifact_fetches[fetch_id] = queue
    chunks: list[bytes] = []
    total = 0
    try:
        await session.send(artifact_fetch_frame(artifact_id=artifact_id, fetch_id=fetch_id))
    except Exception as exc:
        session.artifact_fetches.pop(fetch_id, None)
        raise ToolException(
            "bridge disconnected", code=ToolErrorCode.UNAVAILABLE, retryable=True
        ) from exc
    try:
        async with asyncio.timeout(timeout_seconds):
            while True:
                chunk = await queue.get()
                if chunk.error:
                    raise ToolException(
                        f"artifact unavailable: {chunk.error[:200]}",
                        code=ToolErrorCode.NOT_FOUND,
                        retryable=False,
                    )
                try:
                    payload = base64.b64decode(chunk.data, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise ToolException(
                        "artifact chunk was not valid base64",
                        code=ToolErrorCode.TOOL_ERROR,
                        retryable=False,
                    ) from exc
                total += len(payload)
                if total > max_bytes:
                    raise ToolException(
                        "artifact exceeds the transfer limit",
                        code=ToolErrorCode.TOOL_ERROR,
                        retryable=False,
                    )
                chunks.append(payload)
                if chunk.final:
                    return b"".join(chunks)
    except TimeoutError as exc:
        raise ToolException(
            "artifact transfer timed out", code=ToolErrorCode.TIMEOUT, retryable=True
        ) from exc
    finally:
        session.artifact_fetches.pop(fetch_id, None)


def ingest_artifact_chunk(session: BridgeSession, chunk: ArtifactChunkData) -> None:
    """Route one inbound chunk to its waiting fetch. An unknown `fetch_id` is
    dropped and logged — the same replay defence `ingest_result` applies."""
    queue = session.artifact_fetches.get(chunk.fetch_id)
    if queue is None:
        logger.warning(
            "bridge session %s dropped chunk for unknown fetch_id %.64s",
            session.session_id,
            chunk.fetch_id,
        )
        return
    queue.put_nowait(chunk)


def fail_artifact_fetches(session: BridgeSession) -> None:
    """Disconnect: unblock every waiting pull with an error chunk."""
    for fetch_id, queue in list(session.artifact_fetches.items()):
        queue.put_nowait(ArtifactChunkData(fetch_id=fetch_id, final=True, error="bridge offline"))
    session.artifact_fetches.clear()
