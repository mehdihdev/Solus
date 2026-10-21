"""The hosted-server registry is DATA, and its data is a security policy.

`remote_mcp.HOSTED_SERVERS` decides three things no code path may override: which
vendor hosts Solus will speak to from the cloud, which of a server's advertised
tools SOL may call at all, and which scopes the customer's browser is asked to
grant. Each is pinned here by a test so a future edit to the table has to argue
with CI rather than with a reviewer's memory.
"""

from urllib.parse import urlsplit

from solus_api.agent.tools.remote_mcp import (
    FS_MCP,
    HOSTED_SERVERS,
    HostedTool,
    RemoteMCPSpec,
    hosted_server,
)
from solus_api.models import SourceType

#: The mirror image of `test_mcp_license.test_vendor_run_specs_are_loopback_only`.
#: There, a url means loopback-on-the-customer's-machine; here it means a vendor's
#: cloud — so the guard inverts: https only, and only hosts we have reviewed.
ALLOWED_HOSTS = frozenset({"fs-mcp.labs.onshape.app", "mcp-auth.labs.onshape.app"})


def test_every_hosted_url_is_https_on_a_reviewed_host() -> None:
    """The registry IS the outbound allowlist. There is no other SSRF guard on
    the API's outbound path (`grep -rn "ssrf" packages/api/src` finds only the
    prose in this module), so a plaintext or unreviewed host would be one edit
    away from a request the cloud makes on a vendor's say-so."""
    for spec in HOSTED_SERVERS.values():
        for label, url in (
            ("url", spec.url),
            ("authorize_url", spec.authorize_url),
            ("token_url", spec.token_url),
            ("register_url", spec.register_url),
            ("resource", spec.resource),
        ):
            parts = urlsplit(url)
            assert parts.scheme == "https", f"{spec.name}.{label} is not https: {url}"
            assert parts.hostname in ALLOWED_HOSTS, f"{spec.name}.{label} host {parts.hostname}"


def test_fs_mcp_oauth_endpoints_are_pinned_to_onshapes_auth_host() -> None:
    """Onshape split fs-mcp's authorization server onto its own host: the
    resource's metadata now names `mcp-auth.labs.onshape.app`, and fs-mcp's own
    `/authorize` answers 404. Pinned here, never discovered (ADR §4)."""
    assert urlsplit(FS_MCP.url).hostname == "fs-mcp.labs.onshape.app"
    assert FS_MCP.authorize_url == "https://mcp-auth.labs.onshape.app/authorize"
    assert FS_MCP.token_url == "https://mcp-auth.labs.onshape.app/token"  # noqa: S105
    assert FS_MCP.register_url == "https://mcp-auth.labs.onshape.app/register"
    # RFC 8707: the auth host refuses an authorize request without it. This is
    # the `resource` fs-mcp's protected-resource metadata advertises.
    assert FS_MCP.resource == "https://fs-mcp.labs.onshape.app"


def test_fs_mcp_never_requests_delete_or_pii() -> None:
    """`OAuth2Delete` and `OAuth2ReadPII` are forbidden on the record
    (`connectors/onshape.py:239-243`). fs-mcp's protected-resource metadata
    advertises all four scopes, and the MCP SDK would have asked for all four —
    the whole reason the endpoints are pinned instead of discovered."""
    assert FS_MCP.scopes == ("OAuth2Read", "OAuth2Write")


def test_session_ending_and_billing_tools_are_not_exposed_at_all() -> None:
    """`logout` ends the customer's session and `set_api_allocation` re-points
    which account is billed. Neither is something SOL should be able to propose,
    and a tool that is never registered is the only gate with no bypass."""
    assert not FS_MCP.exposes("logout")
    assert not FS_MCP.exposes("set_api_allocation")


def test_unclassified_tools_are_not_exposed_and_would_gate_as_mutating() -> None:
    """ADR-031: the tool namespace is fixed cloud-side against the Solus-owned
    allowlist, never by what a server advertises. A tool the vendor adds between
    releases is skipped — and if one ever reached the gate anyway it is treated
    as mutating, never as a read."""
    assert not FS_MCP.exposes("delete_everything")
    assert FS_MCP.requires_confirmation("delete_everything") is True


def test_every_mutating_tool_carries_its_own_consent_sentence() -> None:
    """§7 requires the CONCRETE action be shown. A single server-level prefix
    would assert the same effect for every tool, which is false the moment two
    mutating tools do different things."""
    sentences: set[str] = set()
    for spec in HOSTED_SERVERS.values():
        for name, entry in spec.tools.items():
            if not entry.mutating:
                continue
            assert entry.consent, f"{spec.name}.{name} is mutating with no consent text"
            summary = spec.consent_summary(name)
            assert name in summary
            sentences.add(summary)
    # Distinct tools must not read as the same action.
    assert len(sentences) == sum(
        1 for spec in HOSTED_SERVERS.values() for e in spec.tools.values() if e.mutating
    )


def test_put_featurescript_is_gated_and_reads_are_not() -> None:
    assert FS_MCP.requires_confirmation("put_featurescript") is True
    assert FS_MCP.requires_confirmation("get_featurescript") is False


def test_a_hosted_server_rides_an_existing_source_type_not_its_own_tile() -> None:
    """The brief: FeatureScript is part of Onshape, never a separate tile."""
    assert FS_MCP.source_type is SourceType.ONSHAPE
    for spec in HOSTED_SERVERS.values():
        assert isinstance(spec.source_type, SourceType)


def test_lookup_never_builds_a_spec_from_caller_data() -> None:
    assert hosted_server("onshape_fs") is FS_MCP
    assert hosted_server("../../etc/passwd") is None
    assert hosted_server("") is None


def test_a_new_hosted_server_is_data_only() -> None:
    """The generalisation claim, pinned: a second server needs no new logic —
    constructing one and asking it the three policy questions must just work."""
    other = RemoteMCPSpec(
        name="vendor_x",
        url="https://x.example/mcp",
        source_type=SourceType.GITHUB,
        tools={
            "read_thing": HostedTool(),
            "wreck_thing": HostedTool(consent="Wreck", mutating=True),
        },
    )
    assert other.exposes("read_thing")
    assert not other.exposes("undeclared")
    assert other.requires_confirmation("wreck_thing") is True
    assert other.consent_summary("wreck_thing") == "Wreck — `wreck_thing`"
    # A read-only tool with no consent text still gets a Solus-authored sentence.
    assert other.consent_summary("read_thing") == "Run `vendor_x` — `read_thing`"


def test_connect_notice_does_not_claim_a_customer_annual_api_allocation() -> None:
    assert FS_MCP.connect_notice is not None
    assert "consumes your account's API allocation" not in FS_MCP.connect_notice
    assert "service limits" in FS_MCP.connect_notice
