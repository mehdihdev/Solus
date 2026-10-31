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
from typing import Annotated, Final, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    model_validator,
)

from solus_api.orchestration.enums import Complexity, RouteType

_DEFAULT_CONFIG_PATH = Path(__file__).with_name("models.yaml")

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


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
    #: USD per 1M CACHED input tokens (prompt-cache hits). None = no discount.
    price_cached_in: float | None = Field(default=None, ge=0)
    #: Reasoning-effort knob passed to the provider for this entry; None for
    #: non-reasoning models or the provider default. The allow-list is the union
    #: of the providers' ladders (OpenAI: none…max) so a typo fails at config
    #: load, not on the first paid call; a model that rejects a listed value
    #: (the frontier reasoning tier rejects "none") still fails loudly as a
    #: ProviderError.
    reasoning_effort: ReasoningEffort | None = None
    #: SOLUSDEV-252 S3 (review M2): can this model take image blocks in a turn?
    #: A screenshot rides the live turn of GENERAL/CODE routes, so those cells
    #: must never resolve to a text-only model — enforced at config load.
    accepts_images: bool = True

    @model_validator(mode="after")
    def _cached_price_is_a_discount(self) -> Self:
        if self.price_cached_in is not None and self.price_cached_in > self.price_in:
            raise ValueError(
                f"catalog entry {self.name!r}: price_cached_in ({self.price_cached_in}) "
                f"must be <= price_in ({self.price_in})"
            )
        return self

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
    #: Credits debited for ONE web-search API call (SOLUSDEV-321 P1-T5): a search, or the
    #: page-reading call that follows it. Not token-priced, so a flat knob; zero still writes a
    #: ledger row per call. Defaulted so a hand-built config bills what the shipped yaml does.
    web_call_credits: int = Field(default=2, ge=0)


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


#: Each `LayerBudget` default over the old flat 4,000-token total, one key per layer
#: in prompt order (SOLUSDEV-321 P0-T4) — the same shares models.yaml ships.
_DEFAULT_LAYER_SCALE: Final = {
    "preferences": 0.2,
    "project_card": 0.1,
    "solus_standing": 0.15,
    "graph": 0.3,
    "solus_scoped": 0.1,
    "findings": 0.15,
    "conversation": 1.5,
    "retrieval": 0.3,
    "corpus": 1.0,
    "telemetry": 0.15,
    "screen": 0.15,
}


class ContextBudgetConfig(BaseModel):
    """SOL's context budget by routing tier (`context_budget:` in models.yaml,
    SOLUSDEV-321): the total tokens `build_context` may pack for a turn at that
    tier. `layer_scale` maps a context layer's name to its cap as a fraction of
    the total — `LayeredContextBudget.for_tier` (agent/layers.py) turns the two
    into per-layer caps and is where the names are checked against the real
    layers. The default shares are the `LayerBudget` defaults over the old flat
    4,000, so a standard turn is the pre-tier turn scaled up."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trivial: int = Field(default=8_000, gt=0)
    standard: int = Field(default=24_000, gt=0)
    hard: int = Field(default=60_000, gt=0)
    layer_scale: dict[str, Annotated[float, Field(gt=0)]] = Field(
        default_factory=lambda: dict(_DEFAULT_LAYER_SCALE)
    )

    @model_validator(mode="after")
    def _totals_are_ordered(self) -> Self:
        """A typo putting `hard` below `standard` would quietly give the hardest
        questions the least room."""
        if not self.trivial <= self.standard <= self.hard:
            raise ValueError(
                "context_budget totals must be ordered trivial <= standard <= hard "
                f"(got {self.trivial} / {self.standard} / {self.hard})"
            )
        return self

    def total_for(self, tier: Complexity) -> int:
        """The total token budget for `tier` (one field per `Complexity` member)."""
        return int(getattr(self, tier.value))


#: A scope keyword: trimmed, lowercased, never blank (a blank one would match every message).
_ScopeKeyword = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1)
]


class ScopeConfig(BaseModel):
    """What the scope planner reads in a message (`scope:` in models.yaml, SOLUSDEV-321).

    `domain_keywords` are plain words or short phrases, not regexes — the runtime and
    environment groups, which also gate the divergences table. Deliberately NOT
    `estimator.domain_keywords`: every group matched there adds `weights.extra_domain` to
    the complexity score, so a runtime or environment group would shift model routing.
    `connectivity_patterns` and `counting_patterns` are explicit regexes (IGNORECASE,
    validated at load, like `practice_patterns`): a connectivity question with a `wires`
    edge in scope is never answered from a render, and a counting question is the first
    tier's (P1-T1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain_keywords: dict[str, list[_ScopeKeyword]] = Field(default_factory=dict)
    connectivity_patterns: list[str] = Field(default_factory=list)
    counting_patterns: list[str] = Field(default_factory=list)

    _connectivity_regexes: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _counting_regexes: list[re.Pattern[str]] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _compile_patterns(self) -> Self:
        self._connectivity_regexes = _compile_family(
            "connectivity_patterns", self.connectivity_patterns
        )
        self._counting_regexes = _compile_family("counting_patterns", self.counting_patterns)
        return self

    @property
    def connectivity_regexes(self) -> list[re.Pattern[str]]:
        return self._connectivity_regexes

    @property
    def counting_regexes(self) -> list[re.Pattern[str]]:
        return self._counting_regexes


