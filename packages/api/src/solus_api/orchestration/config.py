"""Model-orchestration config contract (ADR-026/024).

The model catalog, the `(complexity × type) → role` matrix, and the cost/margin
knobs all live in data (`models.yaml`) and are validated here. There are ZERO
hardcoded model strings in Python code — model identity lives only in the catalog.

This module is FUNCTIONAL (it is the config contract MO-01 builds on): it loads,
validates, and cross-checks the config. Only the routing/cost *logic* is stubbed
elsewhere (`router.route`, `cost.track_cost`).
"""

import re
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from solus_api.orchestration.enums import Complexity, RouteType

_DEFAULT_CONFIG_PATH = Path(__file__).with_name("models.yaml")


class ModelCatalogEntry(BaseModel):
    """One concrete model and the role(s) it fills. Prices are USD per 1M tokens.

    Breakpoint (long-context) pricing: providers that charge more above an
    input-token threshold set all three `long_*` fields; flat-priced models
    omit them. `cost.compute_call_credits` bills `price_in_long`/`price_out_long`
    when tokens_in exceeds `long_context_threshold_tokens`."""

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    provider: str
    name: str
    price_in: float = Field(ge=0)
    price_out: float = Field(ge=0)
    context_window: int = Field(gt=0)
    roles: list[str] = Field(min_length=1)
    long_context_threshold_tokens: int | None = Field(default=None, gt=0)
    price_in_long: float | None = Field(default=None, ge=0)
    price_out_long: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _long_pricing_all_or_nothing(self) -> Self:
        """Half-configured breakpoint pricing would silently bill flat rates on
        exactly the calls most likely to cross the threshold."""
        long_fields = (self.long_context_threshold_tokens, self.price_in_long, self.price_out_long)
        configured = [field for field in long_fields if field is not None]
        if configured and len(configured) != len(long_fields):
            raise ValueError(
                f"catalog entry {self.name!r}: long_context_threshold_tokens, "
                "price_in_long, and price_out_long must be set together (or all omitted)"
            )
        if self.price_in_long is not None and self.price_out_long is not None:
            # A typo putting long rates BELOW flat would silently under-bill
            # exactly the calls the breakpoint exists to bill correctly.
            if self.price_in_long < self.price_in or self.price_out_long < self.price_out:
                raise ValueError(
                    f"catalog entry {self.name!r}: long-context prices "
                    f"({self.price_in_long}/{self.price_out_long}) must be >= "
                    f"the base prices ({self.price_in}/{self.price_out})"
                )
        return self


class EmbeddingConfig(BaseModel):
    """The single embedding model (SYS-02, `embeddings:` in models.yaml). Embeddings
    bill input tokens only, so there is no `price_out`. `dimensions` must match the
    pgvector column width (`models.EMBEDDING_DIM`) — validated at call time by
    `embeddings.embed`, not here, so the config contract stays free of a models.py
    import."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    name: str
    dimensions: int = Field(gt=0)
    price_in: float = Field(ge=0)  # USD per 1M input tokens


class CostConfig(BaseModel):
    """Token→credit conversion knobs (ADR-024), all CALIBRATABLE post-pilot.

    `margin_multiplier` defaults to 2.0 (covers infra + failed calls + trial
    grants + profit — not pure profit, which is why it is 2.0 not ~1.25). Values
    shipped in models.yaml are provisional (no real cost-per-op data yet)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    margin_multiplier: float = Field(default=2.0, gt=0)
    credits_per_dollar: float = Field(gt=0)
    price_unit: Literal["usd_per_million_tokens"] = "usd_per_million_tokens"


