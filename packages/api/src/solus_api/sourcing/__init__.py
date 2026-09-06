"""Sourcing — one engine for two doors (SOLUSDEV-246, STORE ST5).

Workspace › Add › Hardware › Sourced and BOM › Find compatible parts both need
the same thing: a requirement (typed by a person, or derived by Solus from an
assembly's geometry and mass) → candidate parts with trade-offs, filtered by the
project's compliance / style rules with the reason for every exclusion → a
selected part that enters the graph as PLANNED and is visible in the Workspace
and the BOM.

Modules: `torque` (pure arithmetic — never the model's), `rules` (typed,
layered, deterministic), `candidates` (the model's answer parsed as DATA:
grounded or labelled, never invented), `engine` (the metered job), `service`
(graph reads/writes). Routes: `routers/sourcing.py`; plan `docs/api/sourcing.md`.
"""