class EnvelopesConfig(BaseModel):
    """How a part's envelope derives its bounds (`envelopes:` in models.yaml, SOLUSDEV-321 P2-T1).

    A part never states a warn bound: `warn_fraction` is the share of its limit at which the
    envelope starts to warn — of the half-range from the midpoint when the limit has two sides.
    Strictly between nothing and the whole limit: 0 would warn on everything and 1 never ahead of
    the limit itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    warn_fraction: float = Field(default=0.8, gt=0, lt=1)


class ObserverConfig(BaseModel):
    """What a robot session's window evaluator may spend on one window (`observer:` in
    models.yaml, SOLUSDEV-321 P2-T3b): its live-signal rules share `max(cpu_budget_ms,
    cpu_budget_ms_per_part x the session's parts)` milliseconds of CPU, so the budget grows with
    the robot and `cpu_budget_ms` is the floor. The floor is above zero (a window that may spend
    nothing judges nothing); a part may add nothing, which is a fixed budget."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cpu_budget_ms: float = Field(default=20, gt=0)
    cpu_budget_ms_per_part: float = Field(default=10, ge=0)


#: A simulated quantity's or a routing target's name: a lowercase identifier, so a style entry
#: (`simulate <quantity> with <target>`) and a finding headline read it back whole.
SIM_NAME_PATTERN: Final = r"^[a-z][a-z0-9_]{0,63}$"
SimName = Annotated[str, StringConstraints(pattern=SIM_NAME_PATTERN)]
#: A rung of the simulation ladder (docs/api/simulation.md §1): 1 closed-form code, 2 an external
#: target, 3 local headless jobs, 4 an external full simulation. An integer, never a bool.
SimRung = Annotated[int, Field(ge=1, le=4, strict=True)]


class SimTargetConfig(BaseModel):
    """One external routing target of the simulation ladder (`simulation.targets` in models.yaml,
    SOLUSDEV-321 P4-T1). This is the one place a target is named: the simulation package names
    none.

    `rung` is where it runs, `domain` the world it models and `quantities` what it computes.
    `cost` and `fidelity` are ordinals that rank it among a question's candidates. Each defaults
    to its rung, the same rank a built-in provider gets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: SimName
    rung: SimRung
    domain: str = Field(min_length=1, max_length=32)
    quantities: tuple[SimName, ...] = Field(min_length=1)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    fidelity: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class SimulationConfig(BaseModel):
    """When the simulation ladder climbs, and where it may route (`simulation:` in models.yaml,
    SOLUSDEV-321 P4-T1, docs/api/simulation.md §4).

    A value at or past its quantity's band of a limit climbs to the next rung. The band is
    `bands[quantity]`, else `escalate_at`: 0.8, the spec's "within 20 % of a limit". A value with
    margin stops where it is. Like `envelopes.warn_fraction`, a band lies strictly between nothing
    and the whole limit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    escalate_at: float = Field(default=0.8, gt=0, lt=1)
    bands: dict[SimName, Annotated[float, Field(gt=0, lt=1)]] = Field(default_factory=dict)
    targets: tuple[SimTargetConfig, ...] = ()

    @model_validator(mode="after")
    def _targets_are_named_once(self) -> Self:
        names = [target.name for target in self.targets]
        if len(names) != len(set(names)):
            raise ValueError(f"simulation targets must each be named once (got {names})")
        return self

    def band(self, quantity: str) -> float:
        """The fraction of its limit at which `quantity` climbs to the next rung."""
        return self.bands.get(quantity, self.escalate_at)

    def target(self, name: str) -> SimTargetConfig | None:
        """The target named `name`; None when the yaml names none."""
        return next((target for target in self.targets if target.name == name), None)