class EstimatorWeights(BaseModel):
    """How much each signal contributes to the estimator's score (MO-02)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    long_query: int = Field(default=2, ge=0)
    tool_signal: int = Field(default=1, ge=0)
    reasoning_signal: int = Field(default=2, ge=0)
    extra_domain: int = Field(default=2, ge=0)


class EstimatorConfig(BaseModel):
    """Knobs for the query-based complexity estimator (MO-02/02b, `complexity.py`).

    ALL tunable in `models.yaml` (`estimator:` section) without a code change —
    changing "what counts as HARD" is a config edit. Keyword entries are
    EXPLICIT REGEX PATTERNS (compiled here with IGNORECASE, validated at load):
    the pattern author writes the anchors and morphology — `\\bdrift(s|ing|ed)?\\b`
    hits "drifting" but not "adrift"; nothing is prepended or appended. Lists
    default EMPTY: the shipped models.yaml is the single source of the real
    patterns; numeric defaults are sane starting values (hand-built configs get
    length-only estimation) and may drift from the tuned yaml over time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trivial_max_words: int = Field(default=12, ge=0)
    hard_min_words: int = Field(default=35, gt=0)
    standard_threshold: int = Field(default=1, ge=0)
    hard_threshold: int = Field(default=4, ge=0)
    # Regex scans cover the first+last scan_max_chars only (signals cluster at
    # the edges; a 1MB paste must never pin the event loop). Length/size
    # signals always use the FULL text.
    scan_max_chars: int = Field(default=20_000, gt=0)
    weights: EstimatorWeights = Field(default_factory=EstimatorWeights)
    tool_keywords: list[str] = Field(default_factory=list)
    reasoning_keywords: list[str] = Field(default_factory=list)
    domain_keywords: dict[str, list[str]] = Field(default_factory=dict)

    # Compiled per family at load time: a bad regex fails config validation with
    # a clear error instead of surfacing on some later estimate call. A pattern
    # LIST (not one big alternation) keeps distinct-hit counting correct even
    # when individual patterns contain their own groups.
    _tool_patterns: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _reasoning_patterns: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _domain_patterns: dict[str, list[re.Pattern[str]]] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _thresholds_are_ordered(self) -> Self:
        """A tuning typo putting hard below standard would silently route
        ordinary queries to the expensive tier (HARD is checked first)."""
        if self.hard_threshold < self.standard_threshold:
            raise ValueError(
                f"estimator hard_threshold ({self.hard_threshold}) must be >= "
                f"standard_threshold ({self.standard_threshold})"
            )
        return self

    @model_validator(mode="after")
    def _compile_patterns(self) -> Self:
        self._tool_patterns = _compile_family("tool_keywords", self.tool_keywords)
        self._reasoning_patterns = _compile_family("reasoning_keywords", self.reasoning_keywords)
        self._domain_patterns = {
            domain: _compile_family(f"domain_keywords[{domain}]", patterns)
            for domain, patterns in self.domain_keywords.items()
        }
        return self

    @property
    def tool_patterns(self) -> list[re.Pattern[str]]:
        return self._tool_patterns

    @property
    def reasoning_patterns(self) -> list[re.Pattern[str]]:
        return self._reasoning_patterns

    @property
    def domain_patterns(self) -> dict[str, list[re.Pattern[str]]]:
        return self._domain_patterns


