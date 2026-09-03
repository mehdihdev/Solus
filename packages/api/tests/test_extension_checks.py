"""SOLUSDEV-235 (ADR-035) — static content checks over bundle HTML / Markdown / JS."""

from __future__ import annotations

import pytest
from fixtures.extensions import CLEAN_HTML, CLEAN_JS, CLEAN_MD, MINIMAL_MANIFEST_TOML
from solus_api.extensions.checks import static_checks
from solus_api.extensions.manifest import load_manifest

MANIFEST = load_manifest(MINIMAL_MANIFEST_TOML)


def _check(path: str, content: str) -> list[str]:
    return static_checks(MANIFEST, {"widget.html": CLEAN_HTML, path: content.encode()})


def test_clean_bundle_has_no_problems() -> None:
    files = {"widget.html": CLEAN_HTML, "app.js": CLEAN_JS, "OVERVIEW.md": CLEAN_MD}
    assert static_checks(MANIFEST, files) == []


def test_declared_entry_missing_from_files_is_reported() -> None:
    problems = static_checks(MANIFEST, {"OVERVIEW.md": CLEAN_MD})
    assert problems == ["widget.html:1: declared entry is not in the bundle"]


@pytest.mark.parametrize(
    ("snippet", "needle"),
    [
        ('<script src="https://cdn.example/x.js"></script>', "remote script"),
        ("<script\n  src='//cdn.example/x.js'></script>", "remote script"),
        ('<link rel="stylesheet" href="http://x.example/a.css">', "remote stylesheet"),
        ('<iframe src="widget2.html"></iframe>', "iframe"),
        ('<base href="/">', "<base>"),
        (
            '<meta http-equiv="Content-Security-Policy" content="default-src *">',
            "content-security-policy",
        ),
        ('<form action="https://x.example/post">', "remote form"),
        ('<a href="https://x.example">x</a>', "href"),
        ('<img src="//x.example/a.png">', "src"),
        ('<a href="javascript:alert(1)">x</a>', "javascript:"),
        ('<a href="data:text/html,<script>1</script>">x</a>', "data:text/html"),
        ('<object data="x.swf"></object>', "<object>"),
        ('<embed src="x.pdf">', "<embed>"),
    ],
)
def test_html_rules(snippet: str, needle: str) -> None:
    html = "<!doctype html>\n<html><body>\n" + snippet + "\n</body></html>"
    problems = _check("page.html", html)
    assert problems, snippet
    assert all(p.startswith("page.html:3: ") for p in problems), problems
    assert any(needle.lower() in p.lower() for p in problems), problems


def test_html_line_numbers_point_at_the_offending_tag() -> None:
    html = "<!doctype html>\n<html>\n<body>\n\n\n<iframe></iframe>\n</body></html>"
    assert _check("page.html", html) == ["page.html:6: <iframe> is not allowed"]


def test_local_relative_urls_are_fine() -> None:
    html = (
        '<link rel="stylesheet" href="styles.css"><script src="./app.js"></script>'
        '<img src="shots/table.png"><a href="#top">top</a><form action="page.html">'
    )
    assert _check("page.html", html) == []


def test_inline_scripts_in_html_get_the_js_rules() -> None:
    html = "<html>\n<script>\nfetch('https://x.example')\n</script></html>"
    problems = _check("page.html", html)
    assert problems == [
        "page.html:3: direct network access (fetch() — the sandbox has no connect-src)"
    ]


@pytest.mark.parametrize(
    ("snippet", "needle"),
    [
        ("<script>alert(1)</script>", "<script"),
        ("<iframe src='x'></iframe>", "<iframe"),
        ("[click](javascript:alert(1))", "javascript:"),
        ('<a href="JAVASCRIPT:alert(1)">x</a>', "javascript:"),
        ('<img src="x.png" onerror="alert(1)">', "on"),
        ("<div onmouseover = 'x()'>", "on"),
    ],
)
def test_markdown_rules(snippet: str, needle: str) -> None:
    problems = _check("OVERVIEW.md", "# Title\n\n" + snippet + "\n")
    assert problems and all(p.startswith("OVERVIEW.md:3: ") for p in problems), problems
    assert any(needle.lower() in p.lower() for p in problems), problems


def test_markdown_prose_mentioning_on_words_is_fine() -> None:
    md = "# Guide\n\nTurn the option on = better. Click on <b>Run</b>.\n"
    assert _check("docs/HOW.md", md) == []


@pytest.mark.parametrize(
    ("snippet", "needle"),
    [
        ("importScripts('x.js')", "importScripts"),
        ("const w = new Worker('w.js')", "Worker"),
        ("navigator.serviceWorker.register('sw.js')", "serviceWorker"),
        ("import('https://cdn.example/m.js')", "import("),
        ('import ("http://cdn.example/m.js")', "import("),
        ("fetch('/api')", "fetch"),
        ("const x = new XMLHttpRequest()", "XMLHttpRequest"),
        ("new WebSocket('wss://x')", "WebSocket"),
        ("new EventSource('/e')", "EventSource"),
        ("navigator.sendBeacon('/b', d)", "sendBeacon"),
    ],
)
def test_js_rules(snippet: str, needle: str) -> None:
    problems = _check("app.js", "'use strict';\n\n" + snippet + "\n")
    assert problems and all(p.startswith("app.js:3: ") for p in problems), problems
    assert any(needle in p for p in problems), problems


def test_local_dynamic_import_and_message_passing_are_fine() -> None:
    js = "const m = await import('./mod.js');\nparent.postMessage({ok: true}, '*');\n"
    assert _check("app.js", js) == []


def test_non_utf8_text_files_are_reported() -> None:
    problems = static_checks(MANIFEST, {"widget.html": CLEAN_HTML, "app.js": b"\xff\xfe\x00bad"})
    assert problems == ["app.js:1: not valid UTF-8 text"]


def test_unrelated_file_types_are_not_scanned() -> None:
    files = {
        "widget.html": CLEAN_HTML,
        "styles.css": b"a{background:url(https://x)}",
        "d.json": b"{}",
    }
    assert static_checks(MANIFEST, files) == []


def test_each_problem_is_reported_once_per_line() -> None:
    problems = _check("page.html", '<script src="https://cdn.example/x.js"></script>')
    assert len(problems) == 1, problems
