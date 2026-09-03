"""Static content checks over an extension bundle (SOLUSDEV-235 / ADR-035).

The sandbox (ADR-035 §1) gives an extension no ``connect-src``, no remote
``script-src`` and no frames, so a bundle that tries any of those is not
compliant — and a reviewer should see WHICH line, not a CSP error in a user's
console later. These are regex checks over the text members (HTML, Markdown,
JS): fast, pure, and deliberately conservative; the CSP remains the real
boundary at runtime. Problems read ``"<path>:<line>: <message>"``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from solus_contracts.extension_manifest import ExtensionManifest

_REMOTE = r"""\s*=\s*["']?\s*(?:https?:|//)"""
_TAG_ATTRS = r"[^>]*?"


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    message: str


def _rule(pattern: str, message: str) -> _Rule:
    return _Rule(re.compile(pattern, re.IGNORECASE | re.DOTALL), message)


HTML_RULES: tuple[_Rule, ...] = (
    _rule(rf"<script{_TAG_ATTRS}\ssrc{_REMOTE}", "remote script (no remote script-src)"),
    _rule(rf"<link{_TAG_ATTRS}\shref{_REMOTE}", "remote stylesheet (no remote style-src)"),
    _rule(r"<iframe[\s>/]", "<iframe> is not allowed"),
    _rule(r"<base[\s>/]", "<base> is not allowed"),
    _rule(
        rf"<meta{_TAG_ATTRS}\shttp-equiv\s*=\s*[\"']?\s*content-security-policy",
        "<meta http-equiv=content-security-policy> is not allowed",
    ),
    _rule(rf"<form{_TAG_ATTRS}\saction{_REMOTE}", "remote form action"),
    _rule(r"<object[\s>/]", "<object> is not allowed"),
    _rule(r"<embed[\s>/]", "<embed> is not allowed"),
    _rule(
        r"""\s(?:href|src)\s*=\s*["']?\s*(?:https?:|//|javascript:|data:text/html)""",
        "href/src must be bundle-relative (no http:, https:, //, javascript:, data:text/html)",
    ),
)

MARKDOWN_RULES: tuple[_Rule, ...] = (
    _rule(r"<script[\s>/]", "<script is not allowed in Markdown"),
    _rule(r"<iframe[\s>/]", "<iframe is not allowed in Markdown"),
    _rule(r"javascript:", "javascript: links are not allowed"),
    _rule(r"<[a-z][^>]*?\son\w+\s*=", "on* event attributes are not allowed"),
)

_NO_CONNECT = " — the sandbox has no connect-src)"
JS_RULES: tuple[_Rule, ...] = (
    _rule(r"\bimportScripts\s*\(", "importScripts( is not allowed"),
    _rule(r"\bnew\s+Worker\s*\(", "new Worker( is not allowed"),
    _rule(r"\bnavigator\.serviceWorker\b", "navigator.serviceWorker is not allowed"),
    _rule(
        r"""\bimport\s*\(\s*["'`]\s*(?:https?:|//)""", "import( of a remote module is not allowed"
    ),
    _rule(r"\bfetch\s*\(", "direct network access (fetch()" + _NO_CONNECT),
    _rule(r"\bXMLHttpRequest\b", "direct network access (XMLHttpRequest" + _NO_CONNECT),
    _rule(r"\bWebSocket\s*\(", "direct network access (WebSocket(" + _NO_CONNECT),
    _rule(r"\bEventSource\s*\(", "direct network access (EventSource(" + _NO_CONNECT),
    _rule(r"\bsendBeacon\s*\(", "direct network access (sendBeacon(" + _NO_CONNECT),
)

_INLINE_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
_RULES_BY_SUFFIX: dict[str, tuple[_Rule, ...]] = {
    ".html": HTML_RULES,
    ".md": MARKDOWN_RULES,
    ".js": JS_RULES,
}


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _apply(path: str, text: str, rules: Iterable[_Rule], base_line: int = 0) -> list[str]:
    """One problem per offending span: a later (more generic) rule does not re-flag
    text an earlier rule already covered, so a remote <script src> reads once."""
    flagged: list[tuple[int, int]] = []
    problems: list[str] = []
    for rule in rules:
        for match in rule.pattern.finditer(text):
            start, end = match.span()
            if any(start < e and s < end for s, e in flagged):
                continue
            flagged.append((start, end))
            problems.append(f"{path}:{base_line + _line_of(text, start)}: {rule.message}")
    return problems


def _inline_script_problems(path: str, text: str) -> list[str]:
    problems: list[str] = []
    for match in _INLINE_SCRIPT_RE.finditer(text):
        base = _line_of(text, match.start(1)) - 1
        problems.extend(_apply(path, match.group(1), JS_RULES, base))
    return problems


def _check_file(path: str, data: bytes) -> list[str]:
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    rules = _RULES_BY_SUFFIX.get(suffix)
    if rules is None:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{path}:1: not valid UTF-8 text"]
    problems = _apply(path, text, rules)
    if suffix == ".html":
        problems.extend(_inline_script_problems(path, text))
    return problems


def _declared_entries(manifest: ExtensionManifest) -> list[str]:
    views = (manifest.views.widget, manifest.views.page, manifest.views.window)
    return [view.entry for view in views if view is not None]


def static_checks(manifest: ExtensionManifest, files: Mapping[str, bytes]) -> list[str]:
    """``"<path>:<line>: <message>"`` for every non-compliant line across the bundle's
    HTML, Markdown and JS members (declared entries first), sorted by path then line."""
    problems = [
        f"{entry}:1: declared entry is not in the bundle"
        for entry in _declared_entries(manifest)
        if entry not in files
    ]
    for path in sorted(files):
        problems.extend(_check_file(path, files[path]))
    return problems
