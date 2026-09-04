# Destructive-Action Gate Contract

**Ticket:** SOLUSDEV-218 (SOLUS-CTR-03) · **Lane:** LANE 0
**TypeScript:** `packages/shared-types/src/action-gate.ts`
**Python:** `packages/api/src/solus_api/contracts/action_gate.py`
**Fixtures:** `packages/shared-types/fixtures/action-gate/`

> **This gate ships.** It landed on `main` with SOLUSDEV-96 (SOLUS-ONS-A5 +
> ONS-UI-01) and was amended by SOLUSDEV-168, which let a turn continue past a
> parked action rather than ending at the first one. Every shape below is read
> from the code, verbatim; where a shape here disagrees with the code cited
> beside it, the code is right and this file is a bug.

---

## Why this exists

The Tool viewport (SOLUS-WS-06) and the Impact widget (SOLUS-IMP-03) both listed
SOLUS-SOLX-01 as a blocker, because both render the approval UI for a destructive action.

Neither needs the dispatcher built. They need the request/response **shape**. Publishing it
here lets LANE B build the diff and approval surface against fixtures while LANE C builds
the dispatcher behind it.

**This contract documents the shipped gate. It does not replace it, and it is not new safety
machinery.** If a shape here disagrees with the code cited beside it, the code is right and
this file is a bug.

---

## Where every shape comes from

| Shape                                                                      | Source                                    |
| -------------------------------------------------------------------------- | ----------------------------------------- |
| `ConfirmationStatus` (incl. `STALE`)                                       | `solus_api/models.py:176-190`             |
| `ToolConfirmation` columns (`args`, `summary`, `preview`, `expires_at`, …) | `solus_api/models.py:654-699`             |
| The decision body                                                          | `solus_api/schemas.py:166-175`            |
| The decide endpoint                                                        | `solus_api/routers/sol.py:446-494`        |
| Park / decide / STALE detection / TTL                                      | `solus_api/agent/confirmations.py`        |
| The streamed `tool_confirmation` event                                     | `solus_api/agent/stream.py:57-81`         |
| `ToolResult` / `ToolError` / `ToolErrorCode`                               | `solus_api/agent/tools/shapes.py` (W0-04) |

---

## The flow

1. SOL proposes a call to a tool whose descriptor sets `requires_confirmation`.
2. The gate **parks** it instead of running it: a `tool_confirmation` row is written with the
   exact `args`, a Solus-authored `summary`, and a `preview` diff. The turn streams a
   `tool_confirmation` event. A one-shot SSE stream cannot block for a click, so the action
   does not run inside this turn.
3. **The turn CONTINUES** (amended SOLUSDEV-168). It used to end here, which discarded the
   round's other results even though they had already executed and capped a task at one
   change per turn. The parked result goes back to the model saying a person now has it,
   that it is not a failure, and not to propose it again — and the turn's park hook dedupes
   by concrete action, so a model that re-proposes gets the same confirmation rather than a
   second card. `MAX_MODEL_ROUNDS` still bounds the turn. **One turn may therefore park
   SEVERAL actions, and a UI must render one card per parked action, not one per turn.**
4. The user decides each via `POST /api/v1/projects/{p}/sol/confirmations/{id}` with a body
   carrying a decision **and nothing else**. Actions are approved **individually**: a batch
   would have to suspend the staleness re-check in step 5 for every step after the first,
   because a dependent write's preview legitimately diverges once its predecessor lands.
5. On approval the tool runs **at decision time**, with the registry rebuilt under the
   deciding user's own scope and the arguments taken from the stored row. The decision is
   recorded back into the conversation, so a later turn knows whether the change landed —
   before SOLUSDEV-168 the transcript said `unauthorized` forever, and SOL believed its own
   approved write had failed.

### The parked event

```ts
interface ToolConfirmationEvent {
  readonly confirmation_id: string;
  readonly tool: string;
  readonly args: Readonly<Record<string, unknown>>;
  readonly summary: string;
  readonly preview: readonly DiffRow[];
}

interface DiffRow {
  readonly label: string;
  readonly before: string | null;
  readonly after: string | null;
}
```

It carries the **concrete action**, not just an id — a user cannot meaningfully approve an
opaque handle.

`DiffRow` is generic across every tool kind by construction: a CAD edit, a firmware flash and
a robot command all render the same three fields. When a tool cannot describe its own change
(no `preview()` method), the rows become **argument rows** — `before` is `null` and `after` is
the stored argument. Those rows are derived from the same dict that executes, so _displayed is
executed_ even for tools with no before/after.

`summary` is **authored by Solus**. For a bridge tool the upstream fork's own `description` is
untrusted text and must never phrase the sentence a human reads before approving something
destructive — a fork could describe a destructive tool as "read-only" and the user would be
approving a lie. The gate prefers the Solus-written `consent_summary`
(`confirmations.py:76-95`).

### The decision

```ts
interface ConfirmationDecisionRequest {
  readonly decision: "approve" | "reject";
}
```

### The outcome

```ts
interface ConfirmationOutcomeEnvelope {
  readonly data: ToolResultPayload; // { call_id, ok, value, error }
}
```

---

## Five properties a UI must respect

