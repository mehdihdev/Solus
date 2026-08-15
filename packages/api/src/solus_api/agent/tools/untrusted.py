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


def _looks_entropic(value: str) -> bool:
    return (
        len(value) >= _ENTROPIC_MIN_LEN
        and _ENTROPIC_CHARSET.fullmatch(value) is not None
        and len(set(value)) >= _ENTROPIC_MIN_DISTINCT
    )


def redact_value(value: Any) -> Any:
    """Recursively redact secret-shaped content from an untrusted result before
    it is persisted or enters model context. Returns a new structure."""
    if isinstance(value, dict):
        return {
            key: (
                REDACTED if isinstance(key, str) and _SECRET_KEY.search(key) else redact_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str) and _looks_entropic(value):
        return REDACTED
    return value


_SECRET_ASSIGNMENT = re.compile(
    r"((?:token|secret|passw(?:or)?d|api[_-]?key|authorization|cookie|private[_-]?key|credential)"
    r"[A-Za-z0-9_-]*\s*[=:]\s*)(\S+)",
    re.IGNORECASE,
)


def redact_text(text: str) -> str:
    """Scalar redaction for untrusted free text (SEC-M3): secret-shaped
    `key=value`/`key: value` assignments and entropic tokens are masked before
    the text can reach model context or persistence."""
    masked = _SECRET_ASSIGNMENT.sub(lambda m: m.group(1) + REDACTED, text)
    tokens = [REDACTED if _looks_entropic(token) else token for token in masked.split(" ")]
    return " ".join(tokens)
