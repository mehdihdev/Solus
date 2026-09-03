"""SOLUSDEV-235 (ADR-035) — rail-icon SVG reduction to a path-only, theme-aware subset."""

from __future__ import annotations

import pytest
from fixtures.extensions import VALID_ICON_SVG
from solus_api.extensions.svg import SvgError, sanitize_svg, svg_problems

CAP = 16 * 1024


def _svg(body: str, root_attrs: str = "") -> bytes:
    head = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"{root_attrs}>'
    return f"{head}{body}</svg>".encode()


def test_valid_icon_round_trips_with_colours_rewritten_to_current_color() -> None:
    assert svg_problems(VALID_ICON_SVG, CAP) == []
    out = sanitize_svg(VALID_ICON_SVG, CAP)
    assert out.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert 'fill="currentColor"' in out
    assert 'stroke="currentColor"' in out
    assert "#fff" not in out
    assert 'fill="none"' in out, "none is not a colour and must survive"
    assert "<title>BOM</title>" in out
    assert '<path d="M4 4h16v16H4z"' in out
    assert "<?xml" not in out
    # The reduced output is itself valid input (idempotent).
    assert sanitize_svg(out.encode(), CAP) == out


def test_oversized_icon_is_rejected_before_parsing() -> None:
    data = _svg('<path d="M0 0h1"/>' * 2000)
    problems = svg_problems(data, 1024)
    assert problems == [f"exceeds {1024} bytes"]


@pytest.mark.parametrize(
    "data",
    [
        b'<!DOCTYPE svg [<!ENTITY x "y">]>' + _svg("&x;"),
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://x/svg11.dtd">' + _svg(""),
        b'<!ENTITY x "y">' + _svg(""),
        b"<!doctype svg>" + _svg(""),
    ],
)
def test_doctype_and_entities_are_rejected_on_sight(data: bytes) -> None:
    problems = svg_problems(data, CAP)
    assert problems and any("DOCTYPE" in p or "ENTITY" in p for p in problems), problems


def test_processing_instructions_other_than_the_xml_declaration_are_rejected() -> None:
    data = b'<?xml version="1.0"?><?xml-stylesheet href="evil.css"?>' + _svg("")
    assert any("processing instruction" in p for p in svg_problems(data, CAP))
    # The XML declaration alone is fine.
    assert svg_problems(b'<?xml version="1.0"?>' + _svg('<path d="M0 0"/>'), CAP) == []


@pytest.mark.parametrize(
    "body",
    [
        "<script>alert(1)</script>",
        '<image href="x.png"/>',
        '<use href="#a"/>',
        '<foreignObject><body xmlns="http://www.w3.org/1999/xhtml"/></foreignObject>',
        "<style>path{fill:red}</style>",
        '<a href="https://x"><path d="M0 0"/></a>',
        '<defs><filter id="f"/></defs>',
        "<text>hi</text>",
    ],
)
def test_elements_outside_the_allowlist_are_rejected(body: str) -> None:
    problems = svg_problems(_svg(body), CAP)
    assert problems and any("element" in p for p in problems), problems


@pytest.mark.parametrize(
    "attr",
    [
        'onload="alert(1)"',
        'onclick="x()"',
        'href="https://x"',
        'xlink:href="#x"',
        'style="fill:url(#g)"',
        'class="c"',
        'id="i"',
        'filter="url(#f)"',
        'mask="url(#m)"',
        'clip-path="url(#c)"',
        'version="1.1"',
        'data-x="1"',
    ],
)
def test_attributes_outside_the_allowlist_are_rejected(attr: str) -> None:
    problems = svg_problems(_svg(f'<path d="M0 0" {attr}/>'), CAP)
    assert problems and any("attribute" in p for p in problems), problems


def test_on_attributes_are_rejected_on_the_root_too() -> None:
    problems = svg_problems(_svg("", ' onload="alert(1)"'), CAP)
    assert any("onload" in p for p in problems), problems


@pytest.mark.parametrize(
    "value",
    ["url(#grad)", "url(https://x/y.svg#g)", "rgb(1,2,3)", "#ggg", "red;fill:url(#x)", ""],
)
def test_fill_and_stroke_values_are_plain_colours(value: str) -> None:
    for attr in ("fill", "stroke"):
        problems = svg_problems(_svg(f'<path d="M0 0" {attr}="{value}"/>'), CAP)
        assert problems and any(attr in p for p in problems), (attr, value, problems)


@pytest.mark.parametrize("value", ["none", "currentColor", "#abc", "#aabbcc", "#aabbccdd", "black"])
def test_accepted_colour_forms(value: str) -> None:
    assert svg_problems(_svg(f'<path d="M0 0" fill="{value}"/>'), CAP) == []


def test_root_must_be_svg_in_the_svg_namespace() -> None:
    assert any("root" in p for p in svg_problems(b"<g><path d='M0 0'/></g>", CAP))
    bad_ns = b'<svg xmlns="http://www.w3.org/1999/xhtml"><path d="M0 0"/></svg>'
    assert any("xmlns" in p for p in svg_problems(bad_ns, CAP))


def test_malformed_xml_is_a_problem_not_a_crash() -> None:
    problems = svg_problems(b"<svg><path d='M0 0'>", CAP)
    assert problems and any("malformed" in p for p in problems), problems
    assert svg_problems(b"\xff\xfe not xml", CAP)


def test_text_outside_title_is_dropped_and_comments_are_stripped() -> None:
    data = _svg('<!-- hi --> stray <path d="M0 0"/>')
    assert svg_problems(data, CAP) == []
    out = sanitize_svg(data, CAP)
    assert "stray" not in out and "<!--" not in out


def test_sanitize_raises_with_the_problems_when_invalid() -> None:
    with pytest.raises(SvgError) as exc:
        sanitize_svg(_svg("<script/>"), CAP)
    assert exc.value.problems == svg_problems(_svg("<script/>"), CAP)


def test_attribute_values_are_escaped_on_output() -> None:
    out = sanitize_svg(_svg('<title>a &lt; b</title><path d="M0 0 &quot;x&quot;"/>'), CAP)
    assert "a &lt; b" in out
    assert '"x"' not in out
