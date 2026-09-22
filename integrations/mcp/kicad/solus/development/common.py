"""Shared operation boundary and deterministic planning, without registration."""

import json
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from solus.development.commit import commit_plan, read_schematic
from solus.development.models import DevelopmentError, Point, fingerprint, validate_fingerprint
from solus.development.plan import MutationPlan
from solus.workspace import WorkspaceNotConfiguredError, workspace_root
from solus.write.escaping import encode_kicad_string


def workspace() -> Path:
    try:
        return workspace_root()
    except WorkspaceNotConfiguredError as exc:
        raise DevelopmentError("path_escapes_workspace") from exc


def text(value: Any, maximum: int, *, allow_empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not value and not allow_empty)
        or any(ord(c) < 32 for c in value)
    ):
        raise DevelopmentError("unsupported_value")
    return value


def quoted(value: str) -> bytes:
    try:
        return encode_kicad_string(value)
    except ValueError as exc:
        raise DevelopmentError("unsupported_value") from exc


def reference(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", value):
        raise DevelopmentError("unsupported_value")
    return value


def rotation(value: Any) -> int:
    if type(value) is not int or value not in (0, 90, 180, 270):
        raise DevelopmentError("invalid_geometry")
    return value


def original_for(path: str, expected: str) -> bytes:
    validate_fingerprint(expected)
    data = read_schematic(workspace(), path)
    if fingerprint(data) != expected:
        raise DevelopmentError("stale_plan")
    return data


def entity_uuid(path: str, original: bytes | None, operation: dict[str, Any], role: str) -> str:
    canonical = json.dumps(operation, sort_keys=True, separators=(",", ":"), allow_nan=False)
    identity = json.dumps(
        [path, None if original is None else fingerprint(original), canonical, role]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "solus:kicad:" + identity))


def finish(plan: MutationPlan, dry_run: bool, created: list[dict[str, Any]]) -> dict[str, Any]:
    if type(dry_run) is not bool:
        raise DevelopmentError("unsupported_value")
    if not dry_run and plan.original != plan.proposed:
        commit_plan(workspace(), plan)
    return {
        "changed": plan.original != plan.proposed,
        "schematic_path": plan.path,
        "before_fingerprint": plan.before_fingerprint,
        "after_fingerprint": plan.after_fingerprint,
        "created": created,
        "dry_run": dry_run,
        "preview": plan.preview(),
    }


def format_number(number: float) -> str:
    """Preserve the validated number exactly, without exponent or precision loss."""
    encoded = format(Decimal(str(number)), "f")
    return encoded.rstrip("0").rstrip(".") if "." in encoded else encoded


def format_point(point: Point, separator: str = " ") -> str:
    return separator.join((format_number(point.x_mm), format_number(point.y_mm)))
