"""Environment rules over the graph's Python requirements (SOLUSDEV-250 / INTEGRATIONS I3).

`python_requirement` nodes are landed by the local-folder connector from the
linked folder's dependency declarations (one node per source file × package).
The rule here is the CUDA/torch-style catch the autocomplete design named and
never had an input for (`docs/architecture/solus-folder.md` §4): the same
package pinned differently across files. Pure: graph in, warnings out; a
malformed specifier is skipped, never guessed (checker contract).

`propose_environments` is the deterministic proposal SOL and the desktop row
both show: one environment per conflicting source file, otherwise one. It is a
plan, not an action — the `code` server executes only what the approval card
showed.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from solus_api.agent.interfaces import GraphContext
from solus_api.checkers.interface import Checker, Severity, Warning
from solus_api.fingerprint.contract import FingerprintOutput

REQUIREMENT_KIND: Final = "python_requirement"
_NORMALIZE: Final = re.compile(r"[-_.]+")
_PIN: Final = re.compile(r"^==\s*([0-9][^,;\s]*)$")


def normalize_package_name(name: str) -> str:
    """PEP 503: lower-case, runs of `-_.` collapse to `-`."""
    return _NORMALIZE.sub("-", name.strip()).lower()


@dataclass(frozen=True)
class Requirement:
    entity_id: UUID
    name: str
    specifier: str
    source_file: str

    @property
    def pin(self) -> Version | None:
        match = _PIN.match(self.specifier.strip())
        if match is None:
            return None
        try:
            return Version(match.group(1))
        except InvalidVersion:
            return None

    @property
    def specifier_set(self) -> SpecifierSet | None:
        try:
            return SpecifierSet(self.specifier.strip())
        except InvalidSpecifier:
            return None


def requirements_of(graph: GraphContext) -> list[Requirement]:
    """The well-formed requirement nodes; anything missing its attributes is skipped."""
    out: list[Requirement] = []
    for entity in graph.entities:
        if entity.kind != REQUIREMENT_KIND:
            continue
        name = entity.attrs.get("name")
        source = entity.attrs.get("source_file")
        specifier = entity.attrs.get("specifier", "")
        if not isinstance(name, str) or not name or not isinstance(source, str):
            continue
        out.append(
            Requirement(
                entity_id=entity.id,
                name=normalize_package_name(name),
                specifier=specifier if isinstance(specifier, str) else "",
                source_file=source,
            )
        )
    return out


def _conflict(a: Requirement, b: Requirement) -> Severity | None:
    """CRITICAL: two different exact pins. WARNING: a pin another file's range
    excludes. None: compatible, identical, or not decidable."""
    pin_a, pin_b = a.pin, b.pin
    if pin_a is not None and pin_b is not None:
        return Severity.CRITICAL if pin_a != pin_b else None
    pinned, ranged = (a, b) if pin_a is not None else (b, a)
    pin = pinned.pin
    spec = ranged.specifier_set
    if pin is None or spec is None or not ranged.specifier.strip():
        return None
    return None if spec.contains(pin, prereleases=True) else Severity.WARNING


class PinConflictChecker(Checker):
    """The same package pinned differently across the folder's dependency files."""

    checker_id = "python_pin_conflict"
    domains = ("code",)

    def check(self, graph: GraphContext, parts: FingerprintOutput) -> list[Warning]:
        by_name: dict[str, list[Requirement]] = defaultdict(list)
        for req in requirements_of(graph):
            by_name[req.name].append(req)
        warnings: list[Warning] = []
        for name, reqs in sorted(by_name.items()):
            if len(reqs) < 2:
                continue
            worst: Severity | None = None
            for i, a in enumerate(reqs):
                for b in reqs[i + 1 :]:
                    if a.source_file == b.source_file:
                        continue
                    severity = _conflict(a, b)
                    if severity is not None and (worst is None or severity is Severity.CRITICAL):
                        worst = severity
            if worst is None:
                continue
            pins = sorted(
                ({"source_file": r.source_file, "specifier": r.specifier} for r in reqs),
                key=lambda p: (p["source_file"], p["specifier"]),
            )
            files = ", ".join(sorted({r.source_file for r in reqs}))
            warnings.append(
                Warning(
                    checker_id=self.checker_id,
                    severity=worst,
                    domains=self.domains,
                    message=(
                        f"'{name}' is pinned differently across {files} — one environment "
                        "cannot satisfy both."
                    ),
                    evidence={"package": name, "pins": pins},
                    entity_ids=tuple(r.entity_id for r in reqs),
                    suggested_area=(
                        "split the environments: one virtual environment per requirement file "
                        "that pins this package"
                    ),
                )
            )
        return warnings


def _env_name(source_file: str) -> str:
    parts = [p for p in source_file.split("/") if p]
    if len(parts) > 1:
        return normalize_package_name(parts[-2])
    stem = parts[0] if parts else "default"
    stem = re.sub(r"\.(txt|toml|yml|yaml)$", "", stem)
    stem = re.sub(r"^requirements[-_]?", "", stem)
    return normalize_package_name(stem) or "policy"


def propose_environments(graph: GraphContext) -> dict[str, Any]:
    """One environment per conflicting source file, else one `default`. Pure."""
    reqs = requirements_of(graph)
    if not reqs:
        return {"environments": [], "conflicts": [], "split": False}
    warnings = PinConflictChecker().check(
        graph, FingerprintOutput(canonical_parts=[], unmatched=[], ambiguous=[])
    )
    conflicting_files = {pin["source_file"] for w in warnings for pin in w.evidence.get("pins", [])}
    by_file: dict[str, list[Requirement]] = defaultdict(list)
    for req in reqs:
        by_file[req.source_file].append(req)

    def rows(items: list[Requirement]) -> list[dict[str, str]]:
        return [
            {"name": r.name, "specifier": r.specifier, "source_file": r.source_file}
            for r in sorted(items, key=lambda r: (r.name, r.source_file))
        ]

    if not conflicting_files:
        return {
            "environments": [
                {"name": "default", "source_files": sorted(by_file), "requirements": rows(reqs)}
            ],
            "conflicts": [],
            "split": False,
        }
    environments: list[dict[str, Any]] = []
    used: set[str] = set()
    shared = [r for f, items in by_file.items() if f not in conflicting_files for r in items]
    for source in sorted(conflicting_files):
        base = _env_name(source)
        name = base
        n = 2
        while name in used:
            name = f"{base}-{n}"
            n += 1
        used.add(name)
        environments.append(
            {
                "name": name,
                "source_files": [source] + sorted(f for f in by_file if f not in conflicting_files),
                "requirements": rows(by_file[source] + shared),
            }
        )
    return {
        "environments": environments,
        "conflicts": [w.model_dump(mode="json") for w in warnings],
        "split": True,
    }
