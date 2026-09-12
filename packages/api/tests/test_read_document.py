"""`read_document` + `propose_part_definition` (SOLUSDEV-252 P6): PDF pages via
vision, page-cited proposals, a candidate PartDefinition built ONLY from what the
pages said, and a gated hand-off into the project's `.solus` Hardware section.
No network, no real model: httpx.MockTransport and a monkeypatched gateway."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import create_project, create_team, me
from fixtures.datasheet import (
    HOSTILE_READ,
    HOSTILE_TEXT,
    PAGE_ONE_READ,
    PAGE_TWO_READ,
    two_page_pdf,
)
from fixtures.screenshot import PNG_MAGIC
from solus_api.agent.documents import extract, fetch, pdf
from solus_api.agent.documents.extract import DocumentProposal, extract_pages, parse_proposals
from solus_api.agent.documents.fetch import fetch_pdf
from solus_api.agent.documents.pdf import MAX_PDF_BYTES, DocumentError, render_pages
from solus_api.agent.tools import ToolCall, ToolRegistry
from solus_api.agent.tools import read_document as tool_module
from solus_api.agent.tools.read_document import (
    PROPOSE_PART_DEFINITION_DESCRIPTOR,
    READ_DOCUMENT_DESCRIPTOR,
    candidate_definition,
    register_document_tools,
)
from solus_api.connectors.secrets import InMemorySecretStore
from solus_api.hardware.library import PartDefinition
from solus_api.models import Artifact, SolusEntry, SolusSection
from solus_api.orchestration import gateway
from solus_api.orchestration.enums import Complexity, RouteType
from solus_api.services.artifacts import create_artifact
from solus_api.storage import LocalArtifactStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

# ------------------------------------------------------------------ render


def test_render_pages_yields_one_png_per_page_at_the_target_width() -> None:
    rendered = render_pages(two_page_pdf(title="XY-1234 datasheet"))
    assert rendered.page_count == 2
    assert rendered.title == "XY-1234 datasheet"
    assert [page.index for page in rendered.pages] == [1, 2]
    for page in rendered.pages:
        assert page.png.startswith(PNG_MAGIC)
        assert page.width == 1400
        assert page.height == 700  # 200x100 pt page, scaled to width


def test_render_pages_honours_the_page_selection_and_the_page_cap() -> None:
    assert [p.index for p in render_pages(two_page_pdf(), pages=[2, 9]).pages] == [2]
    assert [p.index for p in render_pages(two_page_pdf(), max_pages=1).pages] == [1]
    assert render_pages(two_page_pdf(), pages=[]).pages == []


@pytest.mark.parametrize(
    "data", [b"not a pdf at all", b"%PDF-1.4 truncated garbage", b"%PDF-" + b"x" * MAX_PDF_BYTES]
)
def test_render_pages_refuses_non_pdf_broken_and_oversized_input(data: bytes) -> None:
    with pytest.raises(DocumentError):
        render_pages(data)


def test_a_missing_renderer_is_a_clear_document_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pypdfium2", None)  # import raises ImportError
    with pytest.raises(DocumentError, match="unavailable"):
        render_pages(two_page_pdf())


# ------------------------------------------------------------------- fetch


async def _resolve_public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_fetch_pdf_streams_a_pdf_from_a_public_https_host() -> None:
    body = two_page_pdf()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=body)

    data = await fetch_pdf(
        "https://vendor.example/ds.pdf", transport=_transport(handler), resolver=_resolve_public
    )
    assert data == body


@pytest.mark.parametrize(
    "url",
    [
        "http://vendor.example/ds.pdf",
        "https://127.0.0.1/ds.pdf",
        "https://10.0.0.7/ds.pdf",
        "https://[::1]/ds.pdf",
        "https://169.254.169.254/latest/meta-data",
        "ftp://vendor.example/ds.pdf",
        "not a url",
    ],
)
async def test_fetch_pdf_refuses_http_and_non_public_addresses_before_connecting(
    url: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no connection may be attempted")

    with pytest.raises(DocumentError):
        await fetch_pdf(url, transport=_transport(handler), resolver=_resolve_public)


async def test_fetch_pdf_refuses_a_hostname_that_resolves_to_a_private_address() -> None:
    async def resolve_private(_host: str) -> list[str]:
        return ["192.168.1.20"]

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no connection may be attempted")

    with pytest.raises(DocumentError, match="private"):
        await fetch_pdf(
            "https://intranet.example/ds.pdf",
            transport=_transport(handler),
            resolver=resolve_private,
        )


async def test_fetch_pdf_enforces_the_byte_cap_and_the_pdf_check() -> None:
    def big(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=b"%PDF-" + b"x" * 200
        )

    with pytest.raises(DocumentError, match="exceeds"):
        await fetch_pdf(
            "https://vendor.example/ds.pdf",
            transport=_transport(big),
            resolver=_resolve_public,
            max_bytes=100,
        )

    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")

    with pytest.raises(DocumentError, match="not a PDF"):
        await fetch_pdf(
            "https://vendor.example/ds.pdf", transport=_transport(html), resolver=_resolve_public
        )

    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(DocumentError, match="404"):
        await fetch_pdf(
            "https://vendor.example/ds.pdf", transport=_transport(missing), resolver=_resolve_public
        )


async def test_fetch_pdf_follows_at_most_three_same_scheme_redirects() -> None:
    body = two_page_pdf()

    def hop(request: httpx.Request) -> httpx.Response:
        n = int(request.url.path.strip("/") or 0)
        if n < 2:
            return httpx.Response(302, headers={"location": f"https://vendor.example/{n + 1}"})
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=body)

    assert (
        await fetch_pdf(
            "https://vendor.example/0", transport=_transport(hop), resolver=_resolve_public
        )
        == body
    )

    def forever(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://vendor.example/again"})

    with pytest.raises(DocumentError, match="redirect"):
        await fetch_pdf(
            "https://vendor.example/0", transport=_transport(forever), resolver=_resolve_public
        )

    def downgrade(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://vendor.example/plain"})

    with pytest.raises(DocumentError):
        await fetch_pdf(
            "https://vendor.example/0", transport=_transport(downgrade), resolver=_resolve_public
        )


# ----------------------------------------------------------------- extract


def test_parse_proposals_keeps_well_formed_lines_and_stamps_the_page() -> None:
    proposals = parse_proposals(PAGE_ONE_READ, page=1)
    assert [p.kind for p in proposals] == ["other", "other", "other", "rating", "pinout"]
    assert all(p.page == 1 for p in proposals)
    rating = proposals[3]
    assert (rating.name, rating.value, rating.unit) == ("supply voltage", "1.71 to 3.6", "V")
    assert rating.quote == "VDD 1.71 V to 3.6 V"


def test_parse_proposals_accepts_a_fenced_json_array_and_caps_quotes() -> None:
    long_quote = "q" * 1000
    text = (
        '```json\n[{"kind":"timing","name":"t","value":"1","unit":"ms","quote":"'
        + long_quote
        + '"}, 7, {"kind":"rating"}]\n```'
    )
    [only] = parse_proposals(text, page=3)
    assert only.page == 3
    assert len(only.quote) == 240


def test_parse_proposals_never_raises_on_garbage() -> None:
    assert parse_proposals("", page=1) == []
    assert parse_proposals("{not json", page=1) == []
    assert parse_proposals('{"kind":"rating","name":"","value":"x","quote":""}', page=1) == []


class _Completion:
    def __init__(self, text: str) -> None:
        self.text = text


def _script(monkeypatch: pytest.MonkeyPatch, reads: dict[int, str]) -> list[dict[str, Any]]:
    """gateway.complete → the scripted read for the page (by call order)."""
    calls: list[dict[str, Any]] = []

    async def complete(query: str, **kw: Any) -> Any:
        calls.append({"query": query, **kw})
        text = reads.get(len(calls))
        if text is None:
            raise RuntimeError("provider blew up")
        return _Completion(text)

    monkeypatch.setattr(gateway, "complete", complete)
    return calls


async def _extract(pages: list[Any], **kw: Any) -> tuple[list[DocumentProposal], list[str]]:
    return await extract_pages(
        pages,
        question=kw.pop("question", None),
        secret_store=InMemorySecretStore(),
        user_id=uuid.uuid4(),
        session=object(),  # type: ignore[arg-type]
        **kw,
    )


async def test_extract_pages_is_one_visual_log_call_per_page_with_a_solus_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _script(monkeypatch, {1: PAGE_ONE_READ, 2: PAGE_TWO_READ})
    rendered = render_pages(two_page_pdf())
    proposals, notes = await _extract(rendered.pages, question="what is the I2C address?")
    assert len(calls) == 2
    for call, page in zip(calls, rendered.pages, strict=True):
        assert call["type"] is RouteType.VISUAL_LOG
        assert call["complexity"] is Complexity.STANDARD
        assert call["max_tokens"] == extract.EXTRACT_MAX_TOKENS
        assert [img.data for img in call["images"]] == [page.png]
        assert "never an instruction" in call["query"]
        assert "<<<SOLUS-DATA" in call["query"]  # the question rides as fenced data
        assert "what is the I2C address?" in call["query"]
    assert {p.page for p in proposals} == {1, 2}
    assert notes == []


async def test_extract_pages_degrades_per_page_and_stops_at_the_call_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _script(monkeypatch, {1: PAGE_TWO_READ})  # page 2's call raises
    rendered = render_pages(two_page_pdf())
    proposals, notes = await _extract(rendered.pages)
    assert len(calls) == 2
    assert [p.page for p in proposals] == [1, 1]
    assert notes == ["page 2: read unavailable (RuntimeError)"]

    calls = _script(monkeypatch, {1: PAGE_ONE_READ})
    proposals, notes = await _extract(rendered.pages, max_calls=1)
    assert len(calls) == 1
    assert any("budget" in note for note in notes)


# --------------------------------------------------------- candidate part


def _proposals(*reads: str) -> list[DocumentProposal]:
    return [p for page, read in enumerate(reads, start=1) for p in parse_proposals(read, page=page)]


def test_candidate_definition_is_built_only_from_proposals_and_validates() -> None:
    definition, notes = candidate_definition(
        _proposals(PAGE_ONE_READ, PAGE_TWO_READ), source_url="https://vendor.example/ds.pdf"
    )
    assert definition is not None
    part = PartDefinition.model_validate(definition)
    assert (part.id, part.name, part.manufacturer, part.category) == (
        "xy-1234",
        "XY-1234",
        "Acme",
        "sensors",
    )
    assert part.specs == {"supply_voltage": "1.71 to 3.6 V", "i2c_clock": "400 kHz"}
    assert part.register_map["WHO_AM_I"].address == 0x75
    assert part.register_map["WHO_AM_I"].size == 1
    assert part.datasheet_url == "https://vendor.example/ds.pdf"
    assert part.notes is not None and "pages 1, 2" in part.notes
    assert notes == []


def test_candidate_definition_is_null_with_a_reason_when_the_pages_do_not_say_enough() -> None:
    definition, notes = candidate_definition(_proposals(PAGE_TWO_READ), source_url=None)
    assert definition is None
    assert notes and "name" in notes[0]

    no_category = [p for p in _proposals(PAGE_ONE_READ) if p.name != "category"]
    definition, notes = candidate_definition(no_category, source_url=None)
    assert definition is None
    assert notes and "category" in notes[0]


def test_registers_without_a_stated_width_are_left_out_not_invented() -> None:
    read = '{"kind":"register","name":"CTRL","value":"0x10","unit":null,"quote":"10 CTRL"}'
    definition, notes = candidate_definition(_proposals(PAGE_ONE_READ, read), source_url=None)
    assert definition is not None and definition["register_map"] == {}
    assert any("width" in note for note in notes)


# ----------------------------------------------------------------- the tools


def test_descriptor_gating_flags() -> None:
    assert READ_DOCUMENT_DESCRIPTOR.requires_confirmation is False
    assert READ_DOCUMENT_DESCRIPTOR.result_cap == 16_000
    assert READ_DOCUMENT_DESCRIPTOR.params["additionalProperties"] is False
    assert PROPOSE_PART_DEFINITION_DESCRIPTOR.requires_confirmation is True
    assert PROPOSE_PART_DEFINITION_DESCRIPTOR.consent_summary is not None
    assert ".solus" in PROPOSE_PART_DEFINITION_DESCRIPTOR.consent_summary
    for descriptor in (READ_DOCUMENT_DESCRIPTOR, PROPOSE_PART_DEFINITION_DESCRIPTOR):
        assert descriptor.description_trusted is True


async def _wire(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    engine: AsyncEngine,
    tmp_path: Path,
) -> tuple[ToolRegistry, uuid.UUID, uuid.UUID, LocalArtifactStore]:
    await me(client, headers)
    team = await create_team(client, headers)
    project = await create_project(client, headers, team["id"])
    user = await me(client, headers)
    project_id, user_id = uuid.UUID(project["id"]), uuid.UUID(user["id"])
    store = LocalArtifactStore(str(tmp_path))
    registry = ToolRegistry()
    register_document_tools(
        registry,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        store=store,
        project_id=project_id,
        user_id=user_id,
        secret_store=InMemorySecretStore(),
        redis=None,
        enqueue=None,
    )
    return registry, project_id, user_id, store


async def _stored_pdf(
    db: AsyncSession, store: LocalArtifactStore, project_id: uuid.UUID, user_id: uuid.UUID
) -> uuid.UUID:
    artifact = await create_artifact(
        db,
        store,
        project_id=project_id,
        created_by=user_id,
        data=two_page_pdf(title="XY-1234"),
        media_type="application/pdf",
        source_tool="test",
        tool_call_id=None,
    )
    await db.commit()
    return artifact.id


async def test_read_document_reads_a_stored_artifact_into_cited_proposals(
    client: httpx.AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, project_id, user_id, store = await _wire(client, alice_headers, engine, tmp_path)
    artifact_id = await _stored_pdf(db, store, project_id, user_id)
    _script(monkeypatch, {1: PAGE_ONE_READ, 2: PAGE_TWO_READ})

    result = await registry.invoke(
        ToolCall(
            call_id="c1",
            tool="read_document",
            args={"source": {"artifact_id": str(artifact_id)}, "question": "I2C address?"},
        )
    )
    assert result.ok, result.error
    value = result.value or {}
    assert value["artifact_id"] == str(artifact_id)
    assert value["title"] == "XY-1234"
    assert value["pages_read"] == [1, 2]
    assert value["truncated"] is False
    assert {p["page"] for p in value["proposals"]} == {1, 2}
    assert all("quote" in p for p in value["proposals"])
    definition = value["candidate_part_definition"]
    assert definition is not None
    PartDefinition.model_validate(definition)
    assert definition["datasheet_url"] is None  # an artifact has no https source


async def test_read_document_fetches_a_url_and_stores_it_as_a_pdf_artifact(
    client: httpx.AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, project_id, _user_id, _store = await _wire(client, alice_headers, engine, tmp_path)
    fetched: list[str] = []

    async def fake_fetch(url: str, **kw: Any) -> bytes:
        fetched.append(url)
        return two_page_pdf()

    monkeypatch.setattr(tool_module, "fetch_pdf", fake_fetch)
    _script(monkeypatch, {1: PAGE_ONE_READ, 2: PAGE_TWO_READ})

    result = await registry.invoke(
        ToolCall(
            call_id="c2",
            tool="read_document",
            args={"source": {"url": "https://vendor.example/ds.pdf"}, "pages": [1]},
        )
    )
    assert result.ok, result.error
    value = result.value or {}
    assert fetched == ["https://vendor.example/ds.pdf"]
    assert value["pages_read"] == [1]
    assert value["truncated"] is True  # page 2 exists and was not read
    row = await db.get(Artifact, uuid.UUID(value["artifact_id"]))
    assert row is not None
    assert (row.project_id, row.media_type, row.source_tool) == (
        project_id,
        "application/pdf",
        "read_document",
    )
    assert value["candidate_part_definition"]["datasheet_url"] == "https://vendor.example/ds.pdf"


async def test_hostile_page_text_ends_up_only_inside_a_proposal_quote(
    client: httpx.AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, project_id, user_id, store = await _wire(client, alice_headers, engine, tmp_path)
    artifact_id = await _stored_pdf(db, store, project_id, user_id)
    _script(monkeypatch, {1: HOSTILE_READ, 2: HOSTILE_READ})

    result = await registry.invoke(
        ToolCall(
            call_id="c3", tool="read_document", args={"source": {"artifact_id": str(artifact_id)}}
        )
    )
    assert result.ok, result.error
    value = result.value or {}
    assert value["candidate_part_definition"] is None
    for proposal in value["proposals"]:
        assert proposal["quote"] == HOSTILE_TEXT
    assert not any(HOSTILE_TEXT in note for note in value["notes"])


async def test_read_document_bad_input_and_foreign_artifacts_never_raise(
    client: httpx.AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
) -> None:
    registry, _project_id, _user_id, store = await _wire(client, alice_headers, engine, tmp_path)
    # Bob's own project holds the PDF; Alice's registry must not see it.
    _bob_registry, bob_project, bob_user, _ = await _wire(
        client, bob_headers, engine, tmp_path / "b"
    )
    foreign = await _stored_pdf(db, store, bob_project, bob_user)

    missing = await registry.invoke(
        ToolCall(call_id="c4", tool="read_document", args={"source": {"artifact_id": str(foreign)}})
    )
    assert missing.ok is False and missing.error is not None
    assert missing.error.code.value == "not_found"

    both = await registry.invoke(
        ToolCall(
            call_id="c5",
            tool="read_document",
            args={"source": {"url": "https://a.example/x.pdf", "artifact_id": str(foreign)}},
        )
    )
    assert both.ok is False and both.error is not None
    assert both.error.code.value == "invalid_args"

    plain_http = await registry.invoke(
        ToolCall(
            call_id="c6", tool="read_document", args={"source": {"url": "http://a.example/x.pdf"}}
        )
    )
    assert plain_http.ok is False and plain_http.error is not None
    assert plain_http.error.code.value == "invalid_args"


async def test_propose_part_definition_previews_and_files_a_cited_hardware_entry(
    client: httpx.AsyncClient,
    alice_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
) -> None:
    registry, project_id, user_id, store = await _wire(client, alice_headers, engine, tmp_path)
    artifact_id = await _stored_pdf(db, store, project_id, user_id)
    definition, _ = candidate_definition(_proposals(PAGE_ONE_READ, PAGE_TWO_READ), source_url=None)
    assert definition is not None
    args = {"definition": definition, "source_artifact_id": str(artifact_id), "pages": [1, 2]}

    [tool] = [t for t in registry.tools() if t.descriptor.name == "propose_part_definition"]
    # The gate duck-types `preview`; it is not on the Tool protocol.
    rows = await tool.preview(args)  # type: ignore[attr-defined]
    labels = {row["label"]: row for row in rows}
    assert labels["supply_voltage"] == {
        "label": "supply_voltage",
        "before": "(none)",
        "after": "1.71 to 3.6 V",
    }
    assert labels["name"]["after"] == "XY-1234"
    assert all(row["before"] == "(none)" for row in rows)

    result = await registry.invoke(
        ToolCall(call_id="c7", tool="propose_part_definition", args=args)
    )
    assert result.ok, result.error
    entry = await db.scalar(
        select(SolusEntry).where(SolusEntry.id == uuid.UUID((result.value or {})["id"]))
    )
    assert entry is not None
    assert entry.section is SolusSection.HARDWARE
    assert entry.author == "sol"
    assert entry.text is not None
    assert str(artifact_id) in entry.text
    assert "pages 1, 2" in entry.text
    assert "supply_voltage: 1.71 to 3.6 V" in entry.text
    assert "WHO_AM_I" in entry.text


async def test_propose_part_definition_refuses_invalid_definitions_and_foreign_sources(
    client: httpx.AsyncClient,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
    engine: AsyncEngine,
    db: AsyncSession,
    tmp_path: Path,
) -> None:
    registry, _project_id, _user_id, store = await _wire(client, alice_headers, engine, tmp_path)
    _bob_registry, bob_project, bob_user, _ = await _wire(
        client, bob_headers, engine, tmp_path / "b"
    )
    foreign = await _stored_pdf(db, store, bob_project, bob_user)
    definition, _ = candidate_definition(_proposals(PAGE_ONE_READ, PAGE_TWO_READ), source_url=None)
    assert definition is not None

    invalid = await registry.invoke(
        ToolCall(
            call_id="c8",
            tool="propose_part_definition",
            args={
                "definition": {**definition, "category": "spaceships"},
                "source_artifact_id": str(foreign),
                "pages": [1],
            },
        )
    )
    assert invalid.ok is False and invalid.error is not None
    assert invalid.error.code.value == "invalid_args"

    stolen = await registry.invoke(
        ToolCall(
            call_id="c9",
            tool="propose_part_definition",
            args={"definition": definition, "source_artifact_id": str(foreign), "pages": [1]},
        )
    )
    assert stolen.ok is False and stolen.error is not None
    assert stolen.error.code.value == "not_found"
    assert await db.scalar(select(SolusEntry)) is None


def test_the_documents_package_names_no_model_and_no_vendor() -> None:
    """Prompt text is Solus-authored; model choice is config (routing), never code."""
    for module in (extract, fetch, pdf, tool_module):
        source = Path(module.__file__ or "").read_text().lower()
        for banned in ("claude", "gpt", "gemini", "sonnet", "haiku", "opus"):
            assert banned not in source, f"{module.__name__} names {banned}"


def test_the_page_budget_fits_a_full_page_of_transcription() -> None:
    """`EXTRACT_MAX_TOKENS` must cover a page that fills `MAX_PROPOSALS_PER_PAGE`.

    At 900 it did not, and the failure was invisible: a reasoning-capable vision
    model spent most of the budget before emitting, the single line it produced
    was cut mid-string, and `parse_proposals` — correctly — dropped it. A dense
    ratings page came back with ONE proposal, "manufacturer", and no error
    anywhere (SOLUSDEV-252, found live on a TI regulator datasheet).
    """
    import json

    from solus_api.agent.documents import extract

    line = json.dumps(
        {
            "kind": "rating",
            "name": "Input voltage (V_O = 5 V to 18 V)",
            "value": "35",
            "unit": "V",
            "quote": "Input voltage (V O = 5 V to 18 V) . . . 35 V",
        }
    )
    # ~4 chars per token is the usual English/JSON ratio; the budget must also
    # leave room for the model's own reasoning tokens, hence the doubling.
    needed = (len(line) + 1) * extract.MAX_PROPOSALS_PER_PAGE // 4
    assert extract.EXTRACT_MAX_TOKENS >= needed * 2, (
        f"{extract.EXTRACT_MAX_TOKENS} tokens cannot hold "
        f"{extract.MAX_PROPOSALS_PER_PAGE} proposals (~{needed} tokens of JSON)"
    )


def test_a_reply_cut_off_mid_line_keeps_the_lines_before_it() -> None:
    """Truncation costs the last row, never the page."""
    from solus_api.agent.documents.extract import parse_proposals

    text = (
        '{"kind": "rating", "name": "Input voltage", "value": "35", "unit": "V", "quote": "35 V"}\n'
        '{"kind": "pinout", "name": "OUTPUT", "value": "3", "unit": null, "quote": "OUTPUT 3"}\n'
        '{"kind": "rating", "name": "Storage temp", "value": "-65", "unit": "\u00b0C", "quo'
    )
    parsed = parse_proposals(text, page=5)
    assert [p.name for p in parsed] == ["Input voltage", "OUTPUT"]
