"""The panel page's XSS and framing posture — SOLUS-A7-01.

The panel token lives in this page's localStorage, so an XSS on it IS credential
theft. These pin the two properties that prevent it: nothing is rendered as
HTML, and nothing is loaded from a third party.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
from solus_api.routers.panel_assets import PANEL_CSS, PANEL_HTML, PANEL_JS


def test_the_script_never_assigns_raw_markup() -> None:
    """Part names are connector-ingested untrusted content. `textContent` is the
    only rendering path, and a single innerHTML would undo that."""
    assert "innerHTML" not in PANEL_JS
    assert "outerHTML" not in PANEL_JS
    assert "textContent" in PANEL_JS


def test_the_page_loads_nothing_from_a_third_party() -> None:
    """`default-src 'none'; script-src 'self'` would block it anyway; this keeps
    the page and the policy honest about each other."""
    for asset in (PANEL_HTML, PANEL_CSS, PANEL_JS):
        assert "http://" not in asset
        assert "https://" not in asset


def test_the_script_is_external_so_the_csp_needs_no_inline_hash() -> None:
    assert '<script src="/panel/app.js"></script>' in PANEL_HTML
    assert "<script>" not in PANEL_HTML.replace('<script src="/panel/app.js"></script>', "")


def test_the_onshape_user_id_is_never_sent_as_a_credential() -> None:
    """It may only key local storage. If it ever reached an Authorization
    header, the whole decision would be undone."""
    assert "'Bearer ' + t" in PANEL_JS or "'Bearer ' + deviceCode" in PANEL_JS
    assert "Bearer ' + onshapeUserId" not in PANEL_JS
    assert "storageKey = 'solus.panel.token.' + onshapeUserId" in PANEL_JS


def test_storage_failure_degrades_to_re_pairing_rather_than_crashing() -> None:
    """A cross-origin iframe may be denied localStorage entirely (Firefox strict
    mode, Safari ITP). Re-pairing each session is the correct degradation."""
    assert "try { localStorage.setItem" in PANEL_JS
    assert "try { return localStorage.getItem" in PANEL_JS


def test_nothing_inline_needs_unsafe_inline() -> None:
    """The CSP is `script-src 'self'; style-src 'self'` with no `'unsafe-inline'`
    and no hashes. An inline <style> or <script> would silently not render — and
    the fix would be to weaken the policy, which is the wrong direction."""
    assert "<style>" not in PANEL_HTML
    assert "style=" not in PANEL_HTML
    assert '<link rel="stylesheet" href="/panel/app.css">' in PANEL_HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_panel_script_actually_parses() -> None:
    """The other tests here grep for strings, which a syntax error survives —
    and this asset is a Python string literal, so no bundler or type-checker
    ever looks at it. A broken script renders a blank panel with the failure
    only in a browser console nobody is watching.
    """
    result = subprocess.run(  # noqa: S603 — fixed argv; the script arrives on stdin
        ["node", "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"],
        input=PANEL_JS.encode(),
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode()
