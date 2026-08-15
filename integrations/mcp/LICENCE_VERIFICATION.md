# Fork-target licence verification

**Method — non-negotiable.** Every verdict below comes from **reading the LICENSE file in the
repository**, fetched from `raw.githubusercontent.com`. The GitHub API's reported licence is **not
authoritative** and is never used here. The AuraFriday case below is the proof of why.

Re-verify before vendoring: a repository's licence can change, and a verdict recorded here binds
only the tree that was read.

Last verified: **2026-08-08** (re-read at the exact commits below).

---

## Verdicts

| Target                                | Tool       | LICENSE file read | Verdict                    | Forkable  |
| ------------------------------------- | ---------- | ----------------- | -------------------------- | --------- |
| `andrewbartels1/SolidworksMCP-python` | SolidWorks | `34a21fe/LICENSE` | MIT (© 2025 ESPO Corp.)   | Legally yes — **see below** |
| `U-C4N/Autocad-MCP`                   | AutoCAD    | `abc2a82/LICENSE` | MIT (© 2026 U. Edizsalan) | **Yes**   |
| `AuraFriday/Fusion-360-MCP-Server`    | Fusion 360 | `main/LICENSE`    | **SPDX: Proprietary**      | **NEVER** |

### ⚠️ `AuraFriday/Fusion-360-MCP-Server` — do not fork, do not vendor, do not read for ideas

Its `LICENSE` opens with:

```
SPDX-License-Identifier: Proprietary

Copyright © 2025 Aura Friday. All Rights Reserved.
```

It is the most-starred Fusion MCP result, and **the GitHub API reports the much softer
`NOASSERTION`** for it. Anyone trusting the API instead of the file would conclude it was
ambiguous-but-probably-fine and fork a repository whose licence forbids exactly that. This entry
exists so nobody repeats that.

Fusion (CAD-02) therefore does **not** go through a fork at all — Autodesk ships its own MCP server
on `127.0.0.1:27182`, and Solus is a **client** of it. That path has no licence question, and it is
blocked only on **G5** (a human confirming Fusion Personal tier terms and the EULA).

---

### ⚠️ `andrewbartels1/SolidworksMCP-python` — MIT, and still blocked

The licence is fine. The **fabricated-data audit is not**: 48 of its 112 tools can report success
for work that never happened, including `check_interference` returning "no interference" when no
check ran. A permissive licence settles the legal question and nothing else — this is the checklist
item below being exercised for real. Full record and the options:
[`solidworks/PROVENANCE.md`](solidworks/PROVENANCE.md).

`U-C4N/Autocad-MCP` was audited the same way and came back clean (0 of 155):
[`autocad/PROVENANCE.md`](autocad/PROVENANCE.md).

---

## Before either MIT fork is vendored

Both are permissively licensed, which settles the legal question and nothing else. Each still owes:

- [ ] **Re-read the LICENSE file** at the exact commit being vendored, and record the tree hash in
      `PROVENANCE.md`.
- [x] **Fabricated-data audit.** Every tool that returns plausible-looking data without actually
      talking to the CAD application is **stripped before vendoring**, and the removal is listed in
      `PROVENANCE.md`. A tool that invents a mass property is worse than a missing tool: the graph
      cannot tell the difference, and neither can the agent.
      **Now mechanical**: `python3 integrations/mcp/tools/audit_fabricated_tools.py <clone>`.
      Run it against a clone at the exact commit and commit the output beside `PROVENANCE.md`.
      Check `CAD_HANDLES` covers the target's seam first — an unlisted seam reports a vacuous zero.
- [ ] **`allowlist.yaml`** naming only the tools that survive, with per-tool
      `requires_confirmation` authored by Solus (the server's own `destructiveHint` is untrusted).
- [ ] **`solus/env.allow`** listing the variable names the fork may inherit, and a private
      dependency environment at `.venv/` built from the fork's committed lockfile with hash
      verification (CAD-00b).
- [ ] **`SECURITY_REVIEW.md` signed by BOTH developers.** This is a human gate. It is never
      self-approved by an agent, and any later change to `bin/launch`, the env allowlist, or the
      lockfile **voids both sign-offs** and requires a fresh review.

Neither fork may be described as "done" on the strength of a mock. Until a licensed SolidWorks or
AutoCAD install has exercised it end to end, the honest status is **"proven against a
protocol-faithful mock; live E2E unverified pending licence."**
