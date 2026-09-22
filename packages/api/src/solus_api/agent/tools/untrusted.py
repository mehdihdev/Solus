"""Shared untrusted-input gates for externally-advertised tools (CLAUDE.md §7).

Extracted from `mcp_tool.py` (MCP-01) so the bridge ingress (SOLUSDEV-154) can
apply the SAME gates to a companion's advertised inventory without importing the
`mcp` SDK — the reasoning layer's import graph must stay MCP-free.

Redaction (SOLUS-RUN-01): ONE gate for every untrusted result — bridge frame or
agent tool result alike (`onshape.get_variables` returns raw Onshape variables,
so a variable named `api_key` holding a token would otherwise go straight into
model context and into the persisted turn). The implementation lives HERE and
`bridge/frames.py` re-exports it, so its own callers are unchanged. LANE C
carried the pre-SOLUSDEV-60 direction (implementation in `frames.py`, this
module re-exporting); the SOLUSDEV-68 merge flipped it back, which is the flip
this docstring always anticipated. Keep exactly one implementation: making both
modules re-export from each other is an import cycle, not a re-export.
"""

import json
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

# Server-authored text (tool descriptions, error text) is UNTRUSTED ingested
# content — length-cap it before it reaches a descriptor or an error message
# the model will read.
UNTRUSTED_TEXT_CAP = 500
# Remote tool names become descriptor names the model reads — constrain them to
# a safe shape instead of trusting server-authored text.
SAFE_REMOTE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")
# A server-authored JSON Schema is untrusted too: bound its serialized size so a
# schema-bomb can't bloat the model context or the registry.
SCHEMA_BYTES_CAP = 64_000


def contains_ref(node: object) -> bool:
    if isinstance(node, dict):
        return any(key == "$ref" or contains_ref(value) for key, value in node.items())
    if isinstance(node, list):
        return any(contains_ref(item) for item in node)
    return False


def schema_oversized(schema: dict[str, Any]) -> bool:
    try:
        return len(json.dumps(schema)) > SCHEMA_BYTES_CAP
    except (TypeError, ValueError):
        return True  # unserializable ⇒ not a schema we accept


def unsafe_schema_reason(schema: dict[str, Any]) -> str | None:
    """Why an advertised input schema is rejected, or None if it passes.

    A `$ref` passes `check_schema` yet explodes at VALIDATION time (unresolvable
    reference) — rejecting it keeps a foreign schema from ever breaking the
    registry's never-raises path.
    """
    if schema_oversized(schema):
        return "advertises an oversized schema"
    if contains_ref(schema):
        return "advertises a $ref-bearing input schema"
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return "advertises a malformed input schema"
    return None


# --------------------------------------------------------------- redaction
#
# Moved here from `bridge/frames.py` (SOLUS-RUN-01). It guarded only the bridge
# path, but a tool RESULT is the same kind of untrusted content wherever it came
# from: `onshape.get_variables` returns raw Onshape variables, so a variable
# named `api_key` holding a token would otherwise go straight into model context
# and into the persisted turn. Both sides import it from here; `bridge/frames.py`
# re-exports so its own callers are unchanged.

_SECRET_KEY = re.compile(
    r"token|secret|passw(or)?d|api[_-]?key|authorization|cookie|private[_-]?key|credential",
    re.IGNORECASE,
)
_ENTROPIC_CHARSET = re.compile(r"^[A-Za-z0-9+/=_.-]+$")
# ponytail: length/charset/distinct-chars heuristic — ≥40 spares uuid4().hex
# call-id-shaped values; a base64 secret under 40 chars slips through. Tighten
# with a real detector (e.g. detect-secrets) if field data shows leaks.
_ENTROPIC_MIN_LEN = 40
_ENTROPIC_MIN_DISTINCT = 16

REDACTED = "[REDACTED]"


#: Path-shaped values are judged per SEGMENT rather than whole. A long absolute
#: path clears every bar the heuristic sets — the separator is inside the
#: charset, and enough directory names make it long and varied — so whole paths
#: were being redacted. That is not a cosmetic loss: the consent card renders
#: `cwd` and `path` rows from the companion's dry-run plan, and a card that says
#: the command runs in "[REDACTED]" cannot be consented to (SOLUSDEV-252, found
#: live approving `machine.run_command`). Segments keep the detector honest — a
#: key sitting in a path component is still one long high-entropy token.
# ponytail: ANCHORED to an absolute / `~` / `./` / drive prefix, so a long
# RELATIVE path (a deep workspace-relative one on a consent card) is still
# judged whole and can still redact. Widening this to "contains a separator"
# would exempt any slash-bearing blob, which is the bigger hole; the upgrade
# path is a real secret detector, not a looser shape rule.
_PATH_PREFIX = re.compile(r"^(?:[A-Za-z]:[\\/]|~[\\/]|\.{1,2}[\\/]|[\\/])")
_PATH_SEPARATOR = re.compile(r"[\\/]")
_BASE64_ONLY = re.compile(r"[+=]")


