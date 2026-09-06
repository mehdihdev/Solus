"""Authored Markdown → corpus chunks (docs/corpus/AUTHORING.md).

One source file is TOML front matter between `+++` fences plus a Markdown body.
The path fixes identity — `content/<domain>/<topic>/<slug>.md` — so a file cannot
claim a domain or topic it does not sit in. Chunking splits the body at level-2
headings, treats fenced blocks (formulae, code) and tables as atomic, and packs
an oversize section block by block; a single block over the cap is an error,
never a torn table. Every chunk of a file shares the file's front matter.

Errors carry paths, rule numbers, and field names — never body text.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from solus_api.corpus.contract import MAX_BODY, MAX_TITLE, SEMVER_RE, CorpusChunk
from solus_api.corpus.enums import TOPIC_DOMAIN, CorpusDomain, Status, Topic

__all__ = [
    "ChunkingError",
    "CorpusReleaseInfo",
    "build_manifest",
    "chunks_from_source",
    "content_root",
    "load_content_tree",
    "load_release",
    "validate_corpus",
]

FRONT_MATTER_FENCE: Final = "+++"
RELEASE_FILE: Final = "corpus.toml"
MANIFEST_FILE: Final = "manifest.json"
MANIFEST_SCHEMA_VERSION: Final = 1
_SLUG_RE: Final = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_HEADING2_RE: Final = re.compile(r"^## (?!#)(.+)$")
#: Fields the path or the chunker owns; front matter may not set them.
_RESERVED: Final = frozenset({"id", "domain", "topic", "body", "content_hash", "embedding"})


class ChunkingError(Exception):
    """A source file that cannot become chunks. `where` is a path or id."""

    def __init__(self, where: str, message: str) -> None:
        super().__init__(f"{where}: {message}")
        self.where = where
        self.message = message


def content_root() -> Path:
    """The shipped content tree (packaged with the API, ADR-036)."""
    return Path(__file__).resolve().parent / "content"


# ------------------------------------------------------------------ front matter


def _split_front_matter(text: str, where: str) -> tuple[dict[str, Any], str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != FRONT_MATTER_FENCE:
        raise ChunkingError(where, "front matter: file must open with +++")
    close = next((i for i in range(1, len(lines)) if lines[i].strip() == FRONT_MATTER_FENCE), None)
    if close is None:
        raise ChunkingError(where, "front matter: closing +++ not found")
    try:
        meta = tomllib.loads("\n".join(lines[1:close]))
    except tomllib.TOMLDecodeError:
        # `from None`: the decoder's message can quote the offending line.
        raise ChunkingError(where, "front matter: invalid TOML") from None
    return meta, "\n".join(lines[close + 1 :]).strip("\n")


def _citation_defaults(entries: Any) -> Any:
    if not isinstance(entries, list):
        return entries
    return [
        {"author": "", "identifier": "", "url": None, **entry} if isinstance(entry, dict) else entry
        for entry in entries
    ]


def _with_defaults(meta: dict[str, Any], where: str) -> dict[str, Any]:
    reserved = _RESERVED & set(meta)
    if reserved:
        raise ChunkingError(where, f"front matter may not set {sorted(reserved)}")
    fields = {
        "license": "solus-proprietary",
        "supersedes": None,
        "related": [],
        "further_reading": [],
        "applicability": [],
        **meta,
    }
    fields["further_reading"] = _citation_defaults(fields["further_reading"])
    provenance = fields.get("provenance")
    if isinstance(provenance, dict):
        fields["provenance"] = {
            "source_url": None,
            "source_locator": "",
            "attribution": "",
            "checked_against": [],
            **provenance,
        }
        fields["provenance"]["checked_against"] = _citation_defaults(
            fields["provenance"]["checked_against"]
        )
    return fields


# ------------------------------------------------------------------------ blocks

BlockKind = Literal["heading2", "fence", "table", "text"]


@dataclass(frozen=True)
class _Block:
    kind: BlockKind
    text: str


def _is_fence(line: str) -> bool:
    return line.startswith("```")


def _is_table(line: str) -> bool:
    return line.lstrip().startswith("|")


def _blocks(body: str) -> list[_Block]:
    """Body → atomic blocks. A fence runs to its closing ``` (or the end); a
    table is the run of `|` lines; text is a paragraph; `## ` outside a fence
    is a level-2 heading and a split point."""
    lines = body.split("\n")
    out: list[_Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if _is_fence(line):
            j = i + 1
            while j < len(lines) and not _is_fence(lines[j]):
                j += 1
            end = min(j + 1, len(lines))
            out.append(_Block("fence", "\n".join(lines[i:end])))
            i = end
            continue
        heading = _HEADING2_RE.match(line)
        if heading:
            out.append(_Block("heading2", heading.group(1).strip()))
            i += 1
            continue
        if _is_table(line):
            j = i
            while j < len(lines) and _is_table(lines[j]):
                j += 1
            out.append(_Block("table", "\n".join(lines[i:j])))
            i = j
            continue
        j = i
        while (
            j < len(lines)
            and lines[j].strip()
            and not _is_fence(lines[j])
            and not _is_table(lines[j])
            and not _HEADING2_RE.match(lines[j])
        ):
            j += 1
        out.append(_Block("text", "\n".join(lines[i:j])))
        i = j
    return out


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


@dataclass(frozen=True)
class _Section:
    title: str
    suffix: str
    blocks: tuple[_Block, ...]


def _sections(blocks: Sequence[_Block], file_title: str, where: str) -> list[_Section]:
    sections: list[_Section] = []
    title, suffix, current = file_title, "", []
    for block in blocks:
        if block.kind != "heading2":
            current.append(block)
            continue
        if current or not sections and not current and suffix:
            sections.append(_Section(title, suffix, tuple(current)))
        elif suffix:
            raise ChunkingError(where, f"empty section '{suffix}'")
        title, suffix, current = block.text, _slugify(block.text), []
    if current:
        sections.append(_Section(title, suffix, tuple(current)))
    elif suffix:
        raise ChunkingError(where, f"empty section '{suffix}'")
    if not sections:
        raise ChunkingError(where, "body is empty")
    return sections


def _pack(section: _Section, where: str) -> list[str]:
    """Render a section as one body, or as several ≤ MAX_BODY bodies that never
    split a block (a table or a fence stays whole)."""
    whole = "\n\n".join(block.text for block in section.blocks)
    if len(whole) <= MAX_BODY:
        return [whole]
    parts: list[list[str]] = [[]]
    for block in section.blocks:
        if len(block.text) > MAX_BODY:
            raise ChunkingError(where, f"a single {block.kind} block exceeds {MAX_BODY} chars")
        candidate = "\n\n".join([*parts[-1], block.text])
        if parts[-1] and len(candidate) > MAX_BODY:
            parts.append([block.text])
        else:
            parts[-1].append(block.text)
    return ["\n\n".join(part) for part in parts]


def _validation_message(exc: ValidationError) -> str:
    # Field names and rule text only — never the offending input (§7).
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'chunk'}: {err['msg']}"
        for err in exc.errors(include_url=False, include_input=False)
    )


def chunks_from_source(
    text: str, *, domain: CorpusDomain, topic: Topic, slug: str, where: str | None = None
) -> list[CorpusChunk]:
    """Parse one authored file into its chunks. `slug` is the file stem."""
    where = where or f"{domain.value}/{topic.value}/{slug}.md"
    if not _SLUG_RE.match(slug):
        raise ChunkingError(where, "file name must be a lowercase slug")
    meta, body = _split_front_matter(text, where)
    file_title = meta.pop("title", None)
    if not isinstance(file_title, str) or not file_title.strip():
        raise ChunkingError(where, "front matter: title is required")
    fields = _with_defaults(meta, where)
    base = f"corpus:{domain.value}/{topic.value}/{slug}"

    chunks: list[CorpusChunk] = []
    for section in _sections(_blocks(body), file_title, where):
        if len(section.title) > MAX_TITLE:
            raise ChunkingError(where, f"section title exceeds {MAX_TITLE} chars")
        section_id = base if not section.suffix else f"{base}-{section.suffix}"
        for index, part in enumerate(_pack(section, where), start=1):
            chunk_id = section_id if index == 1 else f"{section_id}-{index}"
            try:
                chunks.append(
                    CorpusChunk.create(
                        id=chunk_id,
                        domain=domain,
                        topic=topic,
                        title=section.title,
                        body=part,
                        **fields,
                    )
                )
            except ValidationError as exc:
                raise ChunkingError(chunk_id, _validation_message(exc)) from None
    return chunks


# ------------------------------------------------------------------ the tree


class CorpusReleaseInfo(BaseModel):
    """`content/corpus.toml` — the version the whole tree is released as."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus_version: str
    policy_revision: str
    released_at: date

    @field_validator("corpus_version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not SEMVER_RE.match(value):
            raise ValueError("corpus_version must be semver")
        return value


def load_release(root: Path) -> CorpusReleaseInfo:
    path = root / RELEASE_FILE
    try:
        raw = tomllib.loads(path.read_text())
        return CorpusReleaseInfo.model_validate(raw)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ChunkingError(
            str(path), f"release file unreadable or invalid: {type(exc).__name__}"
        ) from None


def _enum_dir[E](kind: type[E], name: str, where: str, label: str) -> E:
    try:
        return kind(name)  # type: ignore[call-arg]
    except ValueError:
        raise ChunkingError(where, f"unknown {label} directory") from None


def load_content_tree(
    root: Path, *, only: Iterable[CorpusDomain] | None = None
) -> list[CorpusChunk]:
    """Every chunk under `root/<domain>/<topic>/*.md`, in path order. `only`
    restricts to some domains (an author validating their own tree)."""
    wanted = None if only is None else set(only)
    chunks: list[CorpusChunk] = []
    for domain_dir in sorted(
        p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))
    ):
        domain = _enum_dir(CorpusDomain, domain_dir.name, str(domain_dir), "domain")
        if wanted is not None and domain not in wanted:
            continue
        for topic_dir in sorted(p for p in domain_dir.iterdir() if p.is_dir()):
            topic = _enum_dir(Topic, topic_dir.name, str(topic_dir), "topic")
            if TOPIC_DOMAIN[topic] is not domain:
                raise ChunkingError(str(topic_dir), "topic is not bound to this domain")
            for path in sorted(topic_dir.glob("*.md")):
                chunks.extend(
                    chunks_from_source(
                        path.read_text(),
                        domain=domain,
                        topic=topic,
                        slug=path.stem,
                        where=str(path),
                    )
                )
    return chunks


