"""Compliance / style rules for sourcing (SOLUSDEV-246 ST5) — typed and deterministic.

Solus code decides every exclusion; the reason shown is the rule's own text,
never a model's judgement. Layers (each typed, unknown keys never survive):
built-in empty defaults ← the repo `.solus/project.toml` `[ext.sourcing]` table
(scalar strings, ADR-035 §4 as amended) ← the project's rules document (a
`sourcing_rules` graph node the desktop edits). Unknown facts on a candidate
(no voltage listed) are FLAGGED, never used to exclude — empty beats invented.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from solus_api.sourcing.candidates import Candidate

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
DEFAULT_EXCLUSION_REASON = "Excluded by the project's .solus rules"
MAX_LIST = 32


class ExcludedSupplier(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Short
    reason: Reason = DEFAULT_EXCLUSION_REASON


class SourcingRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    excluded_suppliers: Annotated[list[ExcludedSupplier], Field(max_length=MAX_LIST)] = []
    required_certifications: Annotated[list[Short], Field(max_length=MAX_LIST)] = []
    max_voltage_v: Annotated[float, Field(ge=0, le=100_000)] | None = None
    allowed_protocols: Annotated[list[Short], Field(max_length=MAX_LIST)] = []
    preferred_suppliers: Annotated[list[Short], Field(max_length=MAX_LIST)] = []

    def payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _split(raw: object, sep: str = ",") -> list[str]:
    if not isinstance(raw, str):
        return []
    return [part.strip() for part in raw.split(sep) if part.strip()][:MAX_LIST]


def _excluded(raw: object) -> list[ExcludedSupplier]:
    """`"Acme Motors: export controlled; Foo Parts"` → typed entries."""
    entries: list[ExcludedSupplier] = []
    for item in _split(raw, ";"):
        name, _, reason = item.partition(":")
        if not name.strip():
            continue
        try:
            entries.append(
                ExcludedSupplier(
                    name=name.strip()[:80],
                    reason=(reason.strip() or DEFAULT_EXCLUSION_REASON)[:200],
                )
            )
        except ValueError:
            continue
    return entries


def rules_from_repo_table(table: dict[str, Any]) -> SourcingRules:
    """The `[ext.sourcing]` scalars → rules. Wrong types are dropped, never raised."""
    voltage = table.get("max_voltage_v")
    max_voltage: float | None = None
    if isinstance(voltage, int | float) and not isinstance(voltage, bool):
        max_voltage = float(voltage) if 0 <= voltage <= 100_000 else None
    try:
        return SourcingRules(
            excluded_suppliers=_excluded(table.get("excluded_suppliers")),
            required_certifications=[s[:80] for s in _split(table.get("required_certifications"))],
            max_voltage_v=max_voltage,
            allowed_protocols=[s[:80] for s in _split(table.get("allowed_protocols"))],
            preferred_suppliers=[s[:80] for s in _split(table.get("preferred_suppliers"))],
        )
    except ValueError:
        return SourcingRules()


def merge_rules(*layers: SourcingRules) -> SourcingRules:
    """Later layers override earlier ones field by field (a set field wins;
    an empty list or None leaves the earlier value)."""
    merged: dict[str, Any] = SourcingRules().model_dump()
    for layer in layers:
        for key, value in layer.model_dump().items():
            if value not in ([], None):
                merged[key] = value
    return SourcingRules.model_validate(merged)


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _supplier_rule(candidate: Candidate, rules: SourcingRules) -> str | None:
    haystack = _norm(f"{candidate.supplier or ''} {candidate.manufacturer or ''}")
    for entry in rules.excluded_suppliers:
        if _norm(entry.name) in haystack:
            who = candidate.supplier or candidate.manufacturer
            return f"Supplier '{who}' is excluded: {entry.reason}"
    return None


def _voltage_rule(candidate: Candidate, rules: SourcingRules) -> tuple[str | None, str | None]:
    """(reason, flag) from the voltage ceiling."""
    if rules.max_voltage_v is None:
        return None, None
    if candidate.voltage_v is None:
        return None, f"Voltage unknown (project maximum {rules.max_voltage_v:.1f} V)"
    if candidate.voltage_v > rules.max_voltage_v:
        return (
            f"Voltage {candidate.voltage_v:.1f} V exceeds the project maximum of "
            f"{rules.max_voltage_v:.1f} V",
            None,
        )
    return None, None


def _protocol_rule(candidate: Candidate, rules: SourcingRules) -> tuple[str | None, str | None]:
    if not rules.allowed_protocols:
        return None, None
    allowed = ", ".join(rules.allowed_protocols)
    if candidate.protocol is None:
        return None, f"Protocol unknown (allowed: {allowed})"
    if _norm(candidate.protocol) not in {_norm(p) for p in rules.allowed_protocols}:
        return f"Protocol '{candidate.protocol}' is not allowed; allowed: {allowed}", None
    return None, None


def _certification_rules(
    candidate: Candidate, rules: SourcingRules
) -> tuple[list[str], str | None]:
    if not rules.required_certifications:
        return [], None
    if not candidate.certifications:
        required = ", ".join(rules.required_certifications)
        return [], f"Certifications unknown (required: {required})"
    have = {_norm(c) for c in candidate.certifications}
    missing = [r for r in rules.required_certifications if _norm(r) not in have]
    return [f"Missing required certification: {r}" for r in missing], None


def _check(candidate: Candidate, rules: SourcingRules) -> tuple[list[str], list[str]]:
    """(reasons to exclude, flags to show) for one candidate."""
    reasons: list[str] = []
    flags: list[str] = []
    supplier = _supplier_rule(candidate, rules)
    if supplier:
        reasons.append(supplier)
    for reason, flag in (_voltage_rule(candidate, rules), _protocol_rule(candidate, rules)):
        if reason:
            reasons.append(reason)
        if flag:
            flags.append(flag)
    cert_reasons, cert_flag = _certification_rules(candidate, rules)
    reasons.extend(cert_reasons)
    if cert_flag:
        flags.append(cert_flag)
    return reasons, flags


def _preferred(candidate: Candidate, rules: SourcingRules) -> bool:
    haystack = _norm(f"{candidate.supplier or ''} {candidate.manufacturer or ''}")
    return any(_norm(p) in haystack for p in rules.preferred_suppliers)


def apply_rules(
    candidates: list[Candidate], rules: SourcingRules
) -> tuple[list[Candidate], list[tuple[Candidate, list[str]]]]:
    """Pure. Included candidates (preferred suppliers first, otherwise the
    model's order) with their flags; excluded ones with the rule text."""
    included: list[Candidate] = []
    excluded: list[tuple[Candidate, list[str]]] = []
    for candidate in candidates:
        reasons, flags = _check(candidate, rules)
        if reasons:
            excluded.append((candidate.with_flags(flags), reasons))
            continue
        preferred = _preferred(candidate, rules)
        included.append(candidate.with_flags((["Preferred supplier"] if preferred else []) + flags))
    included.sort(key=lambda c: 0 if "Preferred supplier" in c.flags else 1)
    return included, excluded