class LimitsConfig(BaseModel):
    """MO-03 pre-flight and retry knobs — ALL tunable in models.yaml, no code change.

    `trial_credit_cap` is denominated in CREDITS (same unit the ledger debits) and is
    PROVISIONAL like the prices. The frequency cap is FLAT for every plan (abuse
    insurance, not a plan feature). Retry knobs govern OUR provider-side backoff
    (adapters deliberately pass max_retries=0 to the SDKs)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_credit_cap: int = Field(default=1000, ge=0)
    # M25: capped — the gates' local window holds up to this many timestamps per remembered user.
    max_calls_per_minute: int = Field(default=20, gt=0, le=10_000)
    frequency_window_seconds: int = Field(default=60, gt=0)
    retry_max_attempts: int = Field(default=3, ge=1)  # total tries incl. the first
    retry_backoff_seconds: float = Field(default=0.5, ge=0)  # base; doubles per retry


class ProviderStanza(BaseModel):
    """Connection shape for a provider that has NO dedicated adapter yet
    (SOLUSDEV-252: `azure`). Config only — the gateway still needs an adapter
    registered under the same provider key before a catalog entry can route
    there; until then dispatch raises `UnknownProviderError` by design.
    `api_key_ref` is a SecretStore ref name, never a key value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["openai_compatible"]
    endpoint: str = ""  # may be empty until deploy fills it
    api_version: str
    api_key_ref: str
    deployments: dict[str, str] = Field(default_factory=dict)  # catalog name -> deployment


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
    providers: dict[str, ProviderStanza] = Field(default_factory=dict)  # adapter-less providers
    context_budget: ContextBudgetConfig = Field(default_factory=ContextBudgetConfig)
    #: Phrases (regexes, IGNORECASE, validated at load) that mark a question as asking
    #: for practice guidance — the only questions that consult the engineering corpus.
    practice_patterns: list[str] = Field(default_factory=list)
    scope: ScopeConfig = Field(default_factory=ScopeConfig)
    envelopes: EnvelopesConfig = Field(default_factory=EnvelopesConfig)
    observer: ObserverConfig = Field(default_factory=ObserverConfig)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)

    _role_index: dict[str, ModelCatalogEntry] = PrivateAttr(default_factory=dict)
    _practice_regexes: list[re.Pattern[str]] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _compile_practice_patterns(self) -> Self:
        self._practice_regexes = _compile_family("practice_patterns", self.practice_patterns)
        return self

    @property
    def practice_regexes(self) -> list[re.Pattern[str]]:
        return self._practice_regexes

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

    @model_validator(mode="after")
    def _screenshot_cells_accept_images(self) -> Self:
        """Review M2: a text-only model pointed at a GENERAL or CODE cell (any
        tier) — or at `default_role`, which fills any missing cell — fails here,
        not on a paid call with pixels attached."""
        cells = [
            (f"{complexity.value}/{route_type.value}", row[route_type])
            for complexity, row in self.matrix.items()
            for route_type in (RouteType.GENERAL, RouteType.CODE, RouteType.VISUAL_LOG)
            if route_type in row
        ]
        cells.append(("default_role", self.default_role))
        for cell, role in cells:
            entry = self._role_index[role]
            if not entry.accepts_images:
                raise ValueError(
                    f"matrix cell {cell} routes to {entry.name!r}, which has accepts_images "
                    "false; GENERAL, CODE and VISUAL_LOG cells carry images and need a vision model"
                )
        return self

    def entry_for_role(self, role: str) -> ModelCatalogEntry:
        """Resolve a role to its concrete catalog entry (validated to exist)."""
        return self._role_index[role]


def load_orchestration_config(path: Path | None = None) -> OrchestrationConfig:
    """Load and validate the model catalog; defaults to the sibling `models.yaml`."""
    source = path or _DEFAULT_CONFIG_PATH
    data = yaml.safe_load(source.read_text())
    return OrchestrationConfig.model_validate(data)
