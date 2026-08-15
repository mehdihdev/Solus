# PROVENANCE — `autocad` (CAD-04) — **DRAFT, NOT SIGNED, NOT VENDORED**

> Pre-vendoring assessment. `upstream/` does not exist and the import commit has **not** been made:
> the import is worth nothing until §6's sign-offs exist, and those are human. Everything an agent
> may decide is decided here.

## 1. Target

| Field            | Value                                                                            |
| ---------------- | -------------------------------------------------------------------------------- |
| Upstream         | `https://github.com/U-C4N/Autocad-MCP`                                           |
| Commit assessed  | `abc2a82e7128358b9e228a7d9442b37019aa3fe5` (committed 2026-08-07T09:30:34+03:00) |
| Licence          | **MIT**, © 2026 Umutcan Edizsalan                                               |
| Licence method   | `LICENSE` file read in a clone at that commit — never the GitHub API             |
| Size             | ~4.9 MB                                                                          |
| Tools registered | **155**                                                                          |

Re-read at the exact commit above, as `integrations/mcp/LICENCE_VERIFICATION.md` requires.

## 2. Modification log

None. Nothing has been vendored.

## 3. Fabricated-data audit — clean, with a stated limit

Run: `python3 integrations/mcp/tools/audit_fabricated_tools.py <clone>`
Full output: [`FABRICATED_DATA_AUDIT.txt`](FABRICATED_DATA_AUDIT.txt).

**0 of 155 tools flagged**, against 48 of 112 for the SolidWorks target
([`../solidworks/PROVENANCE.md`](../solidworks/PROVENANCE.md) §3). The difference is structural, not
luck: every tool here routes through `_backend(ctx)` and returns the backend's own payload rather
than assembling a `status: success` dict of its own, so there is nothing to fabricate into.

**The limit on that zero, stated so nobody reads it as a clean bill of health.** The audit knows a
fixed list of CAD seams (`CAD_HANDLES`); a target using an unlisted seam reports a vacuous zero.
`_backend(` was added to that list for this target and verified against the tree — 150 of 155 tools
reference it. The five that do not were read by hand:

| Tool                            | Verdict                                                                                                                                                                                                                      |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `analysis_measure_area`         | **Honest, unusually so.** Its docstring says "This measures the numbers in the call, NOT the drawing", points at `analysis_measure_entity` for real geometry, and returns an `assumes` field naming what was taken on faith. |
| `template_list`                 | Lists a local constant. Claims nothing about the drawing.                                                                                                                                                                    |
| `system_status`, `system_about` | Server metadata. `_tool_count` returns `None`, not `-1`, "when the count is genuinely unknown … rather than report a fake value" — upstream's own comment.                                                                   |
| `capability.default`            | Backend capability declaration, not a CAD call.                                                                                                                                                                              |

This repository appears to have thought about the exact failure mode CAD-03 fell into.

## 4. What CAD-04 actually maps — read this before writing the connector

**AutoCAD is not a 3D assembly tool in this context, and modelling it as one will produce a wrong
graph.** The upstream tool surface is DWG/DXF: layers, blocks, block attributes, xrefs, text, hatch,
dimensions, model/paper space. For the Robotics Context Model that means:

- **Block definition → entity**; **block insert → an instance relation**, not a second entity. A
  drawing with 40 inserts of one bracket is one part and 40 placements.
- **Block attributes → the part's fields** (part number, material, revision). This is where a
  manufacturer part number actually lives in a 2D package, so it is the supply-chain signal the
  fingerprint matcher can use (`reasoning/fingerprint/`).
- **Xrefs → `depends_on` between drawings.** An xref graph is the closest thing AutoCAD has to an
  assembly tree and is the right source for cross-file relations.
- **Layers → grouping metadata**, not entities. A layer is not a part.
- There is **no mass, no volume, no mate**. Anything in Solus that expects those from a mechanical
  source must tolerate their absence rather than defaulting them — a defaulted mass is the same
  class of lie as §3 of the SolidWorks record.

The `ezdxf` backend also means a large part of this is usable **without an AutoCAD licence at all**,
reading `.dxf`/`.dwg` files directly. That materially changes the CAD-04 shape and is the strongest
argument for looking at this target before SolidWorks.

## 5. Decision required from a human

| Option                                                                                          | Note                                                                                                                   |
| ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **A. Vendor as a fork.** Import verbatim, `bin/launch`, `solus/env.allow`, security review.     | The audit supports it. 155 tools is a large allowlist to review by hand — see the note below.                          |
| **B. Depend on `ezdxf` directly** and write a Solus DXF/DWG reader for the four mappings in §4. | No fork, no customer licence, no companion needed for file-based reads. Does not cover driving a live AutoCAD session. |
| **C. Both**, later: B for ingestion, A when live-session editing is wanted.                     |                                                                                                                        |

I recommend **B first**. §4's mappings are all file-readable, `ezdxf` is MIT and already the
upstream's own backend, and it removes the BYO-licence gate from the ingestion path entirely — which
is what makes AutoCAD data reach the graph for users who do not have a seat. A is a good follow-on
and its groundwork is done here.

**On the 155-tool allowlist:** reviewing all of them is not the sensible first move.
[`allowlist.yaml`](allowlist.yaml) is generated with **every** tool `requires_confirmation: true`, so
it is safe as it stands; the review that matters is downgrading the read-only ones, and that can be
done incrementally as tools are actually wanted. Upstream tags each tool `cost=read` / `cost=mutate`
and sets `readOnlyHint`, recorded in each reason line as **untrusted evidence** for whoever reviews.

## 6. Gate status

- [x] Licence read at the pinned commit — MIT, forkable
- [x] Fabricated-data audit run, output committed, limitation stated
- [x] Graph-mapping analysis (§4) — the substance of CAD-04
- [x] `allowlist.yaml` drafted (agent-permitted per `integrations/mcp/CLAUDE.md` rule 2)
- [ ] **Vendor-vs-`ezdxf` decision (§5) — HUMAN**
- [ ] `upstream/` import at the pinned SHA — blocked on §5
- [ ] `solus/env.allow`, `bin/launch`, lockfile — blocked on §5
- [ ] `SECURITY_REVIEW.md` passed and dated — **HUMAN**, never self-approved by an agent
- [ ] Vendored-tree hash recorded here — blocked on the import
- [ ] Sign-off — dev 1: ******\_\_****** dev 2: ******\_\_****** — **HUMAN**

Until §5 is answered, `MCPServerSpec(name="autocad", ...)` stays PROVISIONAL: its `command` points at
a `bin/launch` that does not exist, so it cannot spawn.
