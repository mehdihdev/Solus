"""Per-project settings VALUES checked against a manifest's `[settings]` block
(SOLUSDEV-235 / ADR-035, docs/api/extensions.md §6.2–§6.3, schema invariant #3).

Pure functions: manifest + values in, dotted problem strings out — the same
`"settings.<key>: <message>"` style as `manifest_problems`, so the Store can
show them inline. Values are user input; nothing here executes or renders them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from solus_contracts.extension_manifest import ExtensionManifest, SettingField

#: Encoded size cap of one install's `settings` object (route plan §6.3).
SETTINGS_MAX_BYTES = 16 * 1024


def encoded_size(value: Any) -> int:
    """Byte length of the canonical JSON encoding (compact, sorted keys)."""
    return len(
        json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()
    )


def _type_ok(field: SettingField, value: Any) -> bool:
    if field.type == "boolean":
        return isinstance(value, bool)
    if field.type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


def _field_problem(field: SettingField, value: Any) -> str | None:
    if not _type_ok(field, value):
        return f"settings.{field.key}: must be a {field.type}"
    if field.type == "select" and value not in (field.options or []):
        return f"settings.{field.key}: must be one of {', '.join(field.options or [])}"
    if field.type == "number":
        if field.min is not None and value < field.min:
            return f"settings.{field.key}: must be >= {field.min}"
        if field.max is not None and value > field.max:
            return f"settings.{field.key}: must be <= {field.max}"
    return None


def validate_settings_values(manifest: ExtensionManifest, values: Mapping[str, Any]) -> list[str]:
    """Every problem with `values` against the manifest's declared fields —
    unknown key, wrong type, select outside options, number outside min/max.
    Empty when valid. Missing keys are NOT problems (defaults fill them)."""
    declared = {field.key: field for field in manifest.settings.fields}
    problems = [f"settings.{key}: unknown setting" for key in values if key not in declared]
    for key, field in declared.items():
        if key in values and (problem := _field_problem(field, values[key])) is not None:
            problems.append(problem)
    return problems


def settings_with_defaults(
    manifest: ExtensionManifest, values: Mapping[str, Any]
) -> dict[str, Any]:
    """`values` (already validated) completed with manifest defaults for the
    declared keys it omits; keys with neither a value nor a default are absent."""
    completed: dict[str, Any] = {}
    for field in manifest.settings.fields:
        if field.key in values:
            completed[field.key] = values[field.key]
        elif field.default is not None:
            completed[field.key] = field.default
    return completed


def coerce_settings(manifest: ExtensionManifest, values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the declared, type-valid entries of `values`, then fill defaults
    — the §6.2 seeding rule for a team policy's `default_settings`, and the
    re-pin rule for carrying an install's settings onto a new manifest."""
    declared = {field.key: field for field in manifest.settings.fields}
    kept = {
        key: value
        for key, value in values.items()
        if key in declared and _field_problem(declared[key], value) is None
    }
    return settings_with_defaults(manifest, kept)
