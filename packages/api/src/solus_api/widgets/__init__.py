"""First-party bundle capabilities (SOLUSDEV-246 / STORE ST1, ADR-035 as amended
2026-09-05, docs/api/widget-bundles.md).

A schema_version 2 ``extension.toml`` may DECLARE ``[backend]``, ``[graph]`` and
``[tools]``; the code behind those declarations is a package in this directory,
never bytes in a bundle. Adding a capability is a *create* — a new sub-package
exporting ``CAPABILITY`` — exactly like a CTR-01 widget manifest; nothing here
lists capabilities by hand (``registry.discover_capabilities``).
"""