def _compile_family(family: str, patterns: list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        if not pattern:
            raise ValueError(f"estimator {family} contains an empty pattern")
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise ValueError(
                f"estimator {family} pattern {pattern!r} is not a valid regex: {exc}"
            ) from exc
    return compiled


class TypeEstimatorConfig(BaseModel):
    """Knobs for the MO-04 query-type estimator (`type_estimator.py`).

    Same contract as `EstimatorConfig`: entries are EXPLICIT REGEX PATTERNS
    compiled+validated at load (IGNORECASE, author-anchored); ALL knobs tunable
    in models.yaml without a code change. Pattern lists default EMPTY (shipped
    yaml is the source); numeric defaults are sane starting values.
    `chars_per_token` is a deliberate lazy heuristic (no tokenizer dependency);
    `long_context_min_tokens` is where measured input size forces LONG_CONTEXT."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chars_per_token: int = Field(default=4, gt=0)
    long_context_min_tokens: int = Field(default=100_000, gt=0)
    code_min_hits: int = Field(default=1, ge=1)
    visual_min_hits: int = Field(default=1, ge=1)
    # Regex scans cover the first+last scan_max_chars only (see EstimatorConfig).
    scan_max_chars: int = Field(default=20_000, gt=0)
    visual_attachment_kinds: list[str] = Field(default_factory=list)
    code_patterns: list[str] = Field(default_factory=list)
    visual_log_patterns: list[str] = Field(default_factory=list)

    _code_regexes: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _visual_regexes: list[re.Pattern[str]] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _compile_patterns(self) -> Self:
        self._code_regexes = _compile_family("code_patterns", self.code_patterns)
        self._visual_regexes = _compile_family("visual_log_patterns", self.visual_log_patterns)
        return self

    @property
    def code_regexes(self) -> list[re.Pattern[str]]:
        return self._code_regexes

    @property
    def visual_regexes(self) -> list[re.Pattern[str]]:
        return self._visual_regexes


class LimitsConfig(BaseModel):
    """MO-03 pre-flight and retry knobs — ALL tunable in models.yaml, no code change.

    `trial_credit_cap` is denominated in CREDITS (same unit the ledger debits) and is
    PROVISIONAL like the prices. The frequency cap is FLAT for every plan (abuse
    insurance, not a plan feature). Retry knobs govern OUR provider-side backoff
    (adapters deliberately pass max_retries=0 to the SDKs)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_credit_cap: int = Field(default=1000, ge=0)
    max_calls_per_minute: int = Field(default=20, gt=0)
    frequency_window_seconds: int = Field(default=60, gt=0)
    retry_max_attempts: int = Field(default=3, ge=1)  # total tries incl. the first
    retry_backoff_seconds: float = Field(default=0.5, ge=0)  # base; doubles per retry


class OrchestrationConfig(BaseModel):
    """The whole routing contract as data. The matrix may be partial — a missing
    `(complexity, type)` cell falls back to `default_role` in `route()`."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    catalog: list[ModelCatalogEntry] = Field(min_length=1)
    matrix: dict[Complexity, dict[RouteType, str]]
    default_role: str
    cost: CostConfig
    estimator: EstimatorConfig = Field(default_factory=EstimatorConfig)
    type_estimator: TypeEstimatorConfig = Field(default_factory=TypeEstimatorConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    embeddings: EmbeddingConfig | None = None  # SYS-02: absent → embed() unavailable

    _role_index: dict[str, ModelCatalogEntry] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _index_and_validate_roles(self) -> Self:
        """Build the role→entry index and enforce that routing is deterministic:
        each referenced role is filled by exactly one catalog entry."""
        index: dict[str, ModelCatalogEntry] = {}
        for entry in self.catalog:
            for role in entry.roles:
                if role in index:
                    raise ValueError(
                        f"role {role!r} is filled by more than one catalog entry "
                        "(routing must be deterministic)"
                    )
                index[role] = entry
        referenced = {role for row in self.matrix.values() for role in row.values()}
        referenced.add(self.default_role)
        missing = sorted(referenced - index.keys())
        if missing:
            raise ValueError(f"matrix/default_role reference roles absent from catalog: {missing}")
        self._role_index = index
        return self

    def entry_for_role(self, role: str) -> ModelCatalogEntry:
        """Resolve a role to its concrete catalog entry (validated to exist)."""
        return self._role_index[role]


def load_orchestration_config(path: Path | None = None) -> OrchestrationConfig:
    """Load and validate the model catalog; defaults to the sibling `models.yaml`."""
    source = path or _DEFAULT_CONFIG_PATH
    data = yaml.safe_load(source.read_text())
    return OrchestrationConfig.model_validate(data)
