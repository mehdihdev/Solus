"""Hosted (cloud-remote) MCP servers, authenticated as the CUSTOMER.

Every MCP server Solus spoke to before this ran on the customer's own machine:
a vendored stdio fork the companion launches, or a local app on loopback
(`test_mcp_license.py` asserts `is_loopback_url` for every `MCPServerSpec.url`,
and the companion refuses anything else — *"the companion only connects to MCP
servers on this machine"*). A vendor-hosted server is a different animal: it is
reached from the cloud, over the internet, with a token that identifies **the
customer**, never Solus.

`MCP_SERVER_CATALOG` is deliberately NOT the place for these. Its `url` field
means *loopback, on this machine* as a security invariant (CAD-02: a non-loopback
entry there would hand the companion an SSRF primitive inside the customer's
network). Hosted servers therefore get their own registry here, and the two
concepts stay separable.

**Adding the next hosted server is one entry in `HOSTED_SERVERS`.** Autodesk's
Fusion Data MCP and others are coming; if adding one requires editing this
module's logic rather than its data, the abstraction is wrong. That is why the
OAuth endpoints live here as literal fields rather than being discovered: see
`AUTH ENDPOINTS ARE PINNED` below.

**AUTH ENDPOINTS ARE PINNED, NOT DISCOVERED.** The `mcp` SDK's
`OAuthClientProvider` will, on any 401, fetch the URL it reads verbatim out of
the server's own `WWW-Authenticate: resource_metadata="…"` header and then trust
`authorization_servers[0]` from that document — steering Dynamic Client
Registration, the customer's browser and the token exchange at a host the
upstream vendor chooses (`mcp/client/auth/oauth2.py:518-528`, `utils.py:52-62`).
That is a blind SSRF out of the Solus cloud plus an authorization-server
substitution primitive. It also *rewrites the requested scope* from the
resource's advertised `scopes_supported` (`utils.py:119-121`), which for fs-mcp
would ask for `OAuth2Delete` and `OAuth2ReadPII` — forbidden on the record
(`connectors/onshape.py:239-243`: Delete *"would let a confused agent wipe a
customer's document"*). So the endpoints below were captured from a live spike
and are Solus data; nothing a server says can move them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from solus_api.models import SourceType


class RemoteAuth(Protocol):
    """Supplies the Authorization header for ONE customer, refreshing as needed.

    A protocol rather than a token string: a hosted server's token is short-lived
    (fs-mcp issues 3599s), so the value has to be resolved per invocation, not
    captured at wiring time.
    """

    async def headers(self) -> Mapping[str, str]:
        """Auth headers, or raise `RemoteAuthError` if unavailable."""
        ...


class RemoteAuthError(Exception):
    """The customer is not connected, not subscribed, or their grant expired.

    Carries a stable `code` and a message written for a HUMAN to act on — the
    brief's requirement that a failure names what is needed rather than being
    opaque. `MCPTool` turns this into `ToolResult(ok=False)`; it never escapes to
    the model as an exception.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


#: Built once per (server, source) at wiring time. Kept out of `RemoteMCPSpec` so
#: the spec stays pure data that a test can construct without a database.
AuthFactory = Callable[[], Awaitable[RemoteAuth]]


@dataclass(frozen=True)
class HostedTool:
    """One tool Solus has classified. DATA — the exposure allowlist entry.

    `consent` is per TOOL, not per server: one server-level sentence would assert
    a false effect for tools that do different things, and §7 requires the
    concrete action be shown. It is Solus-authored end to end — a hosted vendor
    phrases its own tool descriptions and those are untrusted input.
    """

    #: What a human reads before approving. Required for a mutating tool; unused
    #: (but harmless) on a read-only one.
    consent: str = ""
    #: Destructive or irreversible → the W0-04 confirmation gate. Solus-authored,
    #: NOT read from the server's own `destructiveHint`: the MCP SDK warns that
    #: annotations are untrusted, and this repo already ignores them everywhere.
    mutating: bool = False


