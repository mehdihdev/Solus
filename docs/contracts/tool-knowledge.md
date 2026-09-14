# Tool-Knowledge Typed Boundary

**Ticket:** SOLUSDEV-220 (SOLUS-CTR-05) · **Lane:** LANE 0 · ⚠ **highest-risk contract on the board**
**TypeScript:** `packages/shared-types/src/tool-knowledge.ts`
**Compile-time proof:** `packages/shared-types/src/tool-knowledge.illegal.ts`
**Python:** `packages/api/src/solus_api/contracts/tool_knowledge.py`
**Fixtures:** `packages/shared-types/fixtures/tool-knowledge/`

---

## The invariant

The tool-knowledge store holds **tool knowledge only**:

> "the extrude icon in Fusion v2.x is at this location and does this"

It is **read by every tenant**. A customer's parts, dimensions, files or designs entering it
would be a cross-tenant leak of proprietary robot design — the highest-severity invariant in
this codebase (CLAUDE.md §7), and for a company whose product is other people's schematics,
existential.

So a customer's content must be as close to structurally impossible as a type can make it.

> **This is a schema-level and review-level constraint. It is explicitly NOT a convention.**
> Nothing here depends on anyone remembering the rule.
>
> ⚠️ **But read the split carefully, because an earlier draft of this document overstated it
> and a security review proved the overstatement.** The *container* is structural: there is no
> field to put customer content in, no identifier of anything customer-owned, every category is
> a closed enum, and twenty illegal constructions fail `tsc`. The *prose fields are not*. They
> are a bounded free-text channel with a pattern backstop, and the backstop cannot classify
> open-world text — `"Hero Arm Bracket Rev C"` validates today, deliberately (there is a test
> pinning it). **An ingestion path must apply its own allowlist at the source; these patterns
> are a net under it, not the floor.**

The type lives in LANE 0 so the boundary exists on `main` **before** any code that writes to
the knowledge base is written in any lane. Enforcement at the ingestion point, and the
rejection tests for it, are SOLUS-TU-06 in LANE D and must merge before any sharing or
compounding work begins.

---

## How the illegal state is made unrepresentable

### 1. The column set is closed

`extra="forbid"` in Pydantic; no index signature and an explicit unknown-field check in
TypeScript. There is no `properties`, `attrs`, `metadata`, `payload`, `notes`, `embedding` or
`screenshot` field — nothing untyped, nothing free-form.

This matters more than any filter. A leak does not usually arrive as a cleverly disguised
string; it arrives because somebody added a `notes` column and pasted a design review into it.

### 2. Nothing customer-owned can be referenced

There is no `project_id`, `team_id`, `entity_id`, `document_id`, `element_id`, `file_path` or
URL field. A record cannot point at a customer's work because there is nowhere to point.

### 3. Every categorical field is an enum

`ToolFamily`, `UiSurface`, `ControlEffect`, `Provenance` — all closed. A free-text category is
a blob with extra steps. Note in particular that `Provenance` has **no customer option**: the
answer "we learned this from a customer's project" is not a value that can be selected.

### 4. Prose is branded (TS) and validated (both) — a backstop, not a filter

The two prose fields — `label` and `description` — plus `control_id` and every menu-path
segment go through `vendorText()` / `_vendor_text`. Text is **NFKC-normalised first**, so
homoglyph evasion (`／home／mehdi／chassis․f3d`, using a fullwidth solidus and a one-dot leader)
does not slip past. Then it **rejects**:

| Rejected shape                             | Example                                                                               |
| ------------------------------------------ | ------------------------------------------------------------------------------------- |
| Filesystem paths                           | `/home/mehdi/robot/chassis.f3d`, `C:\Users\…\arm_v3.sldprt`, `~/designs/gripper.step` |
| Design filenames                           | `motor_mount.step`, anything ending `.f3d .sldprt .kicad_sch .dxf …`                  |
| URLs                                       | `https://cad.onshape.com/documents/…`                                                 |
| Onshape document / workspace / element ids | `d/9a1c2ef4b7d8`, `w/1a2b3c/e/4d5e6f`                                                 |
| UUIDs and long opaque ids                  | `7c9e6679-7425-40de-…`                                                                |
| Email addresses                            | `someone@example.com`                                                                 |
| Dimensioned values                         | `62.5 mm`, `3.0 A`, `24 AWG`                                                          |
| Anything over 400 characters               | an unbounded string **is** a blob field                                               |

In TypeScript the checked result is **branded**: `VendorText` and `ControlId` are
`string & { [brand]: … }`, so a raw string literal **does not type-check** and the only way to
produce one is to go through the checker. That converts "we reviewed it" into "it does not
compile".

`ScreenLocator` is a normalised `0..1` box — numbers, never an image. A screenshot of a
customer's screen is customer content, so there is no field to hold one.

---

## The compile-time proof