def _semver_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def validate_corpus(chunks: Iterable[CorpusChunk], release: CorpusReleaseInfo) -> None:
    """Cross-chunk rules: unique ids, resolvable links, rule 10, version bounds."""
    by_id: dict[str, CorpusChunk] = {}
    for chunk in chunks:
        if chunk.id in by_id:
            raise ChunkingError(chunk.id, "duplicate chunk id")
        by_id[chunk.id] = chunk
    ceiling = _semver_key(release.corpus_version)
    superseders = {
        c.supersedes for c in by_id.values() if c.supersedes and c.status is Status.ACTIVE
    }
    for chunk in by_id.values():
        for ref in chunk.related:
            if ref not in by_id:
                raise ChunkingError(chunk.id, "related id does not exist in the corpus")
        if chunk.supersedes is not None and chunk.supersedes not in by_id:
            raise ChunkingError(chunk.id, "supersedes id does not exist in the corpus")
        if chunk.status is Status.SUPERSEDED and chunk.id not in superseders:
            raise ChunkingError(chunk.id, "rule 10: no active chunk supersedes this one")
        if _semver_key(chunk.corpus_version) > ceiling or _semver_key(chunk.revised_in) > ceiling:
            raise ChunkingError(chunk.id, "corpus_version/revised_in exceed the release version")


def build_manifest(chunks: Iterable[CorpusChunk], release: CorpusReleaseInfo) -> dict[str, Any]:
    """Schema §8: what the desktop, the API, and SOL agree on as 'the corpus'."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "corpus_version": release.corpus_version,
        "released_at": release.released_at.isoformat(),
        "policy_revision": release.policy_revision,
        "chunks": [
            {"id": c.id, "content_hash": c.content_hash, "status": c.status.value}
            for c in sorted(chunks, key=lambda c: c.id)
        ],
    }