def _entropic_token(value: str) -> bool:
    return (
        len(value) >= _ENTROPIC_MIN_LEN
        and _ENTROPIC_CHARSET.fullmatch(value) is not None
        and len(set(value)) >= _ENTROPIC_MIN_DISTINCT
    )


def _looks_entropic(value: str) -> bool:
    # `+` and `=` never appear in a path we would want to spare, and both are
    # base64: a blob that merely STARTS with `/` gets judged whole, so the
    # per-segment relaxation cannot become an escape hatch for one.
    if _PATH_PREFIX.match(value) and not _BASE64_ONLY.search(value):
        return any(_entropic_token(part) for part in _PATH_SEPARATOR.split(value))
    return _entropic_token(value)


def safe_relative_display_path(value: object) -> str | None:
    """A conservative display exception, not filesystem access authorization."""
    if not isinstance(value, str) or not 1 <= len(value) <= 400:
        return None
    parts = value.split("/")
    if not 2 <= len(parts) <= 32:
        return None
    if any(
        part in {"", ".", ".."}
        or part.strip() != part
        or re.fullmatch(r"[A-Za-z0-9_. -]+", part) is None
        or _SECRET_KEY.search(part)
        or _looks_entropic(part)
        for part in parts
    ):
        return None
    return value


def redact_value(value: Any, *, allowed_paths: frozenset[str] = frozenset()) -> Any:
    """Redact untrusted values; exact validated call-bound display paths may survive.

    Sensitive key names always win. Callers without explicit context retain the
    original detector, including its treatment of arbitrary slash-bearing blobs.
    """
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and _SECRET_KEY.search(key)
                else redact_value(item, allowed_paths=allowed_paths)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, allowed_paths=allowed_paths) for item in value]
    if isinstance(value, str) and _looks_entropic(value):
        if value in allowed_paths and safe_relative_display_path(value) is not None:
            return value
        return REDACTED
    return value


_SECRET_ASSIGNMENT = re.compile(
    r"((?:token|secret|passw(?:or)?d|api[_-]?key|authorization|cookie|private[_-]?key|credential)"
    r"[A-Za-z0-9_-]*\s*[=:]\s*)(\S+)",
    re.IGNORECASE,
)
_AUTHORIZATION = re.compile(r"(authorization\s*[=:]\s*)(?:Bearer|Basic)\s+\S+", re.IGNORECASE)


#: The charset as a SET, for `_trim`. Quotes, brackets and sentence punctuation
#: around a token hid secrets from the old space-split scan — `\'ghp_…\'` and any
#: newline-joined token went unexamined, and a shell trace or a JSON error is
#: exactly where a secret sits next to punctuation.
_CHARSET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=_.-")
_WHITESPACE_SPLIT = re.compile(r"(\s+)")


def _trim(token: str) -> str:
    """Drop leading and trailing characters outside the charset.

    Two pointers, not the obvious `re.sub(r"^[^C]+|[^C]+$", ...)`: that pattern
    backtracks from every start position, measuring 0.7 s on a 16 KB unbroken
    non-charset run and growing quadratically — and this runs over the whole
    output of a failing command, so a CJK build log or a progress bar would block
    the event loop for minutes.
    """
    start, end = 0, len(token)
    while start < end and token[start] not in _CHARSET:
        start += 1
    while end > start and token[end - 1] not in _CHARSET:
        end -= 1
    return token[start:end]


def redact_text(text: str) -> str:
    """Scalar redaction for untrusted free text (SEC-M3): secret-shaped
    `key=value`/`key: value` assignments and entropic tokens are masked before
    the text can reach model context or persistence.

    Tokens are split on ANY whitespace (a command's output is lines, not one
    space-separated line) and judged with their surrounding punctuation trimmed;
    a token that reads as a secret is replaced whole, punctuation included.
    """
    masked = _AUTHORIZATION.sub(lambda m: m.group(1) + REDACTED, text)
    masked = _SECRET_ASSIGNMENT.sub(lambda m: m.group(1) + REDACTED, masked)
    parts = _WHITESPACE_SPLIT.split(masked)
    return "".join(
        REDACTED if part and not part.isspace() and _looks_entropic(_trim(part)) else part
        for part in parts
    )
