"""`altium.export_netlist` — the Solus-authored Protel netlist export
(SOLUSDEV-102 ALT-6).

Interface (allowlist.yaml; mirrors the kicad fork's plan-locked envelope):
    args   {"project_path": str}
    result {"format": "protel", "filename": str, "bytes": int,
            "content": str|null, "artifact_path": str|null,
            "degraded": false, "reason": null}
Exactly one of content/artifact_path is non-null, branching at
`INLINE_MAX_BYTES`; `artifact_path` is WORKSPACE-relative and the file always
lives inside the workspace. On ANY failure — Altium unreachable (the honest
in-house default: no Altium on this machine), malformed bridge data,
unrepresentable/unbounded content, artifact write failure — the tool returns
    {"degraded": true, "reason": <stable REASON_* string>}
and NEVER raises: a failed export must degrade the result, not crash the MCP
server.

Data sourcing (security review): EXACTLY the two read-only IPC commands the
allowlist reasons name — `project.get_nets` and `project.get_bom`, sent
through upstream's file-drop bridge with upstream's own wire encoding (limit
as str). The `force_recompile` flag is never sent (upstream's True path saves
all dirty documents — the hidden write PINNED_PARAMETERS also blocks on
proj_get_nets). Everything the bridge returns is untrusted DATA: shapes are
checked defensively and every field value flows through the neutralizing
emitter (`solus/protel_emit.py`).

Registered through ALT-5's TrimmingRegistrar (`register_export_tools` is
invoked with the registrar in `solus/registration.py`), so the tool inherits
the same hardening as every roster tool: `project_path` is workspace-confined
BEFORE this body runs, ctx is stripped, stdout is diverted off the protocol
channel.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .protel_emit import (
    ProtelComponent,
    ProtelEmitRefusalError,
    ProtelNet,
    emit_protel_netlist,
)
from .trimming import SupportsToolDecorator
from .workspace import workspace_root

RESULT_FORMAT = "protel"

#: Local mirror of the cloud `artifact_inline_max_bytes` (bridge-contract
#: size caps): results at or below this inline the netlist as `content`;
#: above it the bytes land as a workspace artifact named by `artifact_path`.
INLINE_MAX_BYTES = 512 * 1024

#: Subdirectory of the workspace that holds tool-produced artifacts
#: (mirrors the kicad fork's convention).
ARTIFACT_DIR_NAME = "solus-artifacts"

#: Stable degraded-envelope reasons (the cloud treats them as advisory text;
#: tests pin them so they never drift silently).
REASON_ALTIUM_UNREACHABLE = "altium_unreachable"
REASON_DATA_MALFORMED = "netlist_data_malformed"
REASON_ARTIFACT_WRITE_FAILED = "artifact_write_failed"
REASON_EXPORT_FAILED = "netlist_export_failed"

#: Wire-encoded query limits, mirroring upstream's own bulk guidance (its
#: exporter pulls the full pin table with limit=100000). Sent as str —
#: upstream's wire encoding for the file-drop bridge.
_NETS_QUERY_LIMIT = 100_000
_BOM_QUERY_LIMIT = 20_000

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]")


class _MalformedPayloadError(ValueError):
    """A bridge response did not carry the documented get_nets/get_bom shape."""


def _get_bridge() -> Any:
    """The one seam to upstream's file-drop IPC bridge (monkeypatchable in
    tests; lazily imported because the vendored tree joins sys.path during
    the entry module's bootstrap)."""
    from eda_agent.bridge import get_bridge

    return get_bridge()


def _degraded(reason: str) -> dict[str, Any]:
    return {"degraded": True, "reason": reason}


def _text(value: Any) -> str:
    """Untrusted scalar → str ("" for null); the emitter neutralizes it."""
    return "" if value is None else str(value)


def _adapt_components(bom_data: Any) -> tuple[ProtelComponent, ...]:
    if not isinstance(bom_data, dict):
        raise _MalformedPayloadError("get_bom response is not an object")
    raw_components = bom_data.get("components")
    if not isinstance(raw_components, list):
        raise _MalformedPayloadError("get_bom components is not a list")
    components = [
        ProtelComponent(
            designator=_text(entry.get("designator")),
            footprint=_text(entry.get("footprint")),
            comment=_text(entry.get("comment")),
        )
        for entry in raw_components
        if isinstance(entry, dict)
    ]
    return tuple(sorted(components, key=lambda component: component.designator))


