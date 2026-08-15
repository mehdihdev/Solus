# PROVENANCE — `solidworks` (CAD-03) — **DRAFT, NOT SIGNED, NOT VENDORED**

> This is a pre-vendoring assessment, not a fork record. `upstream/` does not exist and the import
> commit has **not** been made. The reason is in §3: the premise the ticket was written on turned
> out to be false, and the decision that follows is a human's. Everything an agent may decide is
> decided here; everything it may not is listed in §6.

## 1. Target

| Field            | Value                                                                         |
| ---------------- | ----------------------------------------------------------------------------- |
| Upstream         | `https://github.com/andrewbartels1/SolidworksMCP-python`                      |
| Commit assessed  | `34a21fe1ff321ed18aeafe27d317f847ea5f5db2` (committed 2026-08-07T12:17-07:00) |
| Licence          | **MIT**, © 2025 ESPO Corporation                                             |
| Licence method   | `LICENSE` file read in a clone at that commit — never the GitHub API          |
| Size             | ~15 MB, 250 Python files                                                      |
| Tools registered | **112**                                                                       |

Licence verdict is unchanged from `integrations/mcp/LICENCE_VERIFICATION.md` and was re-read at the
exact commit above, as that file requires.

## 2. Modification log

None. Nothing has been vendored.

## 3. Fabricated-data audit — **the blocking finding**

Run: `python3 integrations/mcp/tools/audit_fabricated_tools.py <clone>`
Full output: [`FABRICATED_DATA_AUDIT.txt`](FABRICATED_DATA_AUDIT.txt) (regenerable, not hand-written).

**48 of 112 tools can report success for work that never happened.**

`LICENCE_VERIFICATION.md` requires that such tools be "stripped before vendoring", and the CAD-03
ticket estimated about eight of them. The real number is 48, which is not a strip — it is a
different fork. Two shapes:

**a. Never touches SolidWorks at all (13).** The function has no path to the CAD application and
returns a success payload anyway:

```python
async def get_material_properties():
    return {"status": "success", "material": {
        "name": "Steel, Plain Carbon", "density": {"value": 7850, "units": "kg/m³"}, ...}}
```

That is returned whatever the part is actually made of. Others in this group invent
`dimensions_added: 12`, `coverage: "85%"`, `compliance_score: 92`, and a macro recording with
`duration: "5 minutes", actions_recorded: 15` and a hardcoded Windows path.

**b. Capability-probe fallback (35).** The tool asks whether the live adapter supports the
operation, and when it does not, reports success anyway:

```python
if hasattr(adapter, "check_interference"):
    result = await adapter.check_interference(...)      # the real path
    ...
return {"status": "success", "interference_found": False, "interferences": []}   # nothing ran
```

`save_file` does the same and returns `timestamp: "2024-03-14T00:00:00Z"`.

### Why this is disqualifying for Solus specifically

Solus exists to catch cross-domain problems before they break the robot. `check_interference`
returning "no interference" when no check ran is not a missing feature — it is the product asserting
the opposite of the truth. The graph cannot distinguish "clear" from "never looked", the checkers
cannot, and neither can SOL: it will summarise a fabricated pass as a real one, in Guide mode, to a
user who is trusting it precisely because they do not know the domain.

An honest error is recoverable. A confident false negative on an interference check is the failure
mode the whole product is against.

## 4. Was the assessment fair?

The audit was built to avoid crying wolf, and the tests
(`integrations/mcp/tools/tests/test_audit_fabricated_tools.py`) pin the discriminations:

- A tool that probes `hasattr` and then calls a **different** adapter method really did reach CAD;
  it is not flagged (`export_step` is this shape).
- `generate_vba_*` (12) emit VBA source for a human to run and claim nothing about the CAD
  application. **Not counted.**
- Delegating wrappers are judged by their target, not accused (`get_mass_properties` is one).
- The target's own `tests/` are skipped — upstream test doubles fabricate on purpose.

The findings above were each read by hand as well, not taken from the script alone.

## 5. What the repository is good at (so the decision is informed, not one-sided)

The COM adapter layer, the Pydantic input models, and the sketching/feature paths that DO reach the
adapter look competent, and roughly 62 tools have no finding against them. A fork that kept only
those is a real option — see option B below.

## 6. Decision required from a human — this is not an agent's call

| Option                                                                                                                             | What it costs                                                                                                                                                                        |
| ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **A. Do not vendor.** Drop `solidworks` from the catalog for now.                                                                  | Loses SolidWorks; costs nothing else. The spec entry stays PROVISIONAL and unreachable, as it is today.                                                                              |
| **B. Vendor and strip 48.** Import verbatim, then remove or shim every flagged tool in `solus/`.                                   | ~15 MB import plus 48 documented removals, each a PROVENANCE modification row, plus the ongoing rebase cost against an upstream that keeps adding tools in this idiom.               |
| **C. Write a thin Solus SolidWorks server.** Use the upstream COM adapter as reference under MIT, implement only what Solus needs. | Most work up front, no fabricated surface by construction, and no fork to maintain. Nearest to how Onshape was done (`connectors/onshape_ops.py`), which is the pattern that worked. |

My recommendation is **C**, then **A** as the interim. Option B inherits a maintenance obligation
against a codebase whose default idiom is the thing being stripped — every upstream sync re-imports
the pattern, and a reviewer has to catch it again each time. The generated
[`allowlist.yaml`](allowlist.yaml) is written for option B if it is chosen: 62 survivors, all
`requires_confirmation: true`, with the 48 present as commented-out `EXCLUDED` lines so no reviewer
wonders whether a name was simply missed.

## 7. Gate status

- [x] Licence read at the pinned commit — MIT, forkable
- [x] Fabricated-data audit run, output committed
- [x] `allowlist.yaml` drafted (agent-permitted per `integrations/mcp/CLAUDE.md` rule 2)
- [ ] **Vendoring decision (§6) — HUMAN**
- [ ] `upstream/` import at the pinned SHA — blocked on §6
- [ ] `solus/env.allow`, `bin/launch`, lockfile — blocked on §6
- [ ] `SECURITY_REVIEW.md` passed and dated — **HUMAN**, and never self-approved by an agent
- [ ] Vendored-tree hash recorded here — blocked on the import
- [ ] Sign-off — dev 1: ******\_\_****** dev 2: ******\_\_****** — **HUMAN**

Until §6 is answered, `MCPServerSpec(name="solidworks", ...)` in
`packages/api/src/solus_api/agent/tools/mcp_servers.py` stays PROVISIONAL: its `command` points at a
`bin/launch` that does not exist, so it cannot spawn, and the BYO-licence gate precedes any
transport work regardless.
