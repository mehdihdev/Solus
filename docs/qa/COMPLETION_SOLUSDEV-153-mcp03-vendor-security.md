# Completion Report — SOLUSDEV-153 / MCP-03: vendor layout + fork provenance/license + fork security checklist

**Status:** artifacts produced. **STOPPED at the human gate — this ticket requires review by BOTH
devs; nothing here is self-approved.** Cross-reference: the bridge contract tracks this ticket as
**SOLUSDEV-157**; work is committed as SOLUSDEV-153 on the epic branch, consistent with MCP-01/02.

## 🔔 BRIDGE HANDOFF FLAG
**The BRG worktree loop (~/solus-brg, SOLUSDEV-154) is blocked on this ticket.** Once both devs
approve these artifacts, the bridge loop can resume BRG-02-impl/BRG-01. The BRG-02 §10 holes this
ticket resolves, and where:

| BRG-02 §10 hole | Resolved by |
|---|---|
| Advertised-descriptor allowlisting; which tools a companion may host | `integrations/mcp/README.md` → `allowlist.yaml` — single Solus-owned source of truth; cloud validates `hello` inventory against it; discovery filters against it (code follow-on) |
| `tool` → specific local MCP server mapping | Naming rule: dir == `spec.name` (`^[a-z][a-z0-9_]{0,31}$`, no dots) + the existing `{server}.{tool}` qualification from MCP-01 |
| Local sandboxing / least-privilege / fork-hardening checklist | `integrations/mcp/SECURITY_REVIEW.template.md` (declared sandbox posture per fork; least-privilege section; evidence-based gate) |
| Companion-binary integrity | **⚠ EXPLICIT DEVIATION — BRG-02 §10 assigns this to MCP-03, and this ticket does NOT cover it.** Rationale: binary signing/install-integrity belongs with companion packaging and distribution (BRG-04's bundle), not with per-fork vendoring; the nearest thing here is the launch-path rule (companion refuses commands outside `integrations/mcp/`). **Humans adjudicate at this gate:** either re-assign the hole to BRG-04 when ratifying, or commission a dedicated follow-on. Not silently dropped. |
| `hello` payload wire schema | **NOT resolved here** — BRG-02-impl's to build, against the ratified `allowlist.yaml` format |
| `ArtifactRef` upload path for companion bulk data | **NOT resolved here** — flagged to ride the artifacts-wiring follow-on (also noted in MCP-01's report) |

## Deliverables (all new files; no code touched)
- `integrations/mcp/README.md` — vendor layout: full-fork model, per-fork skeleton
  (`upstream/`+`solus/`+`bin/launch`+`PROVENANCE.md`+`SECURITY_REVIEW.md`+`allowlist.yaml`),
  naming rule, launcher/spec binding (pinned-binary rule made mechanical; zero network at launch;
  lockfile-hash installs at companion install time), provisional-server rule, license policy.
- `integrations/mcp/PROVENANCE.template.md` — the fork provenance/license record: upstream
  SHA/tag/tree-hash, MIT|Apache-2.0-only with NOTICE obligation, modification log, exposed-tool
  ratio, CVE-intake + 14-day clock + rebase procedure, two-dev sign-offs pinned to the tree hash,
  re-review triggers.
- `integrations/mcp/SECURITY_REVIEW.template.md` — the evidence-based gate checklist (8 sections:
  supply chain, least privilege, declared sandbox posture, secret hygiene, untrusted I/O,
  destructive actions, honest tiered code-review depth, update path) + explicit exclusions +
  the scheme's three named failure modes with mitigations.
- `integrations/mcp/CLAUDE.md` — agent rules for the directory (upstream-edit discipline,
  allowlist/sign-offs are human decisions, gate before ship, launcher-only entry, license
  boundary, Pattern-2 rule, key-names-only).
- `temp-MCP-03-adr-mcp-hosting.md` — **HUMAN ACTION: draft ADR** ratifying the fork–harden–own
  hosting model, per BRG-02's "unrecorded decisions" flag #1. Review, number, paste into
  DECISIONS.md, delete the temp file.

## Design decisions (delegated judgment — review these specifically)
1. **Full vendored fork over patch series** — the reviewed tree IS the shipped tree; patch series
   rot on rebase. Solus delta stays recoverable via the pristine import commit + PROVENANCE log.
2. **MIT/Apache-2.0 only, no sign-off escape hatch** — stricter than §6.6's tiers, deliberately:
   customer-machine code admits no copyleft ambiguity. Apache's NOTICE obligation is explicit
   (§6.6 never mentioned Apache-2.0; this introduces it).
3. **`allowlist.yaml` as ONE file consumed by both discovery and bridge ingress** — a second copy
   anywhere is defined as a defect (anti-drift).
4. **Honest tiered review depth** (tier-1 100% line-read of launch/network/fs/subprocess/env/
   install/dynamic-code; tier-2 gated+risky handlers; tier-3 ≥20% recorded sample) instead of
   pretending 290-tool servers get full line audits.
5. **Evidence-per-item + CI-recomputable tree hash** as the anti-theater mechanism: a stale
   sign-off becomes a red build, not an honor-system lapse.
6. **Artifacts only, no code this ticket** — `discover_mcp_tools` allowlist consumption and
   per-tool `requires_confirmation` land AFTER you ratify the `allowlist.yaml` format, so code
   never ossifies an unratified schema.

## Follow-ons this creates (tracked here, not silently dropped)
- **Code:** allowlist filtering + per-tool `requires_confirmation` in `discover_mcp_tools`;
  composed-name re-validation (`len(server)+1+len(tool) ≤ 128` — today only the bare remote name
  is gated; the layout imposes the bound on `allowlist.yaml` entries until code enforces it);
  the `WEB_SEARCH` `npx` pin lands at that server's actual vendoring (TODO(MCP-03) in
  `mcp_servers.py` stays accurate — the *process* now exists, the fork doesn't yet).
- **CI (human-owned `.gitlab-ci.yml`):** spec↔dir↔allowlist name agreement; PROVENANCE tree-hash
  recompute; no-`npx`/`uvx` grep over stdio specs; and the license/SCA audit job CLAUDE.md §7
  promises but CI does not yet implement (pre-existing gap, verified).
- **Bridge side (unblocked on approval):** BRG-02-impl builds `hello` inventory validation
  against `allowlist.yaml`; companion refuses commands outside `integrations/mcp/`.

## Human actions requested
1. Both devs review the four `integrations/mcp/` artifacts — **the gate for this ticket.**
2. ADR paste from `temp-MCP-03-adr-mcp-hosting.md` → DECISIONS.md.
3. Cosmetic, from MCP-02: `docs/contracts/live-connection.md` still carries the pasted temp-file
   header lines ("this temp file is the paste source") — trim at your convenience (human-owned).
4. Decide the CI follow-ons above (H1 territory).

## Verification
Docs-only diff; `ruff` / `mypy --strict` / full suite re-run green on `solus_test_mcp` before
commit (no code touched, suite count unchanged). A fresh-context consistency review verified the
artifacts' claims against MCP-01's code and the BRG-02 contract; its findings were fixed before
this handoff — notably: the composed-name length gap (code gates only the bare remote name; the
layout now imposes the `≤ 128` bound on allowlist entries, with code enforcement tracked as a
follow-on), the companion-binary-integrity deviation made explicit (table above), a dangling
`bridge-protocol.md` reference marked as pending-paste, and one unevidenceable checklist item
demoted to a note. Verified accurate as written: `requires_confirmation` semantics
(blanket spec flag today, per-tool allowlist override as follow-on), destructiveHint-ignored
claim, `TODO(MCP-03)`/keyless-gate claims about `WEB_SEARCH`, Pattern-2 language vs
`live-connection.md`, §6.6 license-tier wording, and the missing-SCA-job claim about CI.
