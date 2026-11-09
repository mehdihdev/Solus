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
import unicodedata
from typing import Any, Final, Literal

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

#: Provider-prefixed credentials, by their public shapes. Most are shorter than the entropy
#: floor above (an AWS access key id is 20 characters), so the length/charset heuristic never
#: sees them. A prefix must start a word: `disk-…` is not an OpenAI key. A denylist of shapes
#: sure enough to mask on sight is a floor under the heuristic, not a replacement for it.
_KEY_SHAPES: Final = (
    r"(?:AKIA|ASIA)[A-Z0-9]{16}"  # AWS access key id
    r"|sk-[A-Za-z0-9_-]{20,}"  # OpenAI
    r"|gh[pousr]_[A-Za-z0-9]{36,}"  # GitHub
    r"|glpat-[A-Za-z0-9_-]{20,}"  # GitLab
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"  # Slack
    r"|AIza[0-9A-Za-z_-]{35}"  # Google
    r"|[sr]k_(?:live|test)_[A-Za-z0-9]{20,}"  # Stripe
)
#: A PEM private key's header line — no word rule, so it is searched, never anchored (R162).
_PEM_HEADER: Final = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PROVIDER_KEY = re.compile(rf"(?<![A-Za-z0-9])(?:{_KEY_SHAPES})|{_PEM_HEADER.pattern}")
#: A key shape anchored at a raw word start (R160), tried beside the folded whole-form search
#: (R164): a fold such as `™` → `TM` would fail that search's word rule, so this one has none.
_KEY_AT: Final = re.compile(_KEY_SHAPES)


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


#: What a detector strips before it looks (M35): format characters (zero-width space and joiners),
#: combining marks (a grapheme joiner, a variation selector, an accent) and the blank fillers that
#: are letters or symbols to Unicode, so their category alone would keep them.
_INVISIBLE_CATEGORIES: Final = frozenset({"Cf", "Mn", "Me"})
_BLANK_FILLERS: Final = frozenset(map(chr, (0x115F, 0x1160, 0x3164, 0xFFA0, 0x2800)))


#: What a stripped code point becomes in the separated form: outside every detector's charset.
_SEPARATOR: Final = "\x1f"


def _judged_forms(value: str) -> tuple[str, ...]:
    """The forms the ENTROPY detector judges `value` in (M35, R154): the raw text; NFKD (a
    fullwidth letter is its ASCII one, an accent splits off its letter) with each invisible code
    point replaced by a separator; the same with the separators dropped; and NFKC with the
    invisibles dropped. A value is a secret when any form is; what is masked is always the
    original text. Provider-shaped keys go through `_names_provider_key` instead, which needs no
    separated form: it anchors a key at each raw word start (R160).

    ponytail (R165): the folded form is searched whole AND at raw word starts, so a fullwidth or
    math-styled word run straight into an ASCII key-shaped tail (`ｘｙｚ` + `sk-…`, `㎲k-…`) is
    masked — over-redaction, accepted: it errs toward masking. An ASCII letter or digit run
    straight into a key (`xAKIA…`) is not a key, on purpose — that is what spares `disk-…`."""
    if value.isascii():
        return (value,)
    separated = "".join(
        _SEPARATOR if _invisible(c) else c for c in unicodedata.normalize("NFKD", value)
    )
    composed = "".join(c for c in unicodedata.normalize("NFKC", value) if not _invisible(c))
    return (value, separated, separated.replace(_SEPARATOR, ""), composed)


def _invisible(c: str) -> bool:
    return c in _BLANK_FILLERS or unicodedata.category(c) in _INVISIBLE_CATEGORIES


_NORMAL_FORMS: Final[tuple[Literal["NFKD", "NFKC"], ...]] = ("NFKD", "NFKC")


def _names_provider_key(value: str) -> bool:
    """Whether `value` holds a provider-shaped key (R160): in the raw text, or — for NFKD and NFKC
    each — in the text folded and with every invisible deleted (so one inside a key cannot split
    it), found EITHER by the folded text's own word rule (R164: U+33B2 folds to `μs`, so `㎲k-…`
    is `sk-…` after a `μ`) OR anchored at a raw word start (R160: `™` folds to `TM`, and the
    folded word rule alone let that `M` merge into the key after it)."""
    if _PROVIDER_KEY.search(value):
        return True
    return not value.isascii() and any(
        _key_at_raw_word_start(value, form) for form in _NORMAL_FORMS
    )