@dataclass(frozen=True)
class RemoteMCPSpec:
    """One vendor-hosted MCP server. DATA — no behaviour, no credentials.

    **Exposure is allowlist-driven.** A discovered tool is registered only when
    it appears in `tools`; anything else is skipped with a warning, exactly like
    the stdio path does for a name missing from `allowlist.yaml`
    (`mcp_tool.py:350-353`). ADR-031: *"the tool namespace available to any SOL
    invocation is fixed cloud-side against the Solus-owned allowlist, never by
    what a machine advertises"* — admitting an unclassified tool and merely
    gating it would put a tool Solus has never seen behind a Solus-authored
    consent sentence, which is the same lie from the other direction.
    """

    name: str
    url: str
    #: The connector whose `Source` this rides on. A hosted server is never its
    #: own tile: it is an add-on to a connection the customer already made.
    source_type: SourceType
    #: What a human calls this add-on. The UI renders it generically, so the
    #: next hosted server needs no frontend change to be nameable.
    display_name: str = ""
    #: The exposure allowlist: remote tool name → its Solus-authored policy.
    tools: Mapping[str, HostedTool] = field(default_factory=dict)
    #: OAuth, pinned. See AUTH ENDPOINTS ARE PINNED in the module docstring.
    authorize_url: str = ""
    token_url: str = ""
    register_url: str = ""
    #: Exactly what we ask for and exactly what we accept back. A grant that
    #: comes back wider than this is an escalation and is REFUSED, not stored.
    scopes: tuple[str, ...] = ()
    #: Where a customer goes to subscribe. Programmatic subscription is verified
    #: impossible (the Onshape Billing guide's only path is a browser redirect
    #: scoped to the *calling app's own* products, and Solus is not the
    #: publisher), so this deep link plus a capability probe is the mechanism.
    subscribe_url: str | None = None
    #: Shown at connect time. Enabling a third-party app on someone's account is
    #: a trust cost even when free, so it is disclosed, not implied.
    connect_notice: str | None = None

    def exposes(self, remote_name: str) -> bool:
        """Whether a discovered tool may be registered at all (ADR-031)."""
        return remote_name in self.tools

    def requires_confirmation(self, remote_name: str) -> bool:
        """Fail closed: an unclassified name is never exposed, but if one ever
        reached here it is treated as mutating rather than as read-only."""
        entry = self.tools.get(remote_name)
        return True if entry is None else entry.mutating

    def consent_summary(self, remote_name: str) -> str:
        """The sentence a human approves. Solus-authored end to end."""
        entry = self.tools.get(remote_name)
        prose = entry.consent if entry is not None and entry.consent else f"Run `{self.name}`"
        return f"{prose} — `{remote_name}`"


#: Onshape Labs' hosted FeatureScript MCP server.
#:
#: The classification below was captured from a live `tools/list` against the
#: real server (v3.3.1) and is a SAFETY policy, not a schema: it decides what SOL
#: may call at all and which calls a human must approve. Tool DISCOVERY is still
#: live and never hardcoded — these names only classify what discovery returns,
#: and anything unrecognised is skipped.
#:
#: Two of the server's fourteen tools are deliberately ABSENT and therefore
#: unreachable: `logout` ends the customer's session on the server, and
#: `set_api_allocation` re-points which account is billed. SOL has no legitimate
#: reason to do either, and a tool that is never registered is the only gate that
#: cannot be bypassed.
FS_MCP = RemoteMCPSpec(
    name="onshape_fs",
    url="https://fs-mcp.labs.onshape.app/mcp",
    display_name="FeatureScript",
    source_type=SourceType.ONSHAPE,
    authorize_url="https://fs-mcp.labs.onshape.app/authorize",
    # noqa on the next line: S106 sees "token" in the NAME and assumes a
    # credential. This is the OAuth token ENDPOINT — a public URL from the
    # server's own discovery document. No secret appears in this file.
    token_url="https://fs-mcp.labs.onshape.app/token",  # noqa: S106
    register_url="https://fs-mcp.labs.onshape.app/register",
    # Read + Write only. `OAuth2Delete` and `OAuth2ReadPII` are forbidden on the
    # record; the live spike confirmed the server issues a token without them.
    scopes=("OAuth2Read", "OAuth2Write"),
    subscribe_url=("https://cad.onshape.com/appstore/apps/Onshape%20Labs/6a29aea7c03f8bf659841734"),
    tools={
        # ---- reads -------------------------------------------------------
        "whoami": HostedTool(),
        "get_api_usage": HostedTool(),
        "get_featurescript": HostedTool(),
        "list_feature_studios": HostedTool(),
        "read_featurescript_notes": HostedTool(),
        "search_featurescript_documentation": HostedTool(),
        "test_featurescript": HostedTool(),
        # ---- writes ------------------------------------------------------
        "put_featurescript": HostedTool(
            # The server's own description says it overwrites an ENTIRE Feature
            # Studio. The most destructive tool on the server.
            consent="Replace the whole contents of a Feature Studio in your Onshape document",
            mutating=True,
        ),
        "create_geometry": HostedTool(
            consent="Branch a workspace in your Onshape document and execute a feature in it",
            mutating=True,
        ),
        "create_feature_studio": HostedTool(
            consent="Create a new Feature Studio in your Onshape document",
            mutating=True,
        ),
        "test_feature": HostedTool(
            consent="Write a feature into a Feature Studio and evaluate it in a Part Studio",
            mutating=True,
        ),
        "edit_featurescript_notes": HostedTool(
            consent="Change the FeatureScript notes stored on your Onshape document",
            mutating=True,
        ),
    },
    connect_notice=(
        "Connecting Onshape also enables FeatureScript authoring through the "
        "Onshape Labs FeatureScript app on your account. It runs as you, using "
        "your own Onshape sign-in. Separate vendor service limits may apply; "
        "Solus does not assume an annual allocation for this hosted service. "
        "Disconnecting Solus leaves the app enabled — remove it from the Onshape "
        "App Store if you want it gone."
    ),
)

#: The whole registry. A new hosted server is an entry here and nothing else.
HOSTED_SERVERS: dict[str, RemoteMCPSpec] = {FS_MCP.name: FS_MCP}


def hosted_server(name: str) -> RemoteMCPSpec | None:
    """Look one up by name. Never build a spec from caller-supplied data."""
    return HOSTED_SERVERS.get(name)


__all__ = [
    "FS_MCP",
    "HOSTED_SERVERS",
    "AuthFactory",
    "HostedTool",
    "RemoteAuth",
    "RemoteAuthError",
    "RemoteMCPSpec",
    "hosted_server",
]
