# Impact Result Contract

**Ticket:** SOLUSDEV-219 (SOLUS-CTR-04) · **Lane:** LANE 0
**TypeScript:** `packages/shared-types/src/impact.ts`
**Python:** `packages/api/src/solus_api/contracts/impact.py`
**Fixtures:** `packages/shared-types/fixtures/impact/`

---

## Why this exists

Impact is the flagship surface, and it was fully serialised:

> engine (LANE A, backend) → consequence model (LANE A) → widget (LANE B, frontend),
> with the widget _also_ blocked on the SOL lane.

Publishing the **result shape** lets the engine and the widget be built at the same time by
two terminals. The fixtures stand in for the engine until it lands, and they are realistic
enough that the widget is finished — not stubbed — before the first traversal ever runs.

Nothing in this contract computes impact. It is the shape the engine returns.

---

## The shape

```ts
interface ImpactResult {
  readonly focus: ImpactFocus; // what was focused when the change happened
  readonly change: readonly DiffRow[]; // what changed
  readonly computed_at: string;
  readonly truncated: boolean; // the traversal is bounded
  readonly nodes: readonly ImpactNode[]; // [] means "nothing broke" — a real answer
}

interface ImpactNode {
  readonly entity: ImpactEntity;
  readonly label: string;
  readonly domain: Domain;
  readonly severity: Severity; // the worst of its consequences
  readonly distance: number; // hops from the focus; always === path.length
  readonly path: readonly ImpactPathStep[]; // the traversal back to the focus
  readonly consequences: readonly Consequence[];
}

interface Consequence {
  readonly id: string;
  readonly severity: Severity;
  readonly headline: string; // one line, collapsed row
  readonly rationale: string; // why this matters
  readonly evidence: readonly ConsequenceEvidence[]; // where to look
  readonly action: SolAction | null; // what to do about it
}
```

### Node vs consequence

An **`ImpactNode` is an entity the change reaches**; a **`Consequence` is one specific thing
that goes wrong there**. The split matters because one entity often has several problems —
the driver in the hero case is under-rated, and a thermal checker would add a second
consequence to the same node without restructuring anything.

### `severity` reuses the shipped vocabulary

`info | warning | critical`, mirroring `solus_api.checkers.interface.Severity` (CHK-01) —
imported in Python, not re-declared, so it cannot drift. Ordered by **real-world impact, not
style**: `critical` = the robot will not work or may be damaged; `warning` = degraded or
unreliable; `info` = advisory. Sort with `severityRank`, never alphabetically.

`ImpactNode.severity` is the worst of its consequences, **precomputed** so a widget can sort
a table without walking every consequence. The Python model _enforces_ it, along with
`distance == len(path)`: two ways to say the same thing are two ways to be wrong, and a node
whose distance contradicts its own breadcrumb would render a lie.

### `change` reuses the gate's `DiffRow`

The same `{ label, before, after }` the approval card renders. One diff shape in the product:
what a user approves and what an impact was caused by look identical, because they are.

---

## What every row carries

The acceptance criterion is that each row can **jump to focus** and **launch a SOL action**.

**Jump to focus** — `focusOfImpactNode(node)` returns a `Focus` whose `path` is the
traversal that found the node, so after jumping the user's breadcrumb shows _how the change
reached here_. The helper exists for the same reason `descend` does: six lanes hand-rolling
the conversion would produce six different breadcrumbs.

Note the deliberate seam. Impact is a **wire shape** (snake_case, `project_id`), because it
has a Pydantic mirror; `Focus` is **frontend state** (camelCase, `projectId`), because it does
not. `toEntityRef` and `focusOfImpactNode` are the documented bridge, and since the mapping is
also the jump-to-focus operation, it is the deliverable rather than overhead.

**Launch a SOL action** — `Consequence.action` carries `{ tool, label, args }`.

> ⚠️ `args` is a **proposal, not an authorisation.** A destructive tool still routes through
> the confirmation gate, which stores and re-reads its own arguments
> ([action-gate.md](./action-gate.md)). An impact result is data a model may have influenced,
> and model output is untrusted input to whatever consumes it next (CLAUDE.md §7). Nothing on
> an impact row bypasses the gate.

**Every string on this contract is plain text. Render it as a text node — never as HTML, and
never as a bare `href`.** `rationale`, `headline`, `label` and `detail` are model-influenced
prose. `locator` is constrained to a reference form (`sch:U3`, `firmware/motor_ctl.cpp:88`) and
refuses anything URL-shaped, including `javascript:` and `data:` — but a widget still resolves
it itself rather than handing it to the browser. A row is **submitted to SOL as a proposal**;
a widget never invokes `action.tool` against a tool registry directly.

`action` is **nullable, never absent**, so a widget never has to distinguish "no fix exists"
from "the engine forgot the field".

**`rationale` is the point.** It is why-this-matters prose in the user's terms, rendered under
the user's SOL mode (ADR-016). A row that only names a rule is a lint warning; the rationale
is what makes Impact worth reading. The fixture tests assert it is substantially longer than
its headline for exactly that reason.

---

## The hero case

`fixtures/impact/hero-motor-3a.json` — **one mechanical change, three domains**, which is the
product thesis in a single file. The drive motor is swapped for one with a 3.0 A stall current:

| Domain         | Node            | Consequence                                                                                                                              |
| -------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **electrical** | `U3 TB6612FNG`  | `critical` — driver rated 1.2 A continuous; a stalled wheel thermally shuts it down and, repeated, destroys it                           |
| **code**       | `motor_ctl.cpp` | `warning` — the PWM ceiling at `firmware/motor_ctl/motor_ctl.cpp:88` was tuned for the old motor and now silently caps top speed at ~78% |
| **mechanical** | `drive_harness` | `warning` — 24 AWG over a 400 mm bundled run is marginal at 3 A; works on the bench, misbehaves in the enclosure                         |

None of the three is in the file anyone edited. That is the whole feature.

Two more fixtures cover the states a widget must handle and usually forgets:

- `no-impact.json` — `nodes: []`. Nothing downstream broke. A **real answer**, not an empty
  state to apologise for.
- `truncated.json` — `truncated: true`. The engine's traversal is bounded (IMP-01), and a
  widget that does not surface this presents a partial answer as a complete one.

---

## Drift control

These types have no route yet, so they cannot go through `make gen-openapi`. The **fixtures
are the single source**, validated from both sides:

- Python — `packages/api/tests/contracts/test_impact.py`, `model_validate` under `extra="forbid"`.
- TypeScript — `packages/shared-types/src/impact.test.ts`, `satisfies` under `tsc`.

`JsonShapeOf<T>` keeps every field check at compile time and defers only string-literal
_values_, which the same test asserts at runtime against `SEVERITIES`.

---

## Changing this contract

Additive (a new evidence field, a new optional node field) via a LANE 0 ticket. Breaking
(renaming `rationale`, making `action` non-nullable, changing the severity vocabulary — which
would also be a CHK-01 change) requires LANE A and LANE B merged-up in the same window and is
a founder call. docs/WORKTREES.md §5.
