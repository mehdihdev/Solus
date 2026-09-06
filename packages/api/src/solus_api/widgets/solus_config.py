"""The repo-committed ``.solus/project.toml`` ``[ext.<id>]`` tables (SOLUSDEV-246,
ADR-034 Layer 2 + ADR-035 §4 as amended, widget-bundles.md §6).

Two pure-ish halves: :func:`parse_project_toml_ext` turns the file's TEXT into
the bounded ``{slug: {key: scalar}}`` map a connector lands as ONE
``solus_config`` graph entity (everything else in the file is ignored for now);
:func:`read_bundle_config` reads that entity back for one bundle and types the
values against the bundle's declared settings schema. The file is untrusted
input (CLAUDE.md §7; ADR-034 §5): strict caps, scalars only, never a secret,
never an instruction.
"""

from __future__ import annotations

import json
import re
import tomllib
import uuid
from typing import Any

from solus_contracts.extension_manifest import (
    EXTENSION_ID_PATTERN,
    SETTING_KEY_PATTERN,
    ExtensionManifest,
    SettingField,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.models import GraphEntity

SOLUS_CONFIG_KIND = "solus_config"
SOLUS_CONFIG_PATH = ".solus/project.toml"
MAX_PROJECT_TOML_BYTES = 64 * 1024
MAX_EXT_TABLES = 16
MAX_KEYS_PER_TABLE = 16
MAX_STRING_LEN = 4096
MAX_TABLE_BYTES = 4 * 1024

_SLUG_RE = re.compile(EXTENSION_ID_PATTERN)
_KEY_RE = re.compile(SETTING_KEY_PATTERN)
Scalar = bool | int | float | str


def _scalar(value: Any) -> Scalar | None:
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, str) and len(value) <= MAX_STRING_LEN:
        return value
    return None


def _table(slug: str, raw: Any, problems: list[str]) -> dict[str, Scalar] | None:
    if not isinstance(raw, dict):
        problems.append(f"{SOLUS_CONFIG_PATH}: [ext.{slug}] must be a table")
        return None
    if len(raw) > MAX_KEYS_PER_TABLE:
        problems.append(
            f"{SOLUS_CONFIG_PATH}: [ext.{slug}] has more than {MAX_KEYS_PER_TABLE} keys"
        )
        return None
    table: dict[str, Scalar] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _KEY_RE.match(key):
            problems.append(f"{SOLUS_CONFIG_PATH}: [ext.{slug}] key {key!r} is not a setting key")
            continue
        scalar = _scalar(value)
        if scalar is None:
            problems.append(f"{SOLUS_CONFIG_PATH}: [ext.{slug}].{key} must be a bounded scalar")
            continue
        table[key] = scalar
    if len(json.dumps(table).encode()) > MAX_TABLE_BYTES:
        problems.append(f"{SOLUS_CONFIG_PATH}: [ext.{slug}] exceeds {MAX_TABLE_BYTES} bytes")
        return None
    return table


def parse_project_toml_ext(text: str) -> tuple[dict[str, dict[str, Scalar]], list[str]]:
    """``[ext.<slug>]`` tables of a ``.solus/project.toml`` → ``({slug: table}, problems)``.

    Never raises. A file-level failure yields no tables and one problem; a bad
    table or key is dropped and named. Only ``[ext]`` is read (Ticket B's other
    tables are out of scope here)."""
    problems: list[str] = []
    if len(text.encode("utf-8")) > MAX_PROJECT_TOML_BYTES:
        return {}, [f"{SOLUS_CONFIG_PATH}: exceeds {MAX_PROJECT_TOML_BYTES} bytes"]
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return {}, [f"{SOLUS_CONFIG_PATH}: invalid TOML — {exc}"]
    ext = data.get("ext")
    if ext is None:
        return {}, []
    if not isinstance(ext, dict):
        return {}, [f"{SOLUS_CONFIG_PATH}: [ext] must be a table"]
    if len(ext) > MAX_EXT_TABLES:
        return {}, [f"{SOLUS_CONFIG_PATH}: [ext] has more than {MAX_EXT_TABLES} bundle tables"]
    tables: dict[str, dict[str, Scalar]] = {}
    for slug, raw in ext.items():
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            problems.append(f"{SOLUS_CONFIG_PATH}: [ext.{slug}] is not a bundle id")
            continue
        table = _table(slug, raw, problems)
        if table is not None:
            tables[slug] = table
    return tables, problems


def _typed(field: SettingField, value: Any) -> bool:
    if field.type == "boolean":
        return isinstance(value, bool)
    if field.type == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            return False
        low_ok = field.min is None or value >= field.min
        return low_ok and (field.max is None or value <= field.max)
    if field.type == "select":
        return isinstance(value, str) and value in (field.options or [])
    return isinstance(value, str)


def typed_subset(manifest: ExtensionManifest, table: dict[str, Any]) -> dict[str, Scalar]:
    """Only the keys the bundle declares, only when the value has the declared type."""
    return {
        field.key: table[field.key]
        for field in manifest.settings.fields
        if field.key in table and _typed(field, table[field.key])
    }


async def read_bundle_config(
    session: AsyncSession, project_id: uuid.UUID, slug: str, manifest: ExtensionManifest
) -> dict[str, Scalar]:
    """This bundle's ``[ext.<slug>]`` team defaults for one project, typed; ``{}``
    when the project has no committed config or none for this bundle."""
    row = await session.scalar(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == SOLUS_CONFIG_KIND,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.updated_at.desc())
        .limit(1)
    )
    if row is None or not isinstance(row.attrs, dict):
        return {}
    ext = row.attrs.get("ext")
    table = ext.get(slug) if isinstance(ext, dict) else None
    return typed_subset(manifest, table) if isinstance(table, dict) else {}
