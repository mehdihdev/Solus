"""SOLUSDEV-321 P5 (R102, R124) — a `returns_image` tool's output crossing into the API.

The fork uploads its file as this call's artifact (the existing upload path), and
`bridge.service.consume_tool_image` reads it once: only for a tool the Solus-owned allowlist flags,
only as this call's own artifact (`consume_tool_artifact`'s anti-forgery conditions), never more
than 2 MiB, and only when the bytes are what the companion claimed — a PNG or JPEG by its magic and
its header's dimensions (at most 4096 px a side), or a PDF by its header. `checked_image` is the
one gate an image passes before anything decodes it. The pull path (`fetch_artifact`) stays a
dormant seam: R124 routes the exports through uploads.
"""

from __future__ import annotations

import io
import logging
import struct
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from solus_api.agent.tools.shapes import ToolDescriptor, ToolResult
from solus_api.bridge.allowlist import BridgeToolSpec
from solus_api.bridge.service import (
    MAX_IMAGE_SIDE,
    MAX_TOOL_IMAGE_BYTES,
    PDF_MEDIA_TYPE,
    ImageRefusedError,
    ToolImage,
    checked_image,
    consume_tool_image,
)
from solus_api.models import Artifact, Project, Team, User
from solus_api.services.artifacts import create_artifact
from solus_api.storage import LocalArtifactStore
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

TOOL = "fake.export_view"
TTL = 3600
SHEET = Path(__file__).parent / "fixtures" / "render_sheet.pdf"


@dataclass(frozen=True)
class _ToolScope:
    maker: async_sessionmaker[AsyncSession]
    store: LocalArtifactStore
    project_id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID


async def _tool_scope(engine: AsyncEngine, tmp_path: Path) -> _ToolScope:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = User(supabase_user_id=f"img-{uuid.uuid4().hex}", email="img@example.com")
        team = Team(name="images")
        db.add_all([user, team])
        await db.flush()
        project = Project(team_id=team.id, name="images")
        db.add(project)
        await db.commit()
        return _ToolScope(
            maker, LocalArtifactStore(str(tmp_path / "store")), project.id, team.id, user.id
        )


def _image_bytes(fmt: str, size: tuple[int, int] = (32, 24)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format=fmt)
    return out.getvalue()


