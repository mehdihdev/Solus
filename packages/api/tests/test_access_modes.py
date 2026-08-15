"""Connect-time access choice — read-only vs read+write (SOLUS-ONS-A2).

Editing CAD is the product, not a dangerous add-on, so the capability is offered
rather than withheld. But an OAuth grant is **account-wide** on Onshape (verified:
there is no per-document or per-project scope), so which powers Solus holds is a
decision the customer makes *at connect time* — not one we make for them.

Deliberately a GENERIC connector capability, exactly like `selection`: Fusion,
SolidWorks and AutoCAD need the same shape, and nothing in the frontend may
branch on a provider id.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from solus_api.connectors.contracts import OAuthConnector
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.onshape import ONSHAPE_OAUTH_BASE, OnshapeConnector


def _onshape() -> OnshapeConnector:
    return OnshapeConnector(client_id="cid", client_secret="sec")


# --------------------------------------------------------------- declaration


def test_onshape_declares_both_access_modes_with_read_as_the_default() -> None:
    modes = _onshape().access_modes

    assert modes is not None
    assert modes["default"] == "read"
    assert [m["id"] for m in modes["modes"]] == ["read", "write"]
    for mode in modes["modes"]:
        assert mode["label"] and mode["description"]


def test_the_write_mode_adds_edit_rights_and_nothing_else() -> None:
    """`OAuth2Delete` would let a confused agent destroy a customer's documents
    and workspaces, and buys nothing — feature and instance deletion are both
    `OAuth2Write`."""
    modes = {m["id"]: m for m in (_onshape().access_modes or {})["modes"]}

    assert modes["read"]["scopes"] == ["OAuth2Read"]
    assert modes["write"]["scopes"] == ["OAuth2Read", "OAuth2Write"]
    assert not any("Delete" in s for mode in modes.values() for s in mode["scopes"])


def test_a_connector_without_a_choice_declares_none() -> None:
    """The capability is optional — absent means "no choice to make", the same
    way `selection = None` means "nothing to pick"."""
    assert GitHubConnector(client_id="a", client_secret="b").access_modes is None


def test_the_base_class_defaults_to_no_choice() -> None:
    assert OAuthConnector.access_modes is None


# --------------------------------------------------------------- resolution


def test_scopes_for_resolves_the_named_mode() -> None:
    connector = _onshape()

    assert connector.scopes_for("read") == ("OAuth2Read",)
    assert connector.scopes_for("write") == ("OAuth2Read", "OAuth2Write")


def test_scopes_for_falls_back_to_the_declared_default() -> None:
    """An omitted choice must never silently widen: no mode means the DEFAULT
    mode, and the default is read."""
    connector = _onshape()

    assert connector.scopes_for(None) == ("OAuth2Read",)


def test_an_unknown_mode_is_refused_rather_than_defaulted() -> None:
    """Silently downgrading a typo'd mode would connect a source with powers the
    user did not choose — in either direction."""
    with pytest.raises(ValueError):
        _onshape().scopes_for("readwrite")


def test_a_connector_without_modes_ignores_the_argument() -> None:
    connector = GitHubConnector(client_id="a", client_secret="b")

    assert connector.scopes_for("write") == connector.scopes
    assert connector.scopes_for(None) == connector.scopes


# --------------------------------------------------------------- authorize url


def test_the_authorize_url_carries_the_chosen_scopes() -> None:
    url = _onshape().authorize_url(state="s", redirect_uri="http://localhost/cb", access="write")

    assert url.startswith(f"{ONSHAPE_OAUTH_BASE}/oauth/authorize?")
    assert "OAuth2Read+OAuth2Write" in url or "OAuth2Read%20OAuth2Write" in url


def test_the_authorize_url_defaults_to_read_only() -> None:
    url = _onshape().authorize_url(state="s", redirect_uri="http://localhost/cb")

    assert "OAuth2Write" not in url


# --------------------------------------------------------------- surfaced


async def test_the_catalog_surfaces_access_modes_verbatim(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """Declared metadata, surfaced as-is — so a new CAD connector becomes
    choosable by declaring it, with no route and no frontend change."""
    response = await client.get("/api/v1/integrations", headers=alice_headers)

    catalog = {entry["type"]: entry for entry in response.json()["data"]}
    assert "access_modes" in catalog["github"]
    assert catalog["github"]["access_modes"] is None
