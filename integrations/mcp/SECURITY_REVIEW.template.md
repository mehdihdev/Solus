# Fork security review — `<tool>` @ tree `<hash>` — `<YYYY-MM-DD>`

> Template (MCP-03). A review = a **dated, filled copy** of this file appended to
> `integrations/mcp/<tool>/SECURITY_REVIEW.md` (append-only — the history of what was reviewed is
> the point), signed by **both devs** in PROVENANCE.md against the same tree hash.
> **Every item requires pasted evidence** — the command run and the relevant output — not a bare
> tick. An unchecked or unevidenced item means the fork does not ship. Threat model: this code
> runs on a **customer's machine**; the companion and cloud treat its output as untrusted either
> way (BRG-02 §6) — this checklist is about what the fork can do LOCALLY: leak secrets, escape
> its scope, exfiltrate, or execute beyond least privilege.

## 1. Supply chain
- [ ] `upstream/` matches the PROVENANCE-pinned commit — evidence: diff the vendored tree against
  `git archive <SHA>` of upstream; record the tree hash.
- [ ] No runtime fetch: `bin/launch` and the entrypoint path contain no `npx`/`uvx`/`pipx`/
  `pip install`/`npm install`/`curl | sh` — evidence: `bin/launch` read in full + grep output
  over the launch path.
- [ ] Registry install hooks read and inert or stripped: npm `preinstall`/`postinstall`,
  `setup.py` custom commands — evidence: the hook contents or "none".
- [ ] Lockfile committed, complete, hash-pinned; install reproduces **offline**
  (`npm ci --ignore-scripts` / `pip install --require-hashes --no-index`) — evidence: the install
  run in a network-disabled container.
- [ ] Dependency audit clean at review time (`pip-audit` / `npm audit --audit-level=high` against
  the lockfile); every remaining advisory dispositioned in writing here.
- [ ] Reproducibility: two clean installs from the same tree resolve dependency sets identical to
  the lockfile. (Bit-identical build artifacts NOT required — see Exclusions.)

## 2. Least privilege
- [ ] Runs as the invoking user: no `sudo`/`setuid`/privilege elevation/admin APIs in the launch
  path or shipped code — evidence: `grep -rn "sudo\|setuid\|seteuid\|runas" upstream/ solus/ bin/`.
- [ ] Filesystem scope: all file access in exposed handlers resolves inside the project workspace
  the companion passes; absolute-path and `..` inputs rejected — evidence: tier-1 line-read of
  the fs helpers (§7).
- [ ] Network egress: **none**, unless a specific allowlisted tool's function requires it — then
  each endpoint is named here — evidence: grep for
  `requests|urllib|http.client|socket.|fetch(|axios|net.connect|WebSocket` and a note on every hit.
- [ ] No `shell=True` / `os.system` / `child_process.exec` with input-influenced strings; every
  subprocess call uses a fixed argv list — evidence: grep + a note per hit.
- [ ] `spec.args` fixed at authoring time; nothing model- or server-supplied ever reaches the
  argv of the server or its subprocesses — evidence: `bin/launch` + the spec, read together.

## 3. Sandbox posture
- [ ] A **declared sandbox posture** section exists below for this fork, per OS the companion
  supports — honest even if today's answer is "OS user permissions + launcher env-scrub +
  workspace cwd only" — plus what it assumes the companion adds later. (The mechanism is
  companion work; the DECLARATION is mandatory now.)
- [ ] The fork functions under the strictest posture it declares — evidence: exposed tools run
  once under a deny-by-default wrapper (network-disabled container; read-only mounts outside the
  workspace) with no failures caused by blocked *undeclared* access.
- [ ] Nothing detects/disables sandboxing or self-modifies the install — covered by the tier-1
  launch-path read; note anything suspicious here.

## 4. Secret hygiene
- [ ] Environment access confined to the written env allowlist in `solus/`; `bin/launch` scrubs
  the rest — evidence: `grep -rn "os.environ\|getenv\|process.env" upstream/ solus/`, every hit
  reconciled against the allowlist.
- [ ] No credential ever logged: logging call sites in exposed paths reviewed — evidence: grep of
  logging calls in tier-1 files + a note.
- [ ] No telemetry/phone-home in upstream code — verified via the §2 egress grep and **stripped**
  (not configured off) if found; the strip is a PROVENANCE modification row.
- [ ] No credential persistence: nothing token/key-shaped written to disk, cache, or dotfiles by
  any exposed path — evidence: grep of file-write sites in tier-1 files.
- [ ] SecretStore values reach the server only through the sanctioned delivery seam
  (MCP-03/MCP-05 follow-on); nothing in the fork reads Solus config or credential stores.