def _huge_png(width: int) -> bytes:
    """A PNG whose header states `width` px: only the header is ever read before the gate."""
    header = struct.pack(">IIBBBBB", width, 10, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", 13) + b"IHDR" + header
    return b"\x89PNG\r\n\x1a\n" + chunk + struct.pack(">I", zlib.crc32(b"IHDR" + header))


def _flagged_spec(returns_image: bool = True) -> BridgeToolSpec:
    return BridgeToolSpec(
        server="fake",
        remote_name="export_view",
        descriptor=ToolDescriptor(
            name=TOOL, description="export", params={"type": "object"}, returns={"type": "object"}
        ),
        returns_image=returns_image,
    )


async def _uploaded(
    scope: _ToolScope, data: bytes, media_type: str, *, call_id: str
) -> dict[str, Any]:
    """What the companion's upload leaves: the artifact row, and the ref its result carries."""
    async with scope.maker() as db:
        artifact = await create_artifact(
            db,
            scope.store,
            project_id=scope.project_id,
            created_by=scope.user_id,
            data=data,
            media_type=media_type,
            source_tool=TOOL,
            tool_call_id=call_id,
        )
        await db.commit()
    return {
        "artifact_id": str(artifact.id),
        "uri": artifact.uri,
        "media_type": media_type,
        "storage": "local",
        "size_bytes": len(data),
    }


async def _consume(
    scope: _ToolScope, ref: dict[str, Any], *, call_id: str, spec: BridgeToolSpec | None = None
) -> ToolImage | None:
    result = ToolResult.success(call_id, {"format": "pdf", "artifact_ref": ref, "degraded": False})
    async with scope.maker() as db:
        return await consume_tool_image(
            db,
            scope.store,
            spec=spec or _flagged_spec(),
            result=result,
            project_id=scope.project_id,
            team_id=scope.team_id,
            user_id=scope.user_id,
            ttl_seconds=TTL,
        )


async def _live(scope: _ToolScope, ref: dict[str, Any]) -> bool:
    async with scope.maker() as db:
        row = await db.get(Artifact, uuid.UUID(ref["artifact_id"]))
        return row is not None and row.deleted_at is None


async def test_only_flagged_tools_pull_staged_images_within_caps_and_magic_checks(
    engine: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    scope = await _tool_scope(engine, tmp_path)
    png, jpeg, pdf = _image_bytes("PNG"), _image_bytes("JPEG"), SHEET.read_bytes()

    # An unflagged tool's artifact is never read, so it is never consumed either.
    ref = await _uploaded(scope, png, "image/png", call_id="c-plain")
    assert await _consume(scope, ref, call_id="c-plain", spec=_flagged_spec(False)) is None
    assert await _live(scope, ref)

    # A flagged tool's PNG and PDF, each read once, as the type the bytes are.
    ref = await _uploaded(scope, png, "image/png", call_id="c-png")
    assert await _consume(scope, ref, call_id="c-png") == ToolImage("image/png", png)
    assert not await _live(scope, ref)
    ref = await _uploaded(scope, pdf, PDF_MEDIA_TYPE, call_id="c-pdf")
    assert await _consume(scope, ref, call_id="c-pdf") == ToolImage(PDF_MEDIA_TYPE, pdf)

    # Another call's artifact is not this call's: the anti-forgery check refuses it, untouched.
    ref = await _uploaded(scope, png, "image/png", call_id="c-other")
    assert await _consume(scope, ref, call_id="c-forged") is None
    assert await _live(scope, ref)

    with caplog.at_level(logging.WARNING, logger="solus.bridge.service"):
        mismatched = await _uploaded(scope, jpeg, "image/png", call_id="c-mismatch")
        assert await _consume(scope, mismatched, call_id="c-mismatch") is None
        not_ours = await _uploaded(scope, b"GIF89a" + bytes(64), "image/gif", call_id="c-gif")
        assert await _consume(scope, not_ours, call_id="c-gif") is None
        too_wide = await _uploaded(scope, _huge_png(MAX_IMAGE_SIDE + 1), "image/png", call_id="c-w")
        assert await _consume(scope, too_wide, call_id="c-w") is None
        oversize = await _uploaded(
            scope, png + bytes(MAX_TOOL_IMAGE_BYTES), "image/png", call_id="c-big"
        )
        assert await _consume(scope, oversize, call_id="c-big") is None

    logged = [record.getMessage() for record in caplog.records]
    # The mismatch names the claimed and the sniffed type; no line carries the bytes.
    assert any("image/png" in line and "image/jpeg" in line for line in logged)
    assert not any("\\x" in line or "JFIF" in line for line in logged)


def test_checked_image_reads_the_header_before_any_decode() -> None:
    png, jpeg = _image_bytes("PNG", (40, 30)), _image_bytes("JPEG", (40, 30))
    assert checked_image(png) == ("image/png", 40, 30)
    assert checked_image(jpeg) == ("image/jpeg", 40, 30)
    assert checked_image(_image_bytes("PNG", (MAX_IMAGE_SIDE, 1)))[1:] == (MAX_IMAGE_SIDE, 1)

    for refused in (
        SHEET.read_bytes(),  # a PDF is rasterised first, never decoded as an image
        _huge_png(MAX_IMAGE_SIDE),  # a header alone: nothing a decoder opens
        _huge_png(MAX_IMAGE_SIDE + 1),
        b"GIF89a" + bytes(64),
        b"\x89PNG\r\n\x1a\n" + b"not a header",
        png + bytes(MAX_TOOL_IMAGE_BYTES),
    ):
        with pytest.raises(ImageRefusedError):
            checked_image(refused)


def two_ihdr_png() -> bytes:
    """A 16x16 PNG with a second IHDR (9000x9000) before its data: the gate reads the first header,
    a decoder keeps the last (P5 fix 1, I1)."""
    png = _image_bytes("PNG", (16, 16))
    data = struct.pack(">IIBBBBB", 9000, 9000, 8, 2, 0, 0, 0)
    second = struct.pack(">I", 13) + b"IHDR" + data + struct.pack(">I", zlib.crc32(b"IHDR" + data))
    return png[:33] + second + png[33:]  # after the signature (8) and the first IHDR chunk (25)


def two_sof_jpeg() -> bytes:
    """A 16x16 JPEG with a second start-of-frame (9000x9000) before its scan (I1)."""
    jpeg = _image_bytes("JPEG", (16, 16))
    at = jpeg.index(b"\xff\xc0")
    end = at + 2 + struct.unpack(">H", jpeg[at + 2 : at + 4])[0]
    second = jpeg[at : at + 5] + struct.pack(">HH", 9000, 9000) + jpeg[at + 9 : end]
    return jpeg[:end] + second + jpeg[end:]


def test_bytes_a_decoder_reads_at_another_size_are_refused() -> None:
    """I1: the gate reads the first IHDR or SOF and a decoder the last, so bytes whose headers
    disagree are refused before anything allocates their pixels, the reason naming both sizes."""
    for crafted in (two_ihdr_png(), two_sof_jpeg()):
        with pytest.raises(ImageRefusedError, match="16x16.*9000x9000"):
            checked_image(crafted)
    assert checked_image(_image_bytes("JPEG", (16, 16))) == ("image/jpeg", 16, 16)


async def test_a_ref_that_understates_its_size_is_refused_once_read(
    engine: AsyncEngine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The ref's `size_bytes` is the companion's word, checked first; bytes past the cap that it
    understated are refused by their own length once read (P5 fix 1, M9)."""
    scope = await _tool_scope(engine, tmp_path)
    data = _image_bytes("PNG") + bytes(MAX_TOOL_IMAGE_BYTES)
    ref = {**await _uploaded(scope, data, "image/png", call_id="c-under"), "size_bytes": 64}

    with caplog.at_level(logging.WARNING, logger="solus.bridge.service"):
        assert await _consume(scope, ref, call_id="c-under") is None

    assert not await _live(scope, ref)  # consumed once, then dropped
    assert any(str(len(data)) in record.getMessage() for record in caplog.records)
