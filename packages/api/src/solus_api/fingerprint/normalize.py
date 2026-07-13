"""FP-01 MPN normalization: explicit-taxonomy-only, fail-safe on the unknown.

THE NON-NEGOTIABLE RULE (spec Part A): stripping happens ONLY when an input
decomposes exactly as `[prefix] + stem + [suffix]` with the stem fullmatching a
config `FamilyRule` and the suffix an exact member of that family's lists.
Anything else — unknown family, unknown suffix, leftover residue, or two
families proposing different bases — is NEVER stripped: the identity is the
whole (trimmed, uppercased) string. Worst case is a missed merge, never a
false merge. `LM3588` is structurally untouchable: `8` is in no suffix list.
"""

import re
import uuid

from pydantic import BaseModel, ConfigDict

from solus_api.fingerprint.config import MPN_CHARSET, FingerprintConfig

# uuid5(NAMESPACE_DNS, "fingerprint.solus.dev"), PINNED. This namespace is part
# of the identity contract: canonical_id = uuid5(namespace, base) must be stable
# across runs, processes, and machines (spec Part D / FP-02 idempotent merge).
# Changing it re-keys every canonical part — never touch it.
SOLUS_FINGERPRINT_NAMESPACE = uuid.UUID("5303bedc-ab6d-5aed-927f-b8c897c5e801")

_TOKEN_SPLIT = re.compile(r"[:_/\\,()|\s]+")


def canonical_uuid(base: str) -> uuid.UUID:
    """Deterministic canonical identity: same base → same UUID, everywhere."""
    return uuid.uuid5(SOLUS_FINGERPRINT_NAMESPACE, base)


