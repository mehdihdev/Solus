"""The ONE `{slug}` validator for every extension route (SOLUSDEV-235 Phase 4
REV-MEDIUM; docs/api/extensions.md §3).

`{slug}` is the manifest `extension.id`, matched case-insensitively, so the
contract regex is applied to the lower-cased value and the lower-cased value is
what every lookup receives. The contract's reserved ids (`constructor`,
`__proto__`, `prototype`) are refused here too — a manifest can never carry
them, so a path naming one is garbage, not a lookup.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Depends
from solus_contracts.extension_manifest import EXTENSION_ID_PATTERN, RESERVED_EXTENSION_IDS

from solus_api.core.errors import APIError

_SLUG_RE = re.compile(EXTENSION_ID_PATTERN)


def validate_extension_slug(value: str) -> str:
    """Lower-case `value`; `422 validation_error` unless it matches the manifest
    id rule and is not a reserved id. Callers that must not leak a validation
    hint (attribution → `403 scope_denied`) catch and re-raise."""
    slug = value.lower()
    if not _SLUG_RE.fullmatch(slug) or slug in RESERVED_EXTENSION_IDS:
        raise APIError(422, "validation_error", "Invalid extension slug")
    return slug


def _slug_path(slug: str) -> str:
    return validate_extension_slug(slug)


#: Route-signature form: `slug: SlugPath` validates and normalizes the `{slug}`
#: path segment before the handler body runs.
SlugPath = Annotated[str, Depends(_slug_path)]

__all__ = ["SlugPath", "validate_extension_slug"]