def _adapt_nets(nets_data: Any) -> tuple[ProtelNet, ...]:
    if not isinstance(nets_data, dict):
        raise _MalformedPayloadError("get_nets response is not an object")
    raw_pins = nets_data.get("pins")
    if not isinstance(raw_pins, list):
        raise _MalformedPayloadError("get_nets pins is not a list")
    by_net: dict[str, set[tuple[str, str]]] = {}
    for pin in raw_pins:
        if not isinstance(pin, dict):
            continue
        net = _text(pin.get("net"))
        designator = _text(pin.get("component"))
        pin_number = _text(pin.get("pin"))
        if not net or not designator or not pin_number:
            continue  # mirrors upstream's own exporter: incomplete rows drop
        by_net.setdefault(net, set()).add((designator, pin_number))
    return tuple(ProtelNet(name=name, nodes=tuple(sorted(by_net[name]))) for name in sorted(by_net))


def _artifact_filename(project_path: str) -> str:
    """A bare, benign artifact filename derived from the project stem."""
    stem = _FILENAME_SAFE.sub("_", Path(project_path).stem).lstrip(".")
    return f"{stem or 'project'}-netlist.net"


def _artifact_destination(filename: str) -> Path:
    """The confined path for one artifact file; re-checks the RESOLVED path
    is inside the workspace (defense in depth against symlinked artifact
    directories)."""
    root = workspace_root()
    directory = root / ARTIFACT_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    destination = (directory / filename).resolve()
    if not destination.is_relative_to(root):
        raise OSError(f"artifact destination escaped the workspace: {filename!r}")
    return destination


def _package_result(text: str, filename: str) -> dict[str, Any]:
    """The export envelope: inline at or below the cap, artifact above."""
    data = text.encode("utf-8")
    size = len(data)
    content: str | None = None
    artifact_path: str | None = None
    if size <= INLINE_MAX_BYTES:
        content = text
    else:
        destination = _artifact_destination(filename)
        destination.write_bytes(data)
        artifact_path = destination.relative_to(workspace_root()).as_posix()
    return {
        "format": RESULT_FORMAT,
        "filename": filename,
        "bytes": size,
        "content": content,
        "artifact_path": artifact_path,
        "degraded": False,
        "reason": None,
    }


async def export_netlist_impl(project_path: str) -> dict[str, Any]:
    """Export the project's netlist as Protel text. Never raises."""
    try:
        try:
            bridge = _get_bridge()
            nets_data = await bridge.send_command_async(
                "project.get_nets",
                {"limit": str(_NETS_QUERY_LIMIT), "project_path": project_path},
            )
            bom_data = await bridge.send_command_async(
                "project.get_bom",
                {"limit": str(_BOM_QUERY_LIMIT), "project_path": project_path},
            )
        except Exception:
            # Any failure to round-trip Altium — not running, not attached,
            # timed out, protocol fault — is the same honest answer.
            return _degraded(REASON_ALTIUM_UNREACHABLE)
        text = emit_protel_netlist(_adapt_components(bom_data), _adapt_nets(nets_data))
        return _package_result(text, _artifact_filename(project_path))
    except ProtelEmitRefusalError as refusal:
        return _degraded(refusal.reason)
    except _MalformedPayloadError:
        return _degraded(REASON_DATA_MALFORMED)
    except OSError:
        return _degraded(REASON_ARTIFACT_WRITE_FAILED)
    except Exception:
        # The NEVER-raises guarantee: an unexpected bug degrades the result
        # instead of crashing the stdio server mid-session.
        return _degraded(REASON_EXPORT_FAILED)


def register_export_tools(mcp: SupportsToolDecorator) -> None:
    """Register the Solus-authored export tool. Invoked with the
    TrimmingRegistrar (never a bare server) so the tool inherits the shared
    hardening: path confinement before the body, ctx strip, stdout
    diversion."""

    @mcp.tool()
    async def export_netlist(project_path: str) -> dict[str, Any]:
        """Export the Altium project's netlist in Protel format.

        Synthesized from the read-only `proj_get_nets` / `proj_get_bom`
        data. Returns the text inline (`content`) up to 512 KiB, else as a
        workspace-relative `artifact_path`. When Altium is unreachable (or
        any error occurs) returns `{"degraded": true, "reason": ...}` —
        never an exception.
        """
        return await export_netlist_impl(project_path)