def _key_at_raw_word_start(value: str, form: Literal["NFKD", "NFKC"]) -> bool:
    """Fold `value` one code point at a time (so each fold's offset is known), drop the invisibles,
    search the result whole, and also try a key at the start of every raw code point whose
    predecessor is not an ASCII letter or digit: the text's start, an invisible, an accent, a
    symbol — whatever its fold is."""
    kept: list[str] = []
    starts: list[int] = []
    previous = ""
    for c in value:
        if not (previous.isascii() and previous.isalnum()):
            starts.append(len(kept))
        kept.extend(n for n in unicodedata.normalize(form, c) if not _invisible(n))
        previous = c
    deleted = "".join(kept)
    return _PROVIDER_KEY.search(deleted) is not None or any(
        _KEY_AT.match(deleted, start) for start in starts
    )


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
    # Human-readable KiCad basenames can exceed the token length threshold.
    # Only a final lowercase word-separated filename gets this call-bound
    # display exception; opaque or secret-named components remain masked.
    if any(
        part in {"", ".", ".."}
        or part.strip() != part
        or re.fullmatch(r"[A-Za-z0-9_. -]+", part) is None
        or _SECRET_KEY.search(part)
        or (
            _looks_entropic(part)
            and not (
                index == len(parts) - 1
                and re.fullmatch(r"[a-z]{1,16}(?:_[a-z]{1,16}){2,8}\.kicad_(?:sch|pro|pcb)", part)
            )
        )
        for index, part in enumerate(parts)
    ):
        return None
    return value


def call_display_paths(tool_name: object, args: object) -> frozenset[str]:
    """Exact path arguments for known capabilities; never grants file access."""
    if not isinstance(args, dict) or not isinstance(tool_name, str):
        return frozenset()
    if tool_name in {"machine.read_file", "machine.write_file"}:
        key = "path"
    elif tool_name in {
        "kicad.create_schematic",
        "kicad.get_schematic_geometry",
        "kicad.add_symbol",
        "kicad.add_wire",
        "kicad.add_net_label",
        "kicad.mark_no_connect",
        "kicad.check_erc",
        "kicad.analyze_schematic_connections",
        "kicad.set_symbol_property",
    }:
        key = "schematic_path"
    else:
        return frozenset()
    path = safe_relative_display_path(args.get(key))
    return frozenset({path}) if path is not None else frozenset()


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
    if not isinstance(value, str):
        return value
    forms = _judged_forms(value)  # M35, R154: raw and invisibles-stripped
    if _names_provider_key(value):
        return REDACTED  # judged whole, like an entropic string: prose that carries a key goes
    if any(_looks_entropic(form) for form in forms):
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


def redact_text(text: str, *, allowed_paths: frozenset[str] = frozenset()) -> str:
    """Scalar redaction for untrusted free text (SEC-M3): secret-shaped
    `key=value`/`key: value` assignments and entropic tokens are masked before
    the text can reach model context or persistence.

    Tokens are split on ANY whitespace (a command's output is lines, not one
    space-separated line) and judged with their surrounding punctuation trimmed;
    a token that reads as a secret is replaced whole, punctuation included.
    """
    masked = _PROVIDER_KEY.sub(REDACTED, text)
    masked = _AUTHORIZATION.sub(lambda m: m.group(1) + REDACTED, masked)
    masked = _SECRET_ASSIGNMENT.sub(lambda m: m.group(1) + REDACTED, masked)
    parts = _WHITESPACE_SPLIT.split(masked)
    return "".join(REDACTED if _secret_token(part, allowed_paths) else part for part in parts)


def _secret_token(part: str, allowed_paths: frozenset[str]) -> bool:
    """Whether one whitespace-split token of `redact_text` reads as a secret, judged trimmed and
    in each of its judged forms (M35, R154); an allowed display path (the raw token) is spared."""
    if not part or part.isspace():
        return False
    tokens = [_trim(form) for form in _judged_forms(part)]
    if _names_provider_key(part):
        return True
    if not any(_looks_entropic(token) for token in tokens):
        return False
    raw = tokens[0]
    return not (raw in allowed_paths and safe_relative_display_path(raw) is not None)
