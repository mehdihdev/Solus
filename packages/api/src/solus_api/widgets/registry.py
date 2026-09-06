"""Capability discovery (SOLUSDEV-246) — CTR-01's rule, in Python.

Every sub-package of ``solus_api.widgets`` must export ``CAPABILITY``. There is
no central list to edit: two capabilities land in two disjoint directories. A
malformed package or a duplicate id raises at import time naming both modules —
these are in-repo build-time errors, not untrusted input, and a loader that
silently skipped one would ship a bundle with no backend and no way to see why.
"""

from __future__ import annotations

import functools
import importlib
import pkgutil
from collections.abc import Iterable, Mapping
from types import MappingProxyType, ModuleType

from solus_contracts.extension_manifest import is_safe_extension_id

from solus_api.widgets.capability import WidgetCapability

#: Path segments under `/projects/{id}/widgets/` that are routes, not bundles.
RESERVED_CAPABILITY_IDS = frozenset({"graph"})


def collect_capabilities(
    modules: Iterable[tuple[str, ModuleType]],
) -> dict[str, WidgetCapability]:
    """Pure: takes already-imported ``(name, module)`` pairs so the rule is
    testable with plain objects (the CTR-01 ``collectManifests`` pattern)."""
    found: dict[str, tuple[str, WidgetCapability]] = {}
    for name, module in modules:
        capability = getattr(module, "CAPABILITY", None)
        if not isinstance(capability, WidgetCapability):
            raise ValueError(f"{name}: must export CAPABILITY = WidgetCapability(...)")
        if not is_safe_extension_id(capability.id) or capability.id in RESERVED_CAPABILITY_IDS:
            raise ValueError(f"{name}: capability id {capability.id!r} is not a valid slug")
        if any(kind.domain == "workspace" for kind in capability.kinds):
            raise ValueError(f"{name}: capability kinds may not use the workspace domain")
        if capability.id in found:
            raise ValueError(
                f"duplicate capability id {capability.id!r}: {found[capability.id][0]} and {name}"
            )
        found[capability.id] = (name, capability)
    return {cid: found[cid][1] for cid in sorted(found)}


@functools.cache
def discover_capabilities() -> Mapping[str, WidgetCapability]:
    """Every capability package under ``solus_api.widgets``, id-sorted. Cached:
    the set is fixed by the build, not by any request."""
    import solus_api.widgets as package

    modules = [
        (info.name, importlib.import_module(info.name))
        for info in pkgutil.iter_modules(package.__path__, prefix=f"{package.__name__}.")
        if info.ispkg
    ]
    return MappingProxyType(collect_capabilities(modules))
