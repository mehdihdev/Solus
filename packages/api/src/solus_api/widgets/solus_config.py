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
from typing import Any, NamedTuple

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


class ParsedExt(NamedTuple):
    """``[ext.<slug>]`` tables plus every problem; ``fatal`` means the FILE was
    unusable (not TOML / over the cap), as opposed to a dropped table or key."""

    tables: dict[str, dict[str, Scalar]]
    problems: list[str]
    fatal: bool = False


def _fatal(problem: str) -> ParsedExt:
    return ParsedExt({}, [problem], fatal=True)


def parse_project_toml_ext(text: str) -> ParsedExt:
    """``[ext.<slug>]`` tables of a ``.solus/project.toml``.

    Never raises. A file-level failure is ``fatal`` with one problem; a bad
    table or key is dropped and named. Only ``[ext]`` is read (Ticket B's other
    tables are out of scope here)."""
    problems: list[str] = []
    if len(text.encode("utf-8")) > MAX_PROJECT_TOML_BYTES:
        return _fatal(f"{SOLUS_CONFIG_PATH}: exceeds {MAX_PROJECT_TOML_BYTES} bytes")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return _fatal(f"{SOLUS_CONFIG_PATH}: invalid TOML — {exc}")
    ext = data.get("ext")
    if ext is None:
        return ParsedExt({}, [])
    if not isinstance(ext, dict):
        return _fatal(f"{SOLUS_CONFIG_PATH}: [ext] must be a table")
    if len(ext) > MAX_EXT_TABLES:
        return _fatal(f"{SOLUS_CONFIG_PATH}: [ext] has more than {MAX_EXT_TABLES} bundle tables")
    tables: dict[str, dict[str, Scalar]] = {}
    for slug, raw in ext.items():
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            problems.append(f"{SOLUS_CONFIG_PATH}: [ext.{slug}] is not a bundle id")
            continue
        table = _table(slug, raw, problems)
        if table is not None:
            tables[slug] = table
    return ParsedExt(tables, problems)


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
            # Only a CONNECTOR may land the repo's config; a bundle-written or
            # manual row of the same kind is never mistaken for it.
            GraphEntity.origin == "connector",
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


async def effective_bundle_config(
    session: AsyncSession, project_id: uuid.UUID, slug: str, manifest: ExtensionManifest
) -> dict[str, Scalar]:
    """What a bundle's backend should act on for this project (see
    :func:`merge_bundle_config` for the precedence)."""
    from solus_api.extensions import installs as svc  # function-local: no import cycle

    repo_defaults = await read_bundle_config(session, project_id, slug, manifest)
    extension = await svc.find_live_extension(session, slug)
    install = (
        await svc.get_install(session, project_id, extension.id) if extension is not None else None
    )
    settings = dict(install.settings) if install is not None else {}
    return merge_bundle_config(manifest, repo_defaults, settings)


def merge_bundle_config(
    manifest: ExtensionManifest,
    repo_defaults: dict[str, Any],
    install_settings: dict[str, Any],
) -> dict[str, Scalar]:
    """Effective per-project values: manifest defaults ← repo ``[ext.<slug>]``
    team defaults ← the install row's settings. Every layer is typed against
    the manifest; unknown keys never survive."""
    defaults = {f.key: f.default for f in manifest.settings.fields if f.default is not None}
    return {
        **typed_subset(manifest, defaults),
        **typed_subset(manifest, repo_defaults),
        **typed_subset(manifest, install_settings),
    }