## 5. Untrusted I/O
- [ ] Tool inputs treated as hostile: paths canonicalized and workspace-confined (traversal);
  archives extracted with size/count/depth bounds (zip-bomb) per CLAUDE.md §7 — evidence: tier-2
  line-read of every allowlisted handler touching files/archives.
- [ ] Parsers bound input sizes; malformed input yields an error, never a crash or hang —
  evidence: each file-consuming allowlisted tool fed one malformed and one oversized input.
- [ ] No `eval`/`exec`/`Function()`/dynamic import of computed paths on input-influenced data —
  evidence: grep + a note per hit. (A declared interpreter tool — e.g. a script-runner — is its
  function and is confirmation-gated; a HIDDEN eval is a finding.)
Note (no checkbox — nothing to evidence): fork **outputs** are untrusted upstream regardless —
cloud ingress caps and redaction own that side (BRG-02 §6); nothing in this review relies on
output hygiene.

## 6. Destructive actions
- [ ] Every allowlisted tool classified destructive / non-destructive in `allowlist.yaml`, with a
  one-line `reason` on each destructive entry — evidence: the reviewer classifies independently
  from handler code (§7 tiers) and diffs against the allowlist; differences resolved before ship.
- [ ] Every destructive tool carries `requires_confirmation: true`. Server-side `destructiveHint`
  annotations were NOT relied on — they are untrusted (and `mcp_tool.py` ignores them).
- [ ] No allowlisted tool has side effects beyond its description (writes/deletes/external
  mutations found in the code read but absent from the description) — any found: description
  fixed or tool dropped.

## 7. Code-review depth — the honest tiers
Large servers cannot be line-audited in full; unrecorded "full audits" are theater. Record depth:
- [ ] **Tier 1 — 100% line-read:** `bin/launch` + entrypoint/startup path; all network code; all
  shared fs helpers; all subprocess/exec sites; all env access; all install/build scripts; all
  dynamic-code sites. Every grep hit from §2/§4/§5 is tier-1 by definition.
- [ ] **Tier 2 — line-read:** the handler of every allowlisted tool marked
  `requires_confirmation: true`, plus every allowlisted handler touching files, network, or
  subprocess.
- [ ] **Tier 3 — spot-check:** remaining allowlisted handlers — minimum **20%** random sample,
  the sample listed here by file:function.
- [ ] Non-allowlisted tool code: disabled in-process via a `solus/` shim (preferred — then
  skippable), or swept by the tier-1 greps with the residual risk stated here explicitly.
- [ ] Depth recorded: files line-read vs spot-checked vs skipped, with the grep evidence — this
  record is what makes the next review's delta cheap.

## 8. Update path
- [ ] The PROVENANCE re-review triggers are in force; the tree hash recorded there matches the
  tree under review — evidence: recompute.
- [ ] On rebase: this checklist re-runs — tier 1 in full; tiers 2–3 may scope to
  `git diff <old>..<new>` plus any file the diff touches in tier-1 categories. A pure
  dependency-bump CVE backport may scope to §1 + §8. Both sign-offs required either way.
- [ ] Both PROVENANCE sign-off lines dated against THIS tree hash.

---

## Declared sandbox posture (fill per fork)
`<per OS: what confines this fork today; what it assumes the companion adds>`

## Exclusions — deliberately NOT on this checklist
- "No vulnerabilities exist in the fork" — unfalsifiable; auditing *known* CVEs (§1) is the
  checkable form.
- "Full line-by-line audit of all upstream code" — at 290-tool scale that is signed-but-not-done
  theater; the tiered depth with a recorded file list is the honest replacement.
- "Verify the sandbox cannot be escaped" — proving a negative; replaced by the declared posture +
  behavior-under-deny test (§3).
- Bit-identical reproducible builds — most npm/pip toolchains can't deliver it; lockfile-hash
  pinning (§1) is the supply-chain property that matters.
- Per-fork fuzzing / memory-safety campaigns — unbounded reviewer time; bounded-input behavior
  checks (§5) are the shippable subset.

## Known failure modes of this scheme (and the built-in mitigations)
1. **Stale forks** — re-review cost makes rebases rare and upstream CVE fixes never land.
   Mitigations: a *named* CVE-intake mechanism in PROVENANCE, the 14-day CVE clock, and the
   scoped re-review path (§8) so a security backport isn't priced like a full re-audit.
2. **Allowlist drift** — tools added one small MR at a time; aggregate privilege never
   re-examined; a second copy of the list diverges cloud-side. Mitigations: additions are a
   re-review trigger; ONE file is the source both discovery and bridge ingress load; proposed CI
   asserts spec ↔ directory ↔ allowlist agreement.
3. **Checklist theater** — sign-offs filled, greps never run. Mitigations: pasted evidence per
   item, and the CI-recomputed tree hash — code can't change without mechanically voiding the
   signature, so a stale sign-off is a red build, not an honor-system lapse.