**1. Arguments are server-side.** `ToolConfirmation.args` holds exactly what the user was
shown and exactly what executes. The decision body is a `StrictModel` with one field, so a
body carrying its own `args` is a **422**, not a merge. Without this, a user could approve
"change width" and a client execute "change everything" (CLAUDE.md §7).

**2. HTTP 200 does not mean the action ran.** This is the trap.

| Situation                                   | Response                                |
| ------------------------------------------- | --------------------------------------- |
| Non-member of the project                   | **404** (not 403 — no existence oracle) |
| Unknown decision, or a body carrying `args` | **422**                                 |
| Wrong project / wrong user / absent row     | **200**, `ok:false`, `not_found`        |
| Already decided (any non-`pending` status)  | **200**, `ok:false`, `unauthorized`     |
| Expired                                     | **200**, `ok:false`, `unauthorized`     |
| **Rejected by the user**                    | **200**, `ok:false`, `unauthorized`     |
| Stale                                       | **200**, `ok:false`, `unauthorized`     |
| Tool no longer registered                   | **200**, `ok:false`, `not_found`        |
| Approved and executed                       | **200**, `ok:true`, `value`             |

The W0-04 never-raises contract holds all the way through: every failure is `ToolResult`
data. Use `isConfirmationRefused(outcome)`, not the status code.

**3. Single use.** Every status but `pending` is terminal, and the decide query takes a row
lock (`with_for_update`) because the status check is check-then-act — without it two
concurrent approvals both read `pending` and both execute. One approval is not an unlimited
licence to repeat a destructive action.

**4. TTL is 30 minutes**, set at park time and checked lazily at decision time. There is **no
background sweeper**: a confirmation only becomes `expired` when someone tries to decide it.
A UI should not assume a stale-looking card has already been reaped.

**5. `STALE` is not `EXPIRED`.** `STALE` means the user approved, but what the action _would
do_ had changed since it was shown — so nothing ran. It is recomputed at decision time by
comparing the rendered rows stored at park against a fresh preview (`_diverged`,
`confirmations.py:308-323`), which is what makes it a gate guarantee rather than an
Onshape-specific one. Time did not run out; the world moved. Say so differently in the UI:
expired means "ask again", stale means "look again, then ask again".

Only the **requesting user** may decide. A teammate never saw the proposed action.

---

## There is no `amend`

SOLUSDEV-218's acceptance text asks for approve/reject/**amend**. Amend is **not** in this
contract, deliberately.

Amend means the client supplies modified arguments at decision time. That is precisely what
property 1 forbids, and it is the single security property the whole round-trip exists to
provide. A gate with an amend path is not a gate.

**The correct affordance is reject-then-re-propose:** the UI offers "change this", which
sends `{"decision": "reject"}` and asks SOL for a new proposal with the user's adjustment.
The user then approves the new action, having seen it. Same user experience, no hole.

Flagged to the humans in the completion report as a deviation from the ticket text.

---

## Building the approval UI with no backend

`packages/shared-types/fixtures/action-gate/` drives a full flow:

| Fixture                        | Renders                                                 |
| ------------------------------ | ------------------------------------------------------- |
| `pending-with-diff.json`       | An Onshape dimension change — two `before → after` rows |
| `pending-args-only.json`       | A firmware flash — argument rows, `before` all `null`   |
| `outcome-approved.json`        | Success, with a `value`                                 |
| `outcome-rejected.json`        | The user's own rejection (still `ok:false`)             |
| `outcome-expired.json`         | TTL elapsed                                             |
| `outcome-stale.json`           | The effect changed since it was shown                   |
| `outcome-already-decided.json` | Single-use replay refused                               |
| `outcome-tool-gone.json`       | Source disconnected between request and approval        |
| `outcome-not-found.json`       | Wrong project, wrong user, or absent                    |

Wire the card to the two pending fixtures and a picker over the outcomes, and every state the
real gate can produce is reachable without a server.

---

## Drift control

These types have no route yet, so they cannot go through the `make gen-openapi` pipeline.
Instead the **fixtures are the single source**, validated from both sides:

- Python — `packages/api/tests/contracts/test_action_gate.py`, `model_validate` under
  `extra="forbid"`.
- TypeScript — `packages/shared-types/src/action-gate.test.ts`, `satisfies` under `tsc`.

A field added, renamed, or removed on either side breaks one of the two suites. Shapes are
therefore **wire shapes** (snake_case), exactly as the API emits them; a renderer may map to
camelCase locally, but the contract is the wire.

`JsonShapeOf<T>` (`src/json.ts`) exists because `tsc` widens string literals in `.json`
imports. It keeps every field check at compile time and defers only the literal _values_,
which the same test then asserts at runtime against the exported const arrays.

---

## Changing this contract

This one is special: it **tracks** an implementation. If SOLUSDEV-96 changes the gate before
it merges, this contract follows it — it does not hold it. After both are on `main`, the
normal rule applies (docs/WORKTREES.md §5): additive via a LANE 0 ticket, breaking is a
founder call with every consuming lane merged-up in the same window.

Any change that weakens property 1, 3 or 5 is a security change, not a contract change, and
goes to a human (CLAUDE.md §7).
