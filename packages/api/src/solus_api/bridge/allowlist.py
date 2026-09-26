"""The Solus-owned tool allowlist and the hello-inventory gate (ADR-031).

`allowlist.yaml` (one per fork under `integrations/mcp/<tool>/`) is the single
source of truth for which tools a companion may expose and which carry the
confirmation gate. Everything a companion ADVERTISES is untrusted input: the
tool namespace available to any SOL invocation is fixed cloud-side against this
allowlist, never by what a machine advertises. Failing entries are skipped with
a warning — one bad advertised tool never kills registration (same posture as
`discover_mcp_tools`).
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from solus_api.agent.tools.shapes import ToolDescriptor
from solus_api.agent.tools.untrusted import (
    SAFE_REMOTE_NAME,
    UNTRUSTED_TEXT_CAP,
    schema_oversized,
    unsafe_schema_reason,
)
from solus_api.bridge.frames import HelloData, HelloTool

logger = logging.getLogger("solus.bridge.allowlist")

# Fork/server names per integrations/mcp/README.md: no dots (the dot is the
# {server}.{tool} separator), 32 chars max.
SERVER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
COMPOSED_NAME_MAX = 128
_ANY_OBJECT_RETURNS: dict[str, Any] = {"type": "object"}

#: Composed names whose companion implementation advertises `dry_run` and
#: answers it with the resolved plan instead of running it
#: (packages/companion/src/solus_companion/machine/server.py). Solus-owned, like
#: `requires_confirmation`.
_COMPLETE_PREVIEW_TOOLS: Final = frozenset(
    {
        "kicad.create_schematic",
        "kicad.add_symbol",
        "kicad.add_wire",
        "kicad.add_net_label",
        "kicad.mark_no_connect",
        "kicad.set_symbol_property",
        "code.git_commit",
        "code.git_push",
        "code.arduino_prepare",
        "code.arduino_compile",
        "code.arduino_upload",
        "isaac.start",
        "isaac.stop",
        "isaac.load_model",
        "isaac.set_joint_limits",
        "isaac.set_sensor_pose",
        "isaac.run_routine",
    }
)
_DRY_RUN_TOOLS: Final = _COMPLETE_PREVIEW_TOOLS | frozenset(
    {"machine.run_command", "machine.install_package", "machine.create_environment"}
)


def requires_complete_preview(composed_name: str) -> bool:
    """Solus-owned policy: argument-only approval cannot authorize these writes."""
    return composed_name in _COMPLETE_PREVIEW_TOOLS


def supports_dry_run(composed_name: str) -> bool:
    """Whether `{server}.{tool}` may be previewed by re-issuing it with
    `dry_run: true`."""
    return composed_name in _DRY_RUN_TOOLS


class AllowedTool(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    requires_confirmation: bool = False
    reason: str | None = None  # required on destructive entries (README rule)
    # SOLUSDEV-250 security review M5: a tool that legitimately runs longer
    # than the registry's default dispatch bound (a pip install, a test run)
    # declares its own bound HERE, in the Solus-owned allowlist — never from
    # the fork's advertised schema. It must exceed the fork's own cap so the
    # cloud never reports TIMEOUT while the child keeps running.
    timeout_seconds: int | None = Field(default=None, ge=1, le=900)
    #: SOLUSDEV-252 S5: a failing call is filed into `.solus` Error logging
    #: automatically. Solus-authored here, never advertised by the companion.
    files_errors: bool = False
    #: The tool accepts `dry_run: true` and returns the resolved plan WITHOUT
    #: executing, so the consent card can show the argv/path that will really
    #: run (bridge/tool.py::BridgeTool). Overwritten from `_DRY_RUN_TOOLS` at
    #: load: it states what the IMPLEMENTATION accepts, so a yaml (or a fork)
    #: can never opt a tool into being called with an argument it does not
    #: advertise.
    supports_dry_run: bool = False

    @model_validator(mode="after")
    def _destructive_needs_reason(self) -> Self:
        if self.requires_confirmation and not self.reason:
            raise ValueError("a destructive (requires_confirmation) entry must carry a reason")
        return self


class ServerAllowlist(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    server: str
    #: A VENDOR-RUN MCP server on the customer's machine (CAD-02: Autodesk's
    #: Fusion server at 127.0.0.1:27182), rather than a vendored fork the
    #: companion launches. The cloud never dials it — the companion does — but
    #: the field must exist here: this model is `extra="forbid"`, so an
    #: allowlist carrying `url:` without it would fail validation and the whole
    #: server would register with ZERO tools, silently.
    url: str | None = None
    #: WHO starts this server. `companion` (the default) is a vendored fork the
    #: companion launches from `bin/launch`. `cloud` is a fork the API spawns
    #: itself — the companion must not try, and would only fail noisily (the
    #: brave fork needs Node, which the companion does not ship). `builtin` is a
    #: server the companion implements natively, so there is no launcher to find.
    #: Declared here because this file is the single source of truth for a
    #: server, and because both readers are `extra="forbid"`.
    launched_by: Literal["companion", "cloud", "builtin"] = "companion"
    tools: tuple[AllowedTool, ...] = ()


@dataclass(frozen=True)
class BridgeAllowlist:
    """Loaded allowlists: `servers[server_name][tool_name] -> AllowedTool`."""

    servers: dict[str, dict[str, AllowedTool]]

    def get(self, server: str, tool: str) -> AllowedTool | None:
        return self.servers.get(server, {}).get(tool)


def _load_one(path: Path) -> ServerAllowlist | None:
    try:
        parsed = ServerAllowlist.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        logger.error("bridge allowlist %s is invalid; skipping: %s", path, exc)
        return None
    if parsed.server != path.parent.name:
        logger.error(
            "bridge allowlist %s server %r does not match its directory; skipping",
            path,
            parsed.server,
        )
        return None
    if SERVER_NAME.fullmatch(parsed.server) is None:
        logger.error("bridge allowlist %s has an invalid server name; skipping", path)
        return None
    return parsed


def load_allowlist(root: Path) -> BridgeAllowlist:
    """Scan `<root>/*/allowlist.yaml` once at app start. These are Solus-owned
    repo files — a bad one is OUR bug, logged loudly and skipped so one broken
    fork cannot brick the API."""
    servers: dict[str, dict[str, AllowedTool]] = {}
    for path in sorted(root.glob("*/allowlist.yaml")):
        parsed = _load_one(path)
        if parsed is None:
            continue
        entries: dict[str, AllowedTool] = {}
        for tool in parsed.tools:
            if SAFE_REMOTE_NAME.fullmatch(tool.name) is None:
                logger.error(
                    "allowlist %s tool %.64r has an unsafe name; skipping", path, tool.name
                )
                continue
            if len(parsed.server) + 1 + len(tool.name) > COMPOSED_NAME_MAX:
                logger.error(
                    "allowlist %s tool %.64r composed name too long; skipping", path, tool.name
                )
                continue
            entries[tool.name] = tool.model_copy(
                update={"supports_dry_run": supports_dry_run(f"{parsed.server}.{tool.name}")}
            )
        servers[parsed.server] = entries
    if not servers:
        # A wrong root and a correct-but-empty one used to look identical: every
        # bridge tool would then be rejected as un-allowlisted, with no clue why.
        logger.warning("no bridge allowlists found under %s — is the root correct?", root)
    return BridgeAllowlist(servers=servers)


@dataclass(frozen=True)
class BridgeToolSpec:
    """One companion-advertised tool that survived the cloud-side gate."""

    server: str
    remote_name: str
    descriptor: ToolDescriptor


def _skip_advertised(server: str, name: str, reason: str) -> None:
    # %.64r bounds the companion-authored name inside our own log lines.
    logger.warning("bridge server %.64r tool %.64r %s; skipping", server, name, reason)


def _gate_tool(server: str, tool: HelloTool, allowed: AllowedTool | None) -> str | None:
    """Why an advertised tool is rejected, or None if it passes."""
    if SAFE_REMOTE_NAME.fullmatch(tool.name) is None:
        return "has an unsafe name"
    if allowed is None:
        return "is not allowlisted"
    if len(server) + 1 + len(tool.name) > COMPOSED_NAME_MAX:
        return "composed name too long"
    if tool.output_schema is not None and schema_oversized(tool.output_schema):
        return "advertises an oversized schema"
    return unsafe_schema_reason(tool.input_schema)


def validate_inventory(hello: HelloData, allowlist: BridgeAllowlist) -> tuple[BridgeToolSpec, ...]:
    """Gate a companion's advertised inventory into descriptors (contract §2 /
    ADR-031). `requires_confirmation` comes ONLY from the allowlist."""
    specs: list[BridgeToolSpec] = []
    seen: set[str] = set()
    for advertised in hello.servers:
        if SERVER_NAME.fullmatch(advertised.server) is None:
            _skip_advertised(advertised.server, "", "has an invalid server name")
            continue
        for tool in advertised.tools:
            if f"{advertised.server}.{tool.name}" in seen:
                # SEC-M4: a duplicate advertised name would blow up
                # ToolRegistry.register downstream — first wins, rest dropped.
                _skip_advertised(advertised.server, tool.name, "is a duplicate advertisement")
                continue
            allowed = allowlist.get(advertised.server, tool.name)
            reason = _gate_tool(advertised.server, tool, allowed)
            if reason is not None:
                _skip_advertised(advertised.server, tool.name, reason)
                continue
            assert allowed is not None  # _gate_tool returned None ⇒ allowlisted
            seen.add(f"{advertised.server}.{tool.name}")
            descriptor = ToolDescriptor(
                name=f"{advertised.server}.{tool.name}",
                description=tool.description[:UNTRUSTED_TEXT_CAP],
                # SOLX-01 SEC-C1/H1: the advertised `description` above is
                # UNTRUSTED fork text — fenced in prompts, refused on consent
                # cards. For the consent card we use OUR words: the Solus-written
                # allowlist `reason` is mandatory on every destructive entry and
                # is reviewed with the fork, so it is what a human reads when
                # approving.
                description_trusted=False,
                consent_summary=allowed.reason,
                params=tool.input_schema,
                returns=(
                    tool.output_schema if tool.output_schema is not None else _ANY_OBJECT_RETURNS
                ),
                timeout_seconds=allowed.timeout_seconds,  # None: the registry default
                requires_confirmation=allowed.requires_confirmation,
                files_errors=allowed.files_errors,
            )
            specs.append(
                BridgeToolSpec(
                    server=advertised.server, remote_name=tool.name, descriptor=descriptor
                )
            )
    return tuple(specs)
