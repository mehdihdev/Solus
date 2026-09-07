"""The corpus chunk contract — docs/schemas/corpus-chunk.md made mechanical (ADR-036).

A chunk is read by EVERY tenant, so its boundary is its shape: `extra="forbid"`
everywhere (§3 — no field exists to hold anything customer-owned), every
categorical field is a closed enum (§4), and the sixteen cross-field rules of
§5 encode the licensing policy so that a chunk the policy forbids does not
validate. Rule numbers in comments refer to that section.

What the shape cannot do (schema §1): tell whether prose was copied or describes
a customer's robot. That is the reviewer's job, which is why `reviewer` is
required and may never be a model.

Rejections carry field names and rule numbers only — never the offending text.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import date
from typing import Annotated, Any, Final
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from solus_api.corpus.enums import (
    APPLICABILITY_VALUES,
    ATTRIBUTION_REQUIRED,
    CLASS_DERIVATIONS,
    CLASS_LICENSES,
    SHIP_LICENSES,
    TOPIC_DOMAIN,
    ApplicabilityKey,
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
from solus_api.corpus.hosts import is_allowed_host

__all__ = [
    "SHIP_LICENSES",
    "Applicability",
    "Citation",
    "CorpusChunk",
    "Provenance",
    "compute_content_hash",
    "is_chunk_id",
]

MAX_BODY: Final = 6000
MAX_TITLE: Final = 120
MAX_ID: Final = 120
MAX_APPLICABILITY: Final = 16
MAX_FURTHER_READING: Final = 8
MAX_RELATED: Final = 12
MAX_CITATIONS: Final = 8

CHUNK_ID_RE: Final = re.compile(
    r"^corpus:(?P<domain>[a-z]+)/(?P<topic>[a-z0-9_]+)/(?P<slug>[a-z0-9][a-z0-9-]*)$"
)
SEMVER_RE: Final = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
#: Rule 8 — a Solus staff handle: lowercase slug, 3..64 chars.
REVIEWER_RE: Final = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
_UUID_RE: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_MODEL_TOKENS: Final = frozenset(
    {
        "claude",
        "gpt",
        "gemini",
        "llama",
        "mistral",
        "model",
        "llm",
        "assistant",
        "chatgpt",
        "anthropic",
        "openai",
        "ai",
        "sol",
        "bot",
    }
)
_HASH_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
#: Rule 13 — what a body may not contain.
_FENCE: Final = "<<<"
_HTML_RE: Final = re.compile(r"</?[A-Za-z!]")
_IMAGE_RE: Final = re.compile(r"!\[")
_URL_RE: Final = re.compile(r"https?://[^\s)\]>]+")
_SKIP_HASH_CHECK: Final = "corpus_skip_hash_check"


def _nfkc(value: Any) -> Any:
    """NFKC-normalise every string in a payload (schema §2), recursively."""
    if isinstance(value, str):
        return unicodedata.normalize("NFKC", value)
    if isinstance(value, dict):
        return {k: _nfkc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_nfkc(v) for v in value]
    return value


def _https_host(url: str, *, rule: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"rule {rule}: url must be https on a bare host with no userinfo")
    return parts.hostname.lower()


def _semver_key(value: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in value.split("."))
    return major, minor, patch


def is_chunk_id(value: str) -> bool:
    return len(value) <= MAX_ID and CHUNK_ID_RE.match(value) is not None


class _Closed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=False)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        return _nfkc(data) if isinstance(data, dict) else data


class Citation(_Closed):
    """A bibliographic pointer (§2.2). The only place an EXCLUDE-class work may be named."""

    title: str = Field(min_length=1, max_length=200)
    author: str = Field(max_length=120)
    identifier: str = Field(max_length=120)
    url: str | None = Field(max_length=400)

    @field_validator("url")
    @classmethod
    def _rights_holder_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        host = _https_host(value, rule="7")
        if not is_allowed_host(host):
            raise ValueError("rule 7: citation url host is not a rights-holder host")
        return value


class Applicability(_Closed):
    """One closed-key, closed-value tag (SCOPE.md §6)."""

    key: ApplicabilityKey
    value: str = Field(max_length=32)

    @model_validator(mode="after")
    def _value_belongs_to_key(self) -> Applicability:
        if self.value not in APPLICABILITY_VALUES[self.key]:
            raise ValueError("rule 12: applicability value is not in its key's enum")
        return self


class Provenance(_Closed):
    """Where a chunk came from and under what terms (§2.1)."""

    source_class: SourceClass
    source_title: str = Field(min_length=1, max_length=200)
    source_publisher: str = Field(min_length=1, max_length=120)
    source_url: str | None = Field(max_length=400)
    source_locator: str = Field(max_length=200)
    source_license: SourceLicense
    accessed_at: date
    attribution: str = Field(max_length=600)
    checked_against: list[Citation] = Field(max_length=MAX_CITATIONS)

    @model_validator(mode="after")
    def _url_matches_class(self) -> Provenance:
        if self.source_class is SourceClass.SOLUS_AUTHORED:
            if self.source_url is not None or self.source_locator != "":
                raise ValueError("rule 5: solus_authored has no source_url and no locator")
            return self
        if self.source_url is None:
            raise ValueError("rule 5: a sourced class requires a source_url")
        host = _https_host(self.source_url, rule="14")
        if not is_allowed_host(host, self.source_class):
            raise ValueError("rule 14: source_url host is not allowed for this source class")
        if self.accessed_at > date.today():
            raise ValueError("accessed_at is in the future")
        return self


def compute_content_hash(fields: Mapping[str, Any]) -> str:
    """Rule 15: sha256 over the canonical JSON of every field except
    `content_hash` and `embedding`. Input is the JSON-mode dump of a chunk."""
    payload = {k: v for k, v in fields.items() if k not in ("content_hash", "embedding")}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("ascii")).hexdigest()


class CorpusChunk(_Closed):
    """One chunk of the engineering corpus (§2). Construct with `create()` to
    have the content hash computed; `model_validate` verifies a stored one."""

    id: str = Field(max_length=MAX_ID)
    domain: CorpusDomain
    topic: Topic
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    body: str = Field(max_length=MAX_BODY)
    kind: Kind
    audience: Audience
    applicability: list[Applicability] = Field(max_length=MAX_APPLICABILITY)
    derivation: Derivation
    provenance: Provenance
    further_reading: list[Citation] = Field(max_length=MAX_FURTHER_READING)
    license: License
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    confidence_basis: ConfidenceBasis
    drafting: Drafting
    reviewer: str = Field(max_length=64)
    reviewed_at: date
    status: Status
    supersedes: str | None
    related: list[str] = Field(max_length=MAX_RELATED)
    corpus_version: str
    revised_in: str
    content_hash: str
    embedding: list[float] | None = None

    @classmethod
    def create(cls, **fields: Any) -> CorpusChunk:
        """Validate `fields` and stamp the content hash (rule 15)."""
        draft = cls.model_validate(
            {**fields, "content_hash": "sha256:" + "0" * 64},
            context={_SKIP_HASH_CHECK: True},
        )
        return draft.model_copy(
            update={"content_hash": compute_content_hash(draft.model_dump(mode="json"))}
        )

    # ------------------------------------------------------------ field rules
    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not CHUNK_ID_RE.match(value):
            raise ValueError("id must be corpus:<domain>/<topic>/<slug>")
        return value

    @field_validator("supersedes")
    @classmethod
    def _supersedes_shape(cls, value: str | None) -> str | None:
        if value is not None and not is_chunk_id(value):
            raise ValueError("supersedes must be a chunk id")
        return value

    @field_validator("related")
    @classmethod
    def _related_shape(cls, value: list[str]) -> list[str]:
        if any(not is_chunk_id(item) for item in value):
            raise ValueError("related entries must be chunk ids")
        if len(set(value)) != len(value):
            raise ValueError("related entries must be unique")
        return value

    @field_validator("corpus_version", "revised_in")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not SEMVER_RE.match(value):
            raise ValueError("version must be semver MAJOR.MINOR.PATCH")
        return value

    @field_validator("reviewer")
    @classmethod
    def _reviewer_is_staff(cls, value: str) -> str:
        if not REVIEWER_RE.match(value) or _UUID_RE.match(value):
            raise ValueError("rule 8: reviewer must be a Solus staff handle")
        if set(re.split(r"[-_]", value)) & _MODEL_TOKENS:
            raise ValueError("rule 8: reviewer may not be a model name")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def _not_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("rule 8: reviewed_at is in the future")
        return value

    @field_validator("content_hash")
    @classmethod
    def _hash_shape(cls, value: str) -> str:
        if not _HASH_RE.match(value):
            raise ValueError("rule 15: content_hash must be sha256:<64 hex>")
        return value

    # ------------------------------------------------------ cross-field rules
    @model_validator(mode="after")
    def _policy(self, info: ValidationInfo) -> CorpusChunk:
        self._check_identity()
        self._check_licensing()
        self._check_status()
        self._check_body()
        if not (info.context or {}).get(_SKIP_HASH_CHECK):
            expected = compute_content_hash(self.model_dump(mode="json"))
            if self.content_hash != expected:
                raise ValueError("rule 15: content_hash does not recompute")
        return self

    def _check_identity(self) -> None:
        match = CHUNK_ID_RE.match(self.id)
        assert match is not None  # field validator ran first
        if match["domain"] != self.domain.value or match["topic"] != self.topic.value:
            raise ValueError("rule 11: id disagrees with domain/topic")
        if TOPIC_DOMAIN[self.topic] is not self.domain:
            raise ValueError("rule 11: topic is not bound to this domain")
        keys = [entry.key for entry in self.applicability]
        if len(set(keys)) != len(keys):
            raise ValueError("rule 12: applicability keys must be unique")
        if _semver_key(self.revised_in) < _semver_key(self.corpus_version):
            raise ValueError("revised_in precedes corpus_version")

    def _check_licensing(self) -> None:
        prov = self.provenance
        # Rule 9 lets a DRAFT carry `unknown` while the reviewer resolves the licence;
        # every other status must satisfy the rule-1 table.
        unresolved_draft = (
            self.status is Status.DRAFT and prov.source_license is SourceLicense.UNKNOWN
        )
        if not unresolved_draft and prov.source_license not in CLASS_LICENSES[prov.source_class]:
            raise ValueError("rule 1: source_license is not allowed for this source_class")
        if self.derivation not in CLASS_DERIVATIONS[prov.source_class]:
            raise ValueError("rule 1: derivation is not allowed for this source_class")
        if self.derivation is Derivation.VERBATIM and prov.source_license not in SHIP_LICENSES:
            raise ValueError("rule 2: verbatim requires a SHIP licence")
        if (
            prov.source_class is SourceClass.STANDARDS_BODY
            and self.derivation is Derivation.FACTS_EXTRACTED
        ):
            raise ValueError("rule 3: standards admit no facts_extracted")
        if (self.derivation is Derivation.SOLUS_ORIGINAL) != (
            prov.source_class is SourceClass.SOLUS_AUTHORED
        ):
            raise ValueError("rule 4: solus_original iff solus_authored")
        if (
            prov.source_class is SourceClass.SOLUS_AUTHORED
            and self.drafting is Drafting.LLM_ASSISTED
            and self.status is not Status.WITHDRAWN  # rule 10 clears the checks
            and not prov.checked_against
        ):
            raise ValueError("rule 5: llm_assisted drafting must record checked_against")
        if (
            self.derivation is Derivation.VERBATIM
            and prov.source_license in ATTRIBUTION_REQUIRED
            and not prov.attribution.strip()
        ):
            raise ValueError("rule 6: verbatim excerpt under this licence needs attribution")

    def _check_status(self) -> None:
        if self.status is Status.ACTIVE:
            if self.provenance.source_license is SourceLicense.UNKNOWN:
                raise ValueError("rule 9: active chunks may not carry an unknown licence")
            if self.confidence <= 0:
                raise ValueError("rule 9: active chunks need confidence > 0")
        if self.status is Status.WITHDRAWN:
            if self.body or self.related or self.further_reading or self.applicability:
                raise ValueError("rule 10: withdrawn chunks keep no served text")
        elif not self.body.strip():
            raise ValueError("body may not be empty unless withdrawn")

    def _check_body(self) -> None:
        body = self.body
        if _FENCE in body:
            raise ValueError("rule 13: body may not contain the fence delimiter")
        if _HTML_RE.search(body):
            raise ValueError("rule 13: body may not contain raw HTML")
        if _IMAGE_RE.search(body):
            raise ValueError("rule 13: body may not contain image syntax")
        allowed = self.provenance.source_url
        for raw in _URL_RE.findall(body):
            if raw.rstrip(".,;:") != allowed:
                raise ValueError("rule 13: body links may target only the source_url")
