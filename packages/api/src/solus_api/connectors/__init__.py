"""Connector framework (SOLUSDEV-103).

The runtime that registers connectors, runs syncs, persists connector state,
and schedules change detection — plus the concrete connectors that translate
external tools into graph entities/relations (CLAUDE.md §2.1, ADR-001).

`contracts` holds the W0-05 connector interface. It is DRAFTED here so this
ticket is unblocked; per CLAUDE.md §9 the finalized interface belongs in
`packages/contracts/python/` and should be promoted there under human review.
"""
