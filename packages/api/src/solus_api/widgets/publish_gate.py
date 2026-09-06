"""The publish gate for first-party tables (SOLUSDEV-246, widget-bundles.md §7).

Pure. The manifest CLAIMS ``[backend]``/``[graph]``/``[tools]``; this decides
whether the claim may be stored: the publisher must be Solus staff and the
in-repo capability with the same id must provide at least what is declared.
Problems use the contract's dotted-path shape so ``422 bundle_invalid`` lists
them beside the validator's own.
"""

from __future__ import annotations

from collections.abc import Mapping

from solus_contracts.extension_manifest import ExtensionManifest, declares_first_party

from solus_api.widgets.capability import WidgetCapability

NOT_STAFF = "backend: first-party only (publisher is not Solus staff)"
RESERVED_ID = "extension.id: reserved for a Solus first-party bundle"


def first_party_problems(
    manifest: ExtensionManifest,
    *,
    is_staff: bool,
    capabilities: Mapping[str, WidgetCapability],
) -> list[str]:
    slug = manifest.extension.id
    if not declares_first_party(manifest):
        # A plain bundle may not squat an in-repo capability's id: slugs are
        # claimed forever, and Solus must be able to publish that bundle later.
        return [RESERVED_ID] if slug in capabilities and not is_staff else []
    if not is_staff:
        return [NOT_STAFF]
    capability = capabilities.get(slug)
    if capability is None:
        return [f"backend.capability: no in-repo capability named {slug}"]
    problems: list[str] = []
    if manifest.backend is not None and manifest.backend.routes and capability.router is None:
        problems.append(f"backend.routes: capability {slug} has no router")
    provided = {(kind.name, kind.domain) for kind in capability.kinds}
    problems.extend(
        f"graph.kinds.{i}: not provided by capability {slug}"
        for i, kind in enumerate(manifest.graph.kinds)
        if (kind.name, kind.domain) not in provided
    )
    problems.extend(
        f"tools.names.{i}: not provided by capability {slug}"
        for i, name in enumerate(manifest.tools.names)
        if name not in capability.tools
    )
    return problems
