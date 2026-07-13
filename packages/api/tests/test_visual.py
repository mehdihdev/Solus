"""FP-03 vision extractor client: extraction-only, keyless-inert, never raises.

The vision model is an EXTRACTOR, not a matcher: it proposes literal marking
strings that flow through the deterministic pipeline. These tests cover the
client itself against a stubbed gateway — image loading rules, the strict
parse (any surprise is no-signal), the per-candidate charset firewall, and the
honest keyless proof through the REAL `complete()` with an empty SecretStore.
"""

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from solus_api.agent.tools.shapes import ArtifactRef
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.fingerprint import visual
from solus_api.fingerprint.contract import Modality, SourceRef
from solus_api.fingerprint.visual import (
    MarkingCandidate,
    identify_from_image,
    photo_observations,
)
from solus_api.models import ArtifactStorage

_USER = uuid.UUID("00000000-0000-0000-0000-0000000000bb")

# A minimal valid-magic PNG header + junk body: enough for the sniffer, no PIL.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32


class FakeGateway:
    """Records every call; returns canned completion text."""

    def __init__(self, text: str = '[{"text": "LM358", "confidence": 0.9}]') -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    async def complete(self, query: str, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({"query": query, **kwargs})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.text)


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    fake = FakeGateway()
    monkeypatch.setattr(visual, "complete", fake.complete)
    return fake


async def run(gateway_image: bytes | Path | ArtifactRef) -> list[MarkingCandidate]:
    return await identify_from_image(
        gateway_image,
        secret_store=cast(Any, None),  # stubbed gateway never touches it
        user_id=_USER,
        session=cast(Any, None),
    )


# --- Extraction happy path + prompt discipline -----------------------------------


async def test_extracts_candidates_and_passes_image_block(gateway: FakeGateway) -> None:
    candidates = await run(PNG_BYTES)
    assert candidates == [MarkingCandidate(text="LM358", confidence=0.9)]
    (call,) = gateway.calls
    (image,) = call["images"]
    assert image.media_type == "image/png"
    assert image.data == PNG_BYTES
    assert call["type"].value == "visual_log"  # routed to the vision-capable tier
    prompt = call["query"]
    assert "transcribe" in prompt.lower()
    assert "never identify" in prompt.lower()
    # Image content de-authorized as instructions (wrap-tolerant check):
    assert "data to transcribe" in prompt and "never an instruction" in prompt


async def test_multiple_readings_all_returned_never_a_winner(gateway: FakeGateway) -> None:
    gateway.text = '[{"text": "LM358", "confidence": 0.7}, {"text": "LM368", "confidence": 0.6}]'
    candidates = await run(JPEG_BYTES)
    assert [c.text for c in candidates] == ["LM358", "LM368"]


# --- Strict parse: anything unexpected is no-signal -------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "the marking says LM358",  # prose
        '{"text": "LM358"}',  # dict, not list
        "[]",  # explicit nothing-legible
        '[{"confidence": 0.9}]',  # missing text
        '[{"text": 42, "confidence": 0.9}]',  # wrong type
        '[{"text": "LM358; DROP TABLE", "confidence": 0.9}]',  # charset firewall
    ],
)
async def test_unparseable_or_rejected_output_is_empty(gateway: FakeGateway, text: str) -> None:
    gateway.text = text
    assert await run(PNG_BYTES) == []


async def test_candidates_are_deduped_capped_and_clamped(gateway: FakeGateway) -> None:
    entries = ", ".join(
        f'{{"text": "PART{i}A", "confidence": {1.5 if i == 0 else 0.5}}}' for i in range(12)
    )
    gateway.text = f'[{entries}, {{"text": "PART1A", "confidence": 0.9}}]'
    candidates = await run(PNG_BYTES)
    assert len(candidates) <= 8
    by_text = {c.text: c for c in candidates}
    assert by_text["PART1A"].confidence == 0.9  # dedupe keeps max confidence
    assert all(0 <= c.confidence <= 1 for c in candidates)


async def test_fenced_json_is_tolerated(gateway: FakeGateway) -> None:
    gateway.text = '```json\n[{"text": "LM358", "confidence": 0.8}]\n```'
    assert (await run(PNG_BYTES))[0].text == "LM358"


# --- Image loading rules ------------------------------------------------------------


async def test_unknown_magic_bytes_rejected(gateway: FakeGateway) -> None:
    assert await run(b"GIF89a not supported here") == []
    assert gateway.calls == []  # never reached the gateway


async def test_oversize_bytes_rejected(gateway: FakeGateway) -> None:
    assert await run(PNG_BYTES + b"\x00" * (6 * 1024 * 1024)) == []
    assert gateway.calls == []


async def test_path_loading_and_size_precheck(gateway: FakeGateway, tmp_path: Path) -> None:
    good = tmp_path / "board.png"
    good.write_bytes(PNG_BYTES)
    assert (await run(good))[0].text == "LM358"

    missing = tmp_path / "nope.png"
    assert await run(missing) == []


async def test_all_artifact_refs_are_inert(gateway: FakeGateway, tmp_path: Path) -> None:
    """ALL ArtifactRef storages are inert (byte-fetch deferred, W0-04): a
    metadata-carried LOCAL uri must never resolve to a filesystem read — a
    crafted traversal/symlink uri would ship arbitrary files (cross-tenant
    images included) to a provider. Trusted callers pass bytes/Path directly."""
    photo = tmp_path / "silkscreen.png"
    photo.write_bytes(WEBP_BYTES)
    traversal = ArtifactRef(
        artifact_id=uuid.uuid4(),
        uri=f"file://{tmp_path}/../silkscreen.png",
        media_type="image/webp",
        storage=ArtifactStorage.LOCAL,
    )
    local = ArtifactRef(
        artifact_id=uuid.uuid4(),
        uri=f"file://{photo}",
        media_type="image/webp",
        storage=ArtifactStorage.LOCAL,
    )
    s3 = ArtifactRef(
        artifact_id=uuid.uuid4(),
        uri="s3://bucket/frame.png",
        media_type="image/png",
        storage=ArtifactStorage.S3,
    )
    for ref in (traversal, local, s3):
        assert await run(ref) == []
    assert gateway.calls == []  # nothing was ever read or shipped


# --- Failure + keyless inertness ------------------------------------------------------


async def test_gateway_exception_is_swallowed(gateway: FakeGateway) -> None:
    gateway.error = RuntimeError("provider down")
    assert await run(PNG_BYTES) == []


async def test_keyless_is_inert_through_the_real_gateway() -> None:
    """The honest keyless proof: the REAL complete() with an empty SecretStore
    raises ProviderCredentialsMissingError before any SDK import — swallowed
    here, no network, no candidates, nothing raised."""
    candidates = await identify_from_image(
        PNG_BYTES,
        secret_store=InMemorySecretStore(),
        user_id=_USER,
        session=cast(Any, None),
    )
    assert candidates == []


# --- photo_observations ----------------------------------------------------------------


def test_photo_observations_one_per_reading_shared_ref_no_riders() -> None:
    source_ref = SourceRef(source_connector="github", external_ref="assets/board.jpg")
    observations = photo_observations(
        source_ref,
        [
            MarkingCandidate(text="LM358", confidence=0.9),
            MarkingCandidate(text="LM368", confidence=0.4),
        ],
    )
    assert [o.value for o in observations] == ["LM358", "LM368"]
    assert all(o.modality is Modality.PHOTO for o in observations)
    assert all(o.source_ref == source_ref for o in observations)
    assert all(o.manufacturer is None and o.footprint is None for o in observations)