class NormalizedMPN(BaseModel):
    """A normalized part number: `base` is the canonical identity; everything
    stripped on the way is preserved as evidence (the visible-conflict feature)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    original: str
    base: str
    vendor_prefix: str | None = None
    family: str | None = None
    package: str | None = None
    grade: str | None = None


class _Decomposition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base: str
    family: str
    package: str | None = None
    grade: str | None = None


def _is_plausible_mpn(text: str, config: FingerprintConfig) -> bool:
    """The identity/garbage firewall: placeholders, passive-component values,
    free text, and injection strings all fail here and go to `unmatched`."""
    if not config.min_mpn_len <= len(text) <= config.max_mpn_len:
        return False
    if MPN_CHARSET.fullmatch(text) is None:
        return False
    if text in config.placeholder_tokens:
        return False
    if any(pattern.fullmatch(text) for pattern in config.value_regexes):
        return False
    has_letter = any(ch.isalpha() for ch in text)
    has_digit = any(ch.isdigit() for ch in text)
    return has_letter and has_digit


def _strip_vendor_prefix(text: str, config: FingerprintConfig) -> tuple[str, str | None]:
    for prefix in sorted(config.vendor_prefixes, key=len, reverse=True):
        rest = text.removeprefix(prefix)
        if rest != text and _is_plausible_mpn(rest, config):
            return rest, prefix
    return text, None


def _family_tails(
    family_packages: list[str], family_grades: list[str]
) -> dict[str, tuple[str | None, str | None]]:
    """tail → (grade, package): plain package, plain grade, grade+package compound."""
    tails: dict[str, tuple[str | None, str | None]] = {}
    for package in family_packages:
        tails[package] = (None, package)
    for grade in family_grades:
        tails.setdefault(grade, (grade, None))
    for grade in family_grades:
        for package in family_packages:
            tails.setdefault(grade + package, (grade, package))
    return tails


def _decompositions(core: str, config: FingerprintConfig) -> list[_Decomposition]:
    found: list[_Decomposition] = []
    for family in config.families:
        for prefix in ["", *family.strip_prefixes]:
            rest = core.removeprefix(prefix)
            if prefix and rest == core:
                continue
            if prefix and family.stem.fullmatch(rest):
                found.append(_Decomposition(base=rest, family=family.name))
            stem, _, hyphen_tail = rest.rpartition("-")
            if stem and hyphen_tail in family.hyphen_suffixes and family.stem.fullmatch(stem):
                found.append(_Decomposition(base=stem, family=family.name, package=hyphen_tail))
            # Positional ordering-scheme suffix (A2): the tail must fullmatch as
            # part of a combined stem+suffix fullmatch — anything else strips
            # NOTHING (fail-safe on the unknown).
            if family.stem_suffix is not None and (match := family.stem_suffix.fullmatch(rest)):
                found.append(
                    _Decomposition(base=match["stem"], family=family.name, package=match["sfx"])
                )
            for tail, (grade, package) in _family_tails(
                family.package_suffixes, family.grade_suffixes
            ).items():
                candidate = rest.removesuffix(tail)
                if candidate != rest and candidate and family.stem.fullmatch(candidate):
                    found.append(
                        _Decomposition(
                            base=candidate, family=family.name, package=package, grade=grade
                        )
                    )
    return found


def _strip_separators(base: str, config: FingerprintConfig) -> str | None:
    """Separator policy (adjudicated 2026-07-12): hyphens are typography, not
    identity (MPU-6050 ≡ MPU6050). Runs AFTER decomposition so hyphen_suffixes
    still see their hyphens; strips ONLY "-" (a space can never survive
    MPN_CHARSET). The de-separated base must re-pass the plausibility gate —
    '10-K' de-hyphenates into passive value '10K' and must die here, never
    become an identity. Post-separator tokens are never re-interpreted."""
    stripped = base.replace("-", "")
    if stripped == base:
        return base
    if not _is_plausible_mpn(stripped, config):
        return None
    # COLLISION GUARD: de-hyphenation must never MINT a taxonomy-known identity
    # ("LM358-8" would become "LM3588" — the C1 catastrophic pair through a side
    # door; "ATMEGA328-P" would mint the picoPower die). If the de-hyphenated
    # form enters known identity space (fullmatches a family stem or decomposes
    # under one), fail safe: the hyphenated whole stays the identity. The
    # adjudicated merges are unaffected (MPU6050 / NRF52832QFAA match no
    # family); taxonomy-sanctioned hyphen tails belong in hyphen_suffixes.
    if any(family.stem.fullmatch(stripped) for family in config.families):
        return base
    if _decompositions(stripped, config):
        return base
    return stripped


def normalize_mpn(raw: str, config: FingerprintConfig) -> NormalizedMPN | None:
    """Normalize one part-number string, or return None when no stable physical
    identity is derivable (spec: "no derivable MPN → unmatched")."""
    text = raw.strip().upper()
    if not _is_plausible_mpn(text, config):
        return None
    core, vendor_prefix = _strip_vendor_prefix(text, config)

    # As-is stem match wins outright: the whole core IS a known identity, so no
    # suffix interpretation may shorten it (this is what protects ATMEGA328P's
    # trailing P and keeps LM3588 whole).
    for family in config.families:
        if family.stem.fullmatch(core):
            base = _strip_separators(core, config)
            if base is None:
                return None
            return NormalizedMPN(
                original=raw, base=base, vendor_prefix=vendor_prefix, family=family.name
            )

    decompositions = _decompositions(core, config)
    bases = {decomposition.base for decomposition in decompositions}
    if len(bases) != 1:
        # Unknown family/suffix, or conflicting family readings: fail safe, keep whole.
        base = _strip_separators(core, config)
        if base is None:
            return None
        return NormalizedMPN(original=raw, base=base, vendor_prefix=vendor_prefix)
    chosen = decompositions[0]
    base = _strip_separators(chosen.base, config)
    if base is None:
        return None
    return NormalizedMPN(
        original=raw,
        base=base,
        vendor_prefix=vendor_prefix,
        family=chosen.family,
        package=chosen.package,
        grade=chosen.grade,
    )


def _strip_extension(token: str, config: FingerprintConfig) -> str:
    for extension in config.extraction.datasheet_extensions:
        token = token.removesuffix(extension)
    return token


def extract_candidate_bases(text: str, config: FingerprintConfig) -> list[str]:
    """Candidate identity bases named inside a symbol/datasheet string.

    Candidates only CORROBORATE: a candidate matters solely when it exactly
    equals an existing part_number group's base, so over-extraction can never
    create identity. Hyphen sub-tokens are included (TI's `lm2904-n` filename
    quirk); part_number values are never token-split — only these strings are.
    """
    cleaned = text.strip().upper()
    if not cleaned or len(cleaned) > config.extraction.max_text_len:
        return []
    bases: set[str] = set()
    for token in _TOKEN_SPLIT.split(cleaned):
        candidates = {token, *token.split("-")}
        for candidate in candidates:
            stripped = _strip_extension(candidate, config)
            if len(stripped) < config.extraction.min_token_len:
                continue
            normalized = normalize_mpn(stripped, config)
            if normalized is not None:
                bases.add(normalized.base)
    return sorted(bases)