`packages/shared-types/src/tool-knowledge.illegal.ts` contains **twenty `@ts-expect-error`
assertions** covering all five categories above. It has no runtime behaviour; it exists to
fail the build.

The mechanism: if any illegal construction ever became legal, TypeScript reports

```
error TS2578: Unused '@ts-expect-error' directive.
```

and `pnpm typecheck` fails. **Verified both directions:**

```console
$ # remove one directive → the line it guarded errors
$ pnpm --filter @solus/shared-types typecheck
src/tool-knowledge.illegal.ts(100,3): error TS2353: Object literal may only specify
  known properties, and 'notes' does not exist in type 'ToolKnowledge'.

$ # weaken the type instead — add `readonly [key: string]: unknown` to ToolKnowledge
$ pnpm --filter @solus/shared-types typecheck
… 12 × error TS2578: Unused '@ts-expect-error' directive.
```

Adding an escape hatch to the type breaks twelve assertions at once. That is what makes this
a boundary rather than a docstring.

The runtime halves are `src/tool-knowledge.test.ts` and
`packages/api/tests/contracts/test_tool_knowledge.py`, both driven by the same fixtures and
the same shared pattern file. Between them they pin every payload a security review got
through — including the ones that are still, deliberately, accepted.

---

## ⚠ The Onshape `featurespecs` trap

Prior work found that Onshape's **per-document `featurespecs`** endpoint returns, alongside
the genuine vendor feature definitions, a customer's **imported custom features**.

This is the dangerous case, because it is **vendor-looking data that is actually customer
content**, and it arrives in exactly the fields a real control would use. An ingestion job
walking `featurespecs` and writing what it finds would populate the shared, every-tenant table
with one customer's proprietary feature library — and every field would look plausible.

The type makes it unrepresentable on two axes:

- The `control_id` of such an entry is a document-scoped identifier (`d/9a1c2ef4b7d8…`), which
  the path/id patterns reject and the slug regex rejects again.
- `provenance` cannot say "a customer's document", so there is no honest way to record it, and
  no dishonest way that passes review.

The same reasoning covers the sibling trap: **"File → Open Recent → `~/designs/arm_v3.f3d`"**
is a real vendor menu holding real customer content. That is why _every_ `menu_path` segment
is checked, not just the first.

Both cases have named tests. If you are writing an ingestion path against a per-document API,
assume it mixes vendor and customer content until you have proved otherwise.

---

## What this contract does not do

Honest limits, so nobody over-trusts it:

- **The pattern list is not exhaustive**, and no pattern list could be. A customer part named
  `Bracket` is indistinguishable from a vendor control named `Bracket` by inspection. The
  patterns make the _common_ leak impossible; the **closed column set and the absent
  identifiers** are what make the _uncommon_ one impossible, because a record with no
  reference to a project and no free-form field is not much of a leak even when its label is
  unfortunate.
- **It does not authorise anything.** It is a shape, not an access check. Who may write to the
  store is LANE D's ingestion guard (SOLUS-TU-06).

  **SOLUS-TU-06 must not treat `parseToolKnowledge` as its filter.** An ingestion job walking a
  per-document or per-project API has to allowlist what it reads at the source — by control
  identity, by vendor documentation, by an operator's explicit review — and use these patterns
  only to catch what slips. The budget an attacker has through the prose fields is roughly
  3.6 KB per row (400 label + 400 description + 8 × 400 menu path), and rows are unbounded.
- **It does not review provenance.** `operator_authored` means a human wrote it; the type
  cannot tell whether that human was looking at a customer's screen at the time. That is the
  review-level half of "schema-level and review-level".

---

## Drift control

Fixtures under `packages/shared-types/fixtures/tool-knowledge/` are validated by both halves
(`satisfies` under `tsc`, `model_validate` under `extra="forbid"`), and both test suites
assert the enum vocabularies match member for member.

---

## Changing this contract

Additive within the existing shape — a new `ToolFamily`, a new `ControlEffect`, a new closed
enum — goes through a LANE 0 ticket like any other.

SOLUSDEV-261 amendment, explicitly approved in chat on 2026-09-12: add `code` and
`isaac` to `ToolFamily`, `terminal` to `UiSurface`, and `execute` to `ControlEffect`.
These classify vendor documentation for code tools and external simulation. They
add no command payload, source path, customer identifier or execution authority;
the existing closed fields, prose validation and ingestion guard still apply.
Python/TypeScript vocabularies and persisted CHECK constraints must change together.

**Anything that widens what the type can hold is a security change, not a contract change.**
A new free-text field, an index signature, an untyped map, an id of anything customer-owned,
or a relaxation of the rejection patterns goes to a human before it is written (CLAUDE.md §7:
"if you are ever uncertain whether something is a security risk: stop, flag it, and do not
merge"). The twenty compile-time assertions exist so that such a change cannot land quietly.
