# Completion Report — SOLUSDEV-153 / MCP-04: metadata-extraction acquisition-path amendment

**Status:** deliverable produced — **`temp-MCP-04-metadata-extraction.md` at the repo root,
awaiting your paste** into `docs/contracts/metadata-extraction.md` (human-owned; the contract was
not touched). Stopped at the per-ticket gate.

## What the amendment does (Edit 4, parts 4a–4g — the contract's own accretion convention)
Adds a THIRD acquisition mechanism — **live MCP export call** — alongside Live-API and
committed-export: for a committed-export tool with a vendored server
(`integrations/mcp/<tool>/`, MCP-03), the connector may obtain the SAME export file by
dispatching the fork's export tool through the W0-04 registry and the bridge (MCPTool, MCP-01),
Onshape-thin-API-shaped: a means to get the file and know it changed, never a deep integration.
New §2.1 carries the five load-bearing invariants:
1. **Mapping preservation** — the parser and §5 field mappings cannot tell acquisition paths
   apart; no mapping/`modality_hints` change is permitted (the ticket's hard rule).
2. **Identity is content-derived, never transport-derived** — `source_key` ≡ `external_ref` ≡
   `SourceRef.external_ref` comes from refdes/instance-id/path exactly as §5 defines, never from
   temp paths or ArtifactRef ids → **fingerprint (W0-06) receives identical canonical-part inputs
   regardless of source**.
3. **Committed-file fallback retained** — the ADR-030 baseline stays the default; companion
   offline / tool closed / `ToolResult(ok=false)` → committed export with a logged degradation;
   live export, when available, is preferred as the fresher working copy.
4. **Untrusted either way** — an MCP-acquired export gets the same defensive parsing as a
   committed file; the bridge grants no trust.
5. **Export tools are non-destructive, allowlisted reads**; mutating tools are outside this
   mechanism and confirmation-gated per MCP-03.
Bulk bytes ride `ArtifactRef` (`ArtifactStorage.CLIENT`) per the bridge contract's size caps.

## Verification
A fresh-context reviewer verified every paste anchor character-for-character against the contract
(all real, unique, no Edit-number collision), confirmed the scope guard holds (no mapping/§6/§7
touches), and confirmed every code/contract claim (`ArtifactStorage.CLIENT`, bridge size caps,
allowlist semantics, never-raises envelope, Edit-3 identity chain). Its two findings were fixed:
the hosting-model ADR is now cited concretely as **ADR-031** (you pasted it during this
iteration), and the ADR-030 revisit clause is quoted verbatim. Docs-only diff; full gate re-run
green before commit.

## Human actions
1. ~~Paste Edit 4a–4g~~ DONE 2026-07-30 under ADR-032 (agent-editable docs): applied to
   `docs/contracts/metadata-extraction.md`, temp file deleted.
2. ~~ADR-031 ratification~~ DONE: Accepted 2026-07-30 (SOLUSDEV-154 / ADR-032 landing; Mehdi
   co-review at the MR). Edit 4a cites it as Accepted.
3. This closes the last unblocked ticket before epic close: **MCP-05 remains BLOCKED-ON-BRG-02**
   (all-or-nothing per your decision). On your go, the epic-close iteration runs the integration
   check + writes `COWORK_QA_mcp-foundation.md`.
