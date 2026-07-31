"""Shared untrusted-input gates for externally-advertised tools (CLAUDE.md §7).

Extracted from `mcp_tool.py` (MCP-01) so the bridge ingress (SOLUSDEV-154) can
apply the SAME gates to a companion's advertised inventory without importing the
`mcp` SDK — the reasoning layer's import graph must stay MCP-free.
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
