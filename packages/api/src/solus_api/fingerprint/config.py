"""FP-01 matcher configuration: taxonomy, weights, thresholds (SOLUSDEV-59).

Mirrors `orchestration/config.py`: frozen Pydantic models with `extra="forbid"`,
regexes compiled and validated at load time (a bad pattern fails the load, not a
match call), a `load_fingerprint_config()` defaulting to the sibling
`matching.yaml`, and a process-wide lazy singleton.

The load-time cross-checks are safety guarantees, not conveniences: a config
edit can never silently let a datasheet or an LLM signal decide a merge —
`datasheet < thresholds.matched`, `generic_symbol < thresholds.low_confidence`,
and `llm.confidence_cap < thresholds.matched` are enforced here.
"""

import re
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

_DEFAULT_CONFIG_PATH = Path(__file__).with_name("matching.yaml")

# Structural charset for a manufacturer part number. Code, not config: this is
# the injection/garbage firewall (CLAUDE.md §7), not a tuning knob.
MPN_CHARSET = re.compile(r"[A-Z0-9./+_-]+")


def _compile_pattern(family: str, pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:  # pragma: no cover - exercised via validators
        raise ValueError(f"{family}: invalid regex {pattern!r}: {exc}") from exc


def _require_upper_tokens(field: str, tokens: list[str]) -> None:
    for token in tokens:
        if not token or token != token.strip() or token != token.upper():
            raise ValueError(f"{field}: suffix tokens must be non-empty uppercase: {token!r}")


class FamilyRule(BaseModel):
    """One family's decomposition rule. An input is stripped ONLY if it splits
    exactly as [strip_prefix] + stem + [suffix] with the stem fullmatching
    `stem_pattern` and the suffix an exact member of the lists below — or, for
    families with a POSITIONAL ordering scheme (ST's package+temp characters),
    a `suffix_pattern` regex the tail must fullmatch as part of a combined
    stem+suffix fullmatch (A2, 2026-07-12)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    stem_pattern: str = Field(min_length=1)
    strip_prefixes: list[str] = Field(default_factory=list)
    package_suffixes: list[str] = Field(default_factory=list)
    grade_suffixes: list[str] = Field(default_factory=list)
    hyphen_suffixes: list[str] = Field(default_factory=list)
    suffix_pattern: str | None = None

    _stem: re.Pattern[str] = PrivateAttr()
    _stem_suffix: re.Pattern[str] | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _compile_and_check(self) -> Self:
        self._stem = _compile_pattern(self.name, self.stem_pattern)
        for field in ("strip_prefixes", "package_suffixes", "grade_suffixes", "hyphen_suffixes"):
            _require_upper_tokens(f"{self.name}.{field}", getattr(self, field))
        if self.suffix_pattern is not None:
            suffix = _compile_pattern(f"{self.name}.suffix_pattern", self.suffix_pattern)
            if suffix.fullmatch(""):
                raise ValueError(f"{self.name}.suffix_pattern must not match the empty string")
            # Named groups: stems contain their own parens, so numbered groups
            # would silently shift — a latent false-merge bug class.
            self._stem_suffix = _compile_pattern(
                f"{self.name}.suffix_pattern",
                f"(?P<stem>{self.stem_pattern})(?P<sfx>{self.suffix_pattern})",
            )
        return self

    @property
    def stem(self) -> re.Pattern[str]:
        return self._stem

    @property
    def stem_suffix(self) -> re.Pattern[str] | None:
        return self._stem_suffix


class ExtractionConfig(BaseModel):
    """Symbol/datasheet token extraction knobs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_token_len: int = Field(default=4, ge=1)
    max_text_len: int = Field(default=256, ge=16)
    generic_symbol_patterns: list[str] = Field(default_factory=list)
    datasheet_extensions: list[str] = Field(default_factory=list)

    _generic: list[re.Pattern[str]] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _compile(self) -> Self:
        self._generic = [
            _compile_pattern("generic_symbol_patterns", p) for p in self.generic_symbol_patterns
        ]
        return self

    @property
    def generic_patterns(self) -> list[re.Pattern[str]]:
        return self._generic


class Weights(BaseModel):
    """Evidence-strength rules table (spec Part B). All 0..1."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exact_mpn: float = Field(ge=0, le=1)
    base_known_suffix: float = Field(ge=0, le=1)
    specific_symbol: float = Field(ge=0, le=1)
    generic_symbol: float = Field(ge=0, le=1)
    datasheet: float = Field(ge=0, le=1)
    photo: float = Field(ge=0, le=1)
    corroboration_bonus: float = Field(ge=0, le=1)


class Penalties(BaseModel):
    """Overall-confidence penalties for visible conflicts within one part."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    package_conflict: float = Field(ge=0, le=1)
    footprint_conflict: float = Field(ge=0, le=1)
    manufacturer_conflict: float = Field(ge=0, le=1)


class Thresholds(BaseModel):
    """Score → W0-06 state mapping (spec Part C)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    matched: float = Field(gt=0, le=1)
    low_confidence: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.matched > self.low_confidence:
            raise ValueError("thresholds: matched must be > low_confidence")
        return self


class LlmConfig(BaseModel):
    """LLM escalation bounds (spec Part E)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence_cap: float = Field(gt=0, le=1)
    max_input_chars: int = Field(default=64, ge=8, le=256)


class FingerprintConfig(BaseModel):
    """The full matcher config; loaded from `matching.yaml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    vendor_prefixes: list[str] = Field(default_factory=list)
    placeholder_tokens: list[str] = Field(default_factory=list)
    value_patterns: list[str] = Field(default_factory=list)
    min_mpn_len: int = Field(default=4, ge=1)
    max_mpn_len: int = Field(default=64, ge=8)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    families: list[FamilyRule] = Field(default_factory=list)
    weights: Weights
    penalties: Penalties
    thresholds: Thresholds
    llm: LlmConfig

    _values: list[re.Pattern[str]] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _validate_cross_rules(self) -> Self:
        self._values = [_compile_pattern("value_patterns", p) for p in self.value_patterns]
        for prefix in self.vendor_prefixes:
            if not prefix or prefix[-1].isalnum() or prefix != prefix.upper():
                raise ValueError(
                    f"vendor_prefixes: {prefix!r} must be uppercase and include its separator"
                )
        _require_upper_tokens("placeholder_tokens", self.placeholder_tokens)
        names = [family.name for family in self.families]
        if len(names) != len(set(names)):
            raise ValueError("families: names must be unique")
        # The precision guarantees. A config edit cannot cross these lines.
        if not self.weights.datasheet < self.thresholds.matched:
            raise ValueError("weights.datasheet must stay below thresholds.matched")
        if not self.weights.generic_symbol < self.thresholds.low_confidence:
            raise ValueError("weights.generic_symbol must stay below thresholds.low_confidence")
        if not self.weights.photo < self.thresholds.matched:
            raise ValueError("weights.photo must stay below thresholds.matched")
        if not self.llm.confidence_cap < self.thresholds.matched:
            raise ValueError("llm.confidence_cap must stay below thresholds.matched")
        if not self.min_mpn_len < self.max_mpn_len:
            raise ValueError("min_mpn_len must be < max_mpn_len")
        return self

    @property
    def value_regexes(self) -> list[re.Pattern[str]]:
        return self._values


def load_fingerprint_config(path: Path | None = None) -> FingerprintConfig:
    """Load and validate the matcher config; defaults to the sibling `matching.yaml`."""
    source = path or _DEFAULT_CONFIG_PATH
    data = yaml.safe_load(source.read_text())
    return FingerprintConfig.model_validate(data)


_default_config: FingerprintConfig | None = None


def default_fingerprint_config() -> FingerprintConfig:
    """Process-wide lazy singleton, parsed once (edits need a restart)."""
    global _default_config
    if _default_config is None:
        _default_config = load_fingerprint_config()
    return _default_config
