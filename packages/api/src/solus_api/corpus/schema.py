"""Storage for the engineering corpus (ADR-036) — `corpus_chunk`, `corpus_citation`,
`corpus_release`.

THE SECOND GLOBAL CONTENT-BEARING TABLE after `tool_docs`, and the first whose
rows are long prose. Containment (ADR-033 as extended by ADR-036):

1. **No tenant column, no FK to projects/teams/users.** Nowhere to put one.
2. **Prose is bounded and everything else is an enum, a number, a date, or a
   typed array.** No JSONB, no free-form container. Citations are a typed child
   table, not a blob.
3. **The only write path is `corpus.ingest`** (tripwire-tested); the read path
   re-validates rows through the contract before serving them.
4. **Only `status = active` rows serve.** A draft is invisible to every tenant.

The primary key is the chunk's own stable id (`corpus:<domain>/<topic>/<slug>`)
so a citation in a past SOL answer resolves for the chunk's whole life,
including after withdrawal.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from solus_api.corpus.contract import MAX_BODY
from solus_api.corpus.enums import (
    Audience,
    ConfidenceBasis,
    CorpusDomain,
    Derivation,
    Drafting,
    Kind,
    License,
    SourceClass,
    SourceLicense,
    Status,
    Topic,
)
from solus_api.models import (
    EMBEDDING_DIM,
    Base,
    TimestampMixin,
    UuidPkMixin,
    _enum_column,
    _hnsw,
    utcnow,
)


class CitationRole(enum.StrEnum):
    FURTHER_READING = "further_reading"
    CHECKED_AGAINST = "checked_against"


class CorpusChunkRow(TimestampMixin, Base):
    """One chunk, flattened from the contract shape. Built ONLY by `corpus.ingest`."""

    __tablename__ = "corpus_chunk"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    domain: Mapped[CorpusDomain] = mapped_column(_enum_column(CorpusDomain))
    topic: Mapped[Topic] = mapped_column(_enum_column(Topic))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[Kind] = mapped_column(_enum_column(Kind))
    audience: Mapped[Audience] = mapped_column(_enum_column(Audience))
    #: "key=value" pairs; closed keys and values, re-validated on read.
    applicability: Mapped[list[str]] = mapped_column(ARRAY(String(48)), default=list)
    derivation: Mapped[Derivation] = mapped_column(_enum_column(Derivation))
    # -- provenance, flattened ------------------------------------------------
    source_class: Mapped[SourceClass] = mapped_column(_enum_column(SourceClass))
    source_title: Mapped[str] = mapped_column(String(200))
    source_publisher: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(400), default=None)
    source_locator: Mapped[str] = mapped_column(String(200), default="")
    source_license: Mapped[SourceLicense] = mapped_column(_enum_column(SourceLicense))
    accessed_at: Mapped[date] = mapped_column(Date)
    attribution: Mapped[str] = mapped_column(String(600), default="")
    # -- review and lifecycle --------------------------------------------------
    license: Mapped[License] = mapped_column(_enum_column(License))
    confidence: Mapped[float] = mapped_column(Float)
    confidence_basis: Mapped[ConfidenceBasis] = mapped_column(_enum_column(ConfidenceBasis))
    drafting: Mapped[Drafting] = mapped_column(_enum_column(Drafting))
    reviewer: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[date] = mapped_column(Date)
    status: Mapped[Status] = mapped_column(_enum_column(Status))
    supersedes: Mapped[str | None] = mapped_column(String(120), default=None)
    related: Mapped[list[str]] = mapped_column(ARRAY(String(120)), default=list)
    corpus_version: Mapped[str] = mapped_column(String(32))
    revised_in: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(72))
    # NOTE: pgvector reads back numpy.ndarray, not list (models.py:37).
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), default=None, nullable=True)

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_corpus_chunk_confidence"),
        CheckConstraint(f"char_length(body) <= {MAX_BODY}", name="ck_corpus_chunk_body_cap"),
        CheckConstraint("status <> 'withdrawn' OR body = ''", name="ck_corpus_chunk_withdrawn"),
        CheckConstraint("cardinality(applicability) <= 16", name="ck_corpus_chunk_applicability"),
        CheckConstraint("cardinality(related) <= 12", name="ck_corpus_chunk_related"),
        Index("ix_corpus_chunk_serve", "status", "domain", "topic"),
        _hnsw("ix_corpus_chunk_embedding", "embedding"),
    )


class CorpusCitationRow(UuidPkMixin, Base):
    """A `further_reading` or `checked_against` entry — typed, never a blob."""

    __tablename__ = "corpus_citation"

    chunk_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("corpus_chunk.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[CitationRole] = mapped_column(_enum_column(CitationRole))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(120), default="")
    identifier: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str | None] = mapped_column(String(400), default=None)

    __table_args__ = (
        UniqueConstraint("chunk_id", "role", "position", name="uq_corpus_citation_position"),
        CheckConstraint("position >= 0 AND position < 8", name="ck_corpus_citation_position"),
    )


class CorpusRelease(UuidPkMixin, Base):
    """One applied corpus version — the migration trail of the shipped artifact."""

    __tablename__ = "corpus_release"

    corpus_version: Mapped[str] = mapped_column(String(32), unique=True)
    policy_revision: Mapped[str] = mapped_column(String(200))
    released_at: Mapped[date] = mapped_column(Date)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    chunk_count: Mapped[int] = mapped_column(Integer)
    manifest_hash: Mapped[str] = mapped_column(String(72))


#: Referenced so linters keep the import the tripwire test greps for.
_ = (uuid, Uuid)
