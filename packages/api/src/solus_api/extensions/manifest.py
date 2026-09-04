"""``extension.toml`` TEXT → contract (SOLUSDEV-235 / ADR-035).

The contract (``solus_contracts.extension_manifest``) validates the DECODED
object so JSON fixtures and API bodies share one parser; this module is the
thin text layer the bundle validator, the ARQ review job and a future CLI use
to get from TOML bytes to that object — bounded, and with TOML syntax errors
reported in the same ``"<path>: <message>"`` shape as contract problems.
Pure: no I/O, no framework.
"""

from __future__ import annotations

import tomllib
from typing import Any

from solus_contracts.extension_manifest import (
    EXTENSION_MANIFEST_FILENAME,
    ExtensionManifest,
    manifest_problems,
    parse_extension_manifest,
)

#: Manifests are a page of declarations; 64 KiB is orders of magnitude over any
#: legitimate one and keeps the TOML parser off attacker-sized input.
MANIFEST_TEXT_MAX_BYTES = 64 * 1024


class ManifestError(ValueError):
    """Raised by :func:`load_manifest`; ``problems`` is what the validator stores."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _decode(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """TOML text → decoded object, or the single problem that stopped decoding."""
    size = len(text.encode("utf-8"))
    if size > MANIFEST_TEXT_MAX_BYTES:
        return None, [
            f"{EXTENSION_MANIFEST_FILENAME}: exceeds {MANIFEST_TEXT_MAX_BYTES} bytes ({size})"
        ]
    if not text.strip():
        return None, [f"{EXTENSION_MANIFEST_FILENAME}: file is empty"]
    try:
        return tomllib.loads(text), []
    except tomllib.TOMLDecodeError as exc:
        return None, [f"{EXTENSION_MANIFEST_FILENAME}: invalid TOML — {exc}"]


def manifest_text_problems(text: str) -> list[str]:
    """Every problem with the manifest TEXT: cap, TOML syntax, then contract problems."""
    data, problems = _decode(text)
    if data is None:
        return problems
    return manifest_problems(data)


def load_manifest(text: str) -> ExtensionManifest:
    """Strictly parse manifest text; raises :class:`ManifestError` listing every problem."""
    data, problems = _decode(text)
    if data is None:
        raise ManifestError(problems)
    problems = manifest_problems(data)
    if problems:
        raise ManifestError(problems)
    return parse_extension_manifest(data)
