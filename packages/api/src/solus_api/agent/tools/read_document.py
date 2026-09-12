"""`read_document` and `propose_part_definition` (SOLUSDEV-252 P6).

`read_document` is a READ: it fetches a PDF (an https URL, or an artifact already
in this project), stores a URL fetch as a TTL artifact, renders up to twelve pages
and turns each into page-cited PROPOSALS through one metered vision call
(`agent/documents/`). From those proposals — and nothing else — it assembles a
CANDIDATE `PartDefinition`; when the pages did not say enough to validate one,
the candidate is null and `notes` says why. Empty beats invented.

`propose_part_definition` is the gated hand-off: it files that candidate into the
project's `.solus` Hardware section as a cited text block, after the person
approves the exact rows. The curated library (`hardware/library.py`, R4) is
file-based and human-reviewed, so the `.solus` entry IS the candidate — a human
promotes it to a definition file, or does not.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

import yaml
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.agent.documents.extract import (
    MAX_QUESTION_CHARS,
    PROPOSAL_KINDS,
    QUOTE_CAP,
    DocumentProposal,
    extract_pages,
)
from solus_api.agent.documents.fetch import fetch_pdf
from solus_api.agent.documents.pdf import (
    MAX_PAGES_PER_CALL,
    MAX_PDF_BYTES,
    DocumentError,
    Rendered,
    render_pages,
)
from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import InProcessTool, Tool, ToolException
from solus_api.core.errors import APIError
from solus_api.hardware.library import MAX_SPECS, PartDefinition
from solus_api.models import SolusSection
from solus_api.services.artifacts import (
    create_artifact,
    fetch_artifact_bytes,
    get_artifact_metadata,
)
from solus_api.services.solus_config import MAX_TEXT_CHARS, add_text_entry

if TYPE_CHECKING:
    from solus_api.connectors.secrets import SecretStore
    from solus_api.storage import ArtifactStore

SOURCE_TOOL: Final = "read_document"
#: 12 vision calls, each bounded by the gateway's own timeout — well above the 30 s default.
READ_TIMEOUT_SECONDS: Final = 300.0
DEFAULT_ARTIFACT_TTL_SECONDS: Final = 3600
_PAGES_SCHEMA: Final[dict[str, Any]] = {
    "type": ["array", "null"],
    "items": {"type": "integer", "minimum": 1},
    "maxItems": MAX_PAGES_PER_CALL,
}
_PROPOSAL_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(PROPOSAL_KINDS)},
        "name": {"type": "string"},
        "value": {"type": "string"},
        "unit": {"type": ["string", "null"]},
        "page": {"type": "integer"},
        "quote": {"type": "string", "maxLength": QUOTE_CAP},
    },
    "required": ["kind", "name", "value", "unit", "page", "quote"],
}

READ_DOCUMENT_DESCRIPTOR = ToolDescriptor(
    name="read_document",
    description=(
        "Read a PDF datasheet, drawing or wiring diagram page by page and report what each "
        "page says as cited proposals (pinouts, ratings, timing, registers, dimensions), "
        "plus a candidate part definition when the pages state enough for one. Source: an "
        "https URL, or the artifact_id of a PDF already in this project. At most 12 pages "
        "per call; pass `pages` (1-based) to pick them. Everything returned is what the "
        "document appears to say — cite the page when you use it, and say so when a value "
        "is not on the pages read."
    ),
    params={
        "type": "object",
        "properties": {
            "source": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "maxLength": 2048},
                    "artifact_id": {"type": "string", "format": "uuid"},
                },
                "additionalProperties": False,
            },
            "pages": _PAGES_SCHEMA,
            "question": {"type": ["string", "null"], "maxLength": MAX_QUESTION_CHARS},
        },
        "required": ["source"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "format": "uuid"},
            "title": {"type": ["string", "null"]},
            "pages_read": {"type": "array", "items": {"type": "integer"}},
            "proposals": {"type": "array", "items": _PROPOSAL_SCHEMA},
            "candidate_part_definition": {"type": ["object", "null"]},
            "notes": {"type": "array", "items": {"type": "string"}},
            "truncated": {"type": "boolean"},
        },
        "required": [
            "artifact_id",
            "title",
            "pages_read",
            "proposals",
            "candidate_part_definition",
            "notes",
            "truncated",
        ],
        "additionalProperties": False,
    },
    timeout_seconds=READ_TIMEOUT_SECONDS,
    result_cap=16_000,
)

PROPOSE_PART_DEFINITION_DESCRIPTOR = ToolDescriptor(
    name="propose_part_definition",
    description=(
        "File a candidate part definition (as returned by read_document) into this "
        "project's .solus Hardware section, with the datasheet artifact and pages it came "
        "from. The person approves the exact fields first. It becomes a team-visible "
        "candidate for the curated parts library, not a library entry."
    ),
    params={
        "type": "object",
        "properties": {
            "definition": {"type": "object"},
            "source_artifact_id": {"type": "string", "format": "uuid"},
            "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}, "maxItems": 64},
        },
        "required": ["definition", "source_artifact_id", "pages"],
        "additionalProperties": False,
    },
    returns={
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "section": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["id", "section", "text"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
    consent_summary=(
        "Add this part definition (from the datasheet) to the project's .solus Hardware section"
    ),
)

# ------------------------------------------------------------ candidate part

_SPEC_KINDS: Final = frozenset({"rating", "timing", "dimension"})
_ADDRESS_RE: Final = re.compile(r"^\s*(?:0x([0-9a-f]+)|([0-9a-f]+)h|(\d+))\s*$", re.IGNORECASE)
_BITS_RE: Final = re.compile(r"(\d+)\s*-?\s*bit", re.IGNORECASE)
_BYTES_RE: Final = re.compile(r"(\d+)\s*byte", re.IGNORECASE)


def _slug(text: str, *, separator: str, allowed: str) -> str:
    slug = re.sub(rf"[^{allowed}]+", separator, text.lower()).strip(separator)
    return slug[:64].rstrip(separator)


def _quoted(proposals: Sequence[DocumentProposal], name: str) -> str | None:
    """The first `other` proposal named `name` (part / manufacturer / category)."""
    for proposal in proposals:
        if proposal.kind == "other" and proposal.name.lower() == name:
            return proposal.value
    return None


def _register(proposal: DocumentProposal) -> dict[str, int] | None:
    """{address, size} only when the page stated BOTH; a width is never assumed."""
    address = _ADDRESS_RE.match(proposal.value)
    if address is None:
        return None
    hex_digits = address.group(1) or address.group(2)
    value = int(hex_digits, 16) if hex_digits else int(address.group(3))
    unit = proposal.unit or ""
    bits, count = _BITS_RE.search(unit), _BYTES_RE.search(unit)
    if bits and int(bits.group(1)) % 8 == 0:
        return {"address": value, "size": int(bits.group(1)) // 8}
    if count:
        return {"address": value, "size": int(count.group(1))}
    return None


def _specs(proposals: Sequence[DocumentProposal], notes: list[str]) -> dict[str, str]:
    specs: dict[str, str] = {}
    for proposal in proposals:
        key = _slug(proposal.name, separator="_", allowed="a-z0-9")
        if proposal.kind not in _SPEC_KINDS or not key or key in specs:
            continue
        if len(specs) == MAX_SPECS:
            notes.append(f"more than {MAX_SPECS} ratings were read; the rest stay proposals only")
            break
        specs[key] = f"{proposal.value} {proposal.unit}" if proposal.unit else proposal.value
    return specs


def _registers(
    proposals: Sequence[DocumentProposal], notes: list[str]
) -> dict[str, dict[str, int]]:
    registers: dict[str, dict[str, int]] = {}
    skipped = 0
    for proposal in (p for p in proposals if p.kind == "register"):
        spec = _register(proposal)
        if spec is None or proposal.name in registers:
            skipped += spec is None
            continue
        registers[proposal.name] = spec
    if skipped:
        notes.append(
            f"{skipped} register(s) lacked a stated address or width and were left out "
            "(proposals only; a width is never assumed)"
        )
    return registers


def candidate_definition(
    proposals: Sequence[DocumentProposal], *, source_url: str | None
) -> tuple[dict[str, Any] | None, list[str]]:
    """A `PartDefinition`-shaped dict built ONLY from proposals, or None with the
    reason. Name, manufacturer and category must be quoted on a page; specs come
    from ratings with their units; registers only with a stated address AND width."""
    notes: list[str] = []
    name = _quoted(proposals, "part")
    if name is None:
        return None, ["no candidate: no part name or number was quoted on the pages read"]
    category = _quoted(proposals, "category")
    if category is None:
        return None, ["no candidate: the pages read did not make the part's category evident"]
    pages = sorted({p.page for p in proposals})
    candidate: dict[str, Any] = {
        "id": _slug(name, separator="-", allowed="a-z0-9.-"),
        "name": name,
        "manufacturer": _quoted(proposals, "manufacturer"),
        "category": category,
        "specs": _specs(proposals, notes),
        "register_map": _registers(proposals, notes),
        "datasheet_url": source_url if source_url and source_url.startswith("https://") else None,
        "notes": (
            f"Candidate from datasheet pages {', '.join(map(str, pages))} (read_document); "
            "not in the curated library — human review required."
        ),
    }
    try:
        PartDefinition.model_validate(candidate)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(loc) for loc in first["loc"]) or "definition"
        return None, [f"no candidate: {where} — {first['msg']}", *notes]
    return candidate, notes


# ------------------------------------------------------------------ handlers


def _invalid(message: str) -> ToolException:
    return ToolException(message, code=ToolErrorCode.INVALID_ARGS)


def _parse_uuid(raw: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise _invalid("artifact_id must be a UUID") from None


class _DocumentTools:
    """Both tools bound to ONE project and the requesting user by Solus code."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        store: ArtifactStore,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        secret_store: SecretStore,
        redis: Any,
        enqueue: Any,
        artifact_ttl_seconds: int,
    ) -> None:
        self._sessions = session_factory
        self._store = store
        self._project_id = project_id
        self._user_id = user_id
        self._secret_store = secret_store
        self._redis = redis
        self._enqueue = enqueue
        self._ttl = artifact_ttl_seconds

    async def _load(
        self, session: AsyncSession, source: Mapping[str, Any]
    ) -> tuple[uuid.UUID, bytes, str | None]:
        url, artifact_id = source.get("url"), source.get("artifact_id")
        if (url is None) == (artifact_id is None):
            raise _invalid("source must carry exactly one of url or artifact_id")
        if url is not None:
            try:
                data = await fetch_pdf(str(url))
            except DocumentError as exc:
                raise _invalid(f"could not fetch the document: {exc}") from None
            artifact = await create_artifact(
                session,
                self._store,
                project_id=self._project_id,
                created_by=self._user_id,
                data=data,
                media_type="application/pdf",
                source_tool=SOURCE_TOOL,
                tool_call_id=None,
            )
            await session.commit()
            return artifact.id, data, str(url)
        try:
            artifact, data = await fetch_artifact_bytes(
                session,
                self._store,
                project_id=self._project_id,
                artifact_id=_parse_uuid(artifact_id),
                requester_id=self._user_id,
                ttl_seconds=self._ttl,
                max_bytes=MAX_PDF_BYTES,
            )
        except APIError as exc:
            code = ToolErrorCode.NOT_FOUND if exc.status_code == 404 else ToolErrorCode.TOOL_ERROR
            raise ToolException(exc.message, code=code) from None
        return artifact.id, data, None

    async def read_document(self, args: dict[str, Any]) -> dict[str, Any]:
        pages: Sequence[int] | None = args.get("pages")
        question: str | None = args.get("question")
        async with self._sessions() as session:
            artifact_id, data, url = await self._load(session, args["source"])
            try:
                rendered: Rendered = await asyncio.to_thread(render_pages, data, pages=pages)
            except DocumentError as exc:
                raise _invalid(f"could not read the document: {exc}") from None
            proposals, notes = await extract_pages(
                rendered.pages,
                question=question,
                secret_store=self._secret_store,
                user_id=self._user_id,
                session=session,
                redis=self._redis,
                enqueue=self._enqueue,
            )
        candidate, candidate_notes = candidate_definition(proposals, source_url=url)
        return {
            "artifact_id": str(artifact_id),
            "title": rendered.title,
            "pages_read": [page.index for page in rendered.pages],
            "proposals": [proposal.model_dump() for proposal in proposals],
            "candidate_part_definition": candidate,
            "notes": [*notes, *candidate_notes],
            "truncated": rendered.page_count > len(rendered.pages),
        }

    async def preview_definition(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        """One row per field the entry will carry; nothing exists before, so `before`
        is always "(none)" — the rows the person approves ARE the filed values."""
        definition = args.get("definition")
        if not isinstance(definition, Mapping):
            return []
        rows = [
            {"label": key, "before": "(none)", "after": str(definition[key])}
            for key in ("name", "manufacturer", "category")
            if definition.get(key) is not None
        ]
        specs = definition.get("specs")
        if isinstance(specs, Mapping):
            rows += [
                {"label": str(k), "before": "(none)", "after": str(v)} for k, v in specs.items()
            ]
        registers = definition.get("register_map")
        if isinstance(registers, Mapping):
            rows += [
                {"label": f"register {name}", "before": "(none)", "after": _register_text(spec)}
                for name, spec in registers.items()
            ]
        return rows

    async def propose_definition(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            definition = PartDefinition.model_validate(args["definition"])
        except ValidationError as exc:
            first = exc.errors()[0]
            raise _invalid(f"definition does not validate: {first['loc']} {first['msg']}") from None
        source_id = _parse_uuid(args["source_artifact_id"])
        pages = sorted({int(p) for p in args["pages"]})
        async with self._sessions() as session:
            try:
                await get_artifact_metadata(
                    session,
                    project_id=self._project_id,
                    artifact_id=source_id,
                    requester_id=self._user_id,
                    requester_has_project_access=True,
                    ttl_seconds=self._ttl,
                )
            except APIError:
                raise ToolException(
                    "source artifact not found in this project", code=ToolErrorCode.NOT_FOUND
                ) from None
            text = _entry_text(definition, source_id, pages)
            if len(text) > MAX_TEXT_CHARS:
                raise _invalid(f"definition renders to more than {MAX_TEXT_CHARS} characters")
            try:
                entry = await add_text_entry(
                    session,
                    self._project_id,
                    SolusSection.HARDWARE,
                    text,
                    author="sol",
                    created_by=self._user_id,
                )
                await session.commit()
            except APIError as exc:
                raise _invalid(exc.message) from None
        return {"id": str(entry.id), "section": SolusSection.HARDWARE.value, "text": entry.text}


def _register_text(spec: object) -> str:
    if isinstance(spec, Mapping) and isinstance(spec.get("address"), int):
        return f"0x{spec['address']:02X} ({spec.get('size', '?')} byte)"
    return str(spec)


def _entry_text(definition: PartDefinition, source_id: uuid.UUID, pages: Sequence[int]) -> str:
    """The `.solus` Hardware entry: a YAML block a human can lift into a definition
    file, headed by its provenance. Register addresses are written in hex."""
    body = definition.model_dump(exclude_none=True)
    body["register_map"] = {
        name: {"address": f"0x{spec.address:02X}", "size": spec.size}
        for name, spec in definition.register_map.items()
    }
    cited = ", ".join(map(str, pages)) or "unspecified"
    header = (
        f"# Candidate part definition — from datasheet artifact {source_id}, pages {cited}\n"
        "# Filed by SOL via read_document; not in the curated library until a human "
        "reviews and promotes it.\n"
    )
    return header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True)


def register_document_tools(
    registry: Any,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    store: ArtifactStore,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    secret_store: SecretStore,
    redis: Any,
    enqueue: Any,
    artifact_ttl_seconds: int = DEFAULT_ARTIFACT_TTL_SECONDS,
) -> None:
    """Register both tools on `registry` (a `ToolRegistry`), bound to ONE project
    and the requesting user — the scope is fixed by Solus code before any model
    sees a document. `artifact_ttl_seconds` should be `Settings.artifact_ttl_seconds`."""
    tools = _DocumentTools(
        session_factory=session_factory,
        store=store,
        project_id=project_id,
        user_id=user_id,
        secret_store=secret_store,
        redis=redis,
        enqueue=enqueue,
        artifact_ttl_seconds=artifact_ttl_seconds,
    )
    read: Tool = InProcessTool(READ_DOCUMENT_DESCRIPTOR, tools.read_document)
    propose: Tool = InProcessTool(
        PROPOSE_PART_DEFINITION_DESCRIPTOR, tools.propose_definition, tools.preview_definition
    )
    registry.register(read)
    registry.register(propose)


__all__ = [
    "PROPOSE_PART_DEFINITION_DESCRIPTOR",
    "READ_DOCUMENT_DESCRIPTOR",
    "READ_TIMEOUT_SECONDS",
    "SOURCE_TOOL",
    "candidate_definition",
    "register_document_tools",
]
