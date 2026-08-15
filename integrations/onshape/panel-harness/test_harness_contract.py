"""Contract tests for the Onshape panel harness (SOLUS-ONS-A7).

The harness is a single static page with no build step, so these are the only
thing standing between it and a well-meaning edit that quietly removes a guard.
Four properties, all of which a careless change would plausibly undo:

* every inbound message is checked against the `server` origin,
* every outbound post pins an explicit target origin (never a wildcard),
* nothing is posted at all when there is no origin to pin to,
* the substitution names are the current ones, not the deprecated `{$workspaceId}`.

Comments are stripped before matching. The page *discusses* the wildcard-origin
mistake at length, and the first version of this check passed on its own prose —
which is exactly the kind of false green worth designing out.
"""

from __future__ import annotations

import pathlib
import re

HARNESS = pathlib.Path(__file__).with_name("index.html")


def _executable_script() -> str:
    """The page's JS with comments removed, so prose cannot satisfy a check."""
    html = HARNESS.read_text(encoding="utf-8")
    body = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", line) for line in body.splitlines())


def test_the_stripper_does_not_leave_comment_text_behind() -> None:
    """Guard the guard: if this stops stripping, every test below goes false-green."""
    code = _executable_script()

    assert "the mistake this harness exists partly to avoid teaching" not in code


def test_inbound_messages_are_checked_against_the_declared_origin() -> None:
    """Without this the panel trusts any frame that can reach it."""
    assert "e.origin !== ctx.server" in _executable_script()


def test_outbound_posts_pin_an_explicit_target_origin() -> None:
    """A wildcard would broadcast the customer's document ids to whatever is
    hosting the frame."""
    code = _executable_script()

    assert "postMessage(message, ctx.server)" in code
    assert re.search(r"postMessage\([^)]*['\"]\*['\"]", code) is None


def test_nothing_is_posted_without_an_origin_to_validate_against() -> None:
    assert "if (!ctx.server) return" in _executable_script()


def test_the_current_substitution_names_are_used() -> None:
    """`{$workspaceId}` is deprecated; `{$workspaceOrVersionId}` replaces it.

    An element right panel receives NO document/workspace/element ids unless the
    action URL asks for them, so getting these names wrong yields a panel with
    no context and no error.
    """
    code = _executable_script()

    assert "workspaceOrVersionId" in code
    # Scoped to executable code: the page deliberately NAMES the deprecated
    # token in a warning comment, which is documentation rather than a defect.
    assert "{$workspaceId}" not in code
