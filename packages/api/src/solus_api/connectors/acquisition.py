"""`ExportAcquirer` — the async live-acquisition seam for `EdaExportConnector`
(SOLUSDEV-100 T4a; docs/contracts/metadata-extraction.md §2.1).

Transport-agnostic by design: nothing about bridges, MCP, ToolCalls, or
`ArtifactRef`s appears in this file. An `ExportAcquirer` is injected into an
`EdaExportConnector` subclass at construction (default `None`, keeping every
subclass zero-arg constructible); `_read_export` tries it first and falls back
to the inline `ctx.config["export"]` path on anything short of success. The
concrete implementation that actually talks to a vendored MCP server over the
bridge — or, later, a live tool API — lives in its own module and simply
satisfies this Protocol; it is out of scope here (a later ticket).

Contract for implementations (each maps to an §2.1 invariant):

* Return the export **text** on success — the SAME kind of string the inline
  `ctx.config["export"]` path supplies. `_read_export` treats it identically
  either way (invariant 1, mapping preservation): parsing and sizing don't
  know or care which path produced the text.
* Return `None` to decline or signal unavailability for this sync (bridge
  offline, companion tool closed, no vendored server for this provider,
  etc.). `_read_export` logs the degradation and falls through to the
  inline export (invariant 3, fallback retention) — `None` is simply the
  cheap, non-exceptional spelling of "nothing to offer this sync".
* Raising is also fine and handled identically to returning `None` — an
  acquirer never needs its own try/except purely to implement "decline";
  `_read_export` catches anything an acquirer raises, logs the degradation,
  and falls back the same way. Only a fully exhausted chain (acquirer
  declined/failed AND no inline export) ever raises `ConnectorError` out of
  `_read_export`.
* The returned text is exactly as untrusted as the inline export (invariant
  4) — an acquirer must not pre-parse, pre-trust, or skip the caller's size
  bound; it only obtains bytes and hands back text.
* Identity (`EntityOut.source_key`) is derived from the parsed content alone
  (invariant 2) — this Protocol carries no transport identifiers (call ids,
  artifact ids, temp-file paths) precisely so there is nowhere for one to
  leak into the graph.
"""

from __future__ import annotations

from typing import Protocol

from solus_api.connectors.contracts import SyncContext


class ExportAcquirer(Protocol):
    """Obtains the same committed-export TEXT the inline `ctx.config["export"]`
    path would otherwise supply, via whatever live mechanism a concrete
    implementation uses. See the module docstring for the full contract.
    """

    async def acquire(self, ctx: SyncContext) -> str | None:
        """Return export text, or `None` to decline/signal unavailability.

        `ctx` carries whatever the acquirer needs to scope the request (repo/
        project identifiers live on `ctx.config`, the same keys the connector
        itself reads). Raising is treated by the caller exactly like
        returning `None`.
        """
        ...
