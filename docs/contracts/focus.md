# Shared-Focus Contract

**Ticket:** SOLUSDEV-217 (SOLUS-CTR-02) · **Lane:** LANE 0 · **Source:** `packages/shared-types/src/focus.ts`
**Status:** contract + reference implementation on `main`. The real engine is SOLUS-WS-01 (LANE B).

---

## Why this exists

SOLUS-WS-01 (the shared-focus engine) and SOLUS-WS-03 (the widget canvas) each listed the
other as a dependency. That is a genuine deadlock — neither could start.

It was also wrong. They do not depend on each other's **code**; they both depend on the
**shape of focus**. Publishing the shape here dissolves the cycle: WS-01 implements
`FocusStore` over the real engine, WS-03 consumes the interface, and either can be built
first. In the meantime `createFocusStore()` is a working store both can develop against.

---

## What focus is

The workspace's one piece of ambient state: **what the user is looking at**. Every widget
receives it; any widget may change it. A widget that needs private state keeps it privately
— focus is only for the thing the whole workspace agrees on.

```ts
interface Focus {
  readonly entity: EntityRef; // the graph entity in view
  readonly domain: Domain; // which world it lives in
  readonly label?: string; // display name, cached from the graph
  readonly path: readonly FocusStep[]; // how the user got here, oldest first
}

interface EntityRef {
  readonly projectId: string; // project.id — the tenant scope
  readonly entityId: string; // graph_entity.id
}

interface FocusStep {
  readonly entity: EntityRef;
  readonly domain: Domain;
  readonly label?: string;
  readonly relation: string; // graph_edge.relation_type traversed FROM this step
}

type Domain = "code" | "electrical" | "mechanical" | "simulation" | "runtime";
```

### Three decisions worth knowing

**`projectId` travels with the entity, not ambiently.** A focus is scoped to one project.
Carrying the scope inside the value is what lets `descend()` refuse a cross-project trail
instead of trusting whatever context the caller happened to be in. Cross-tenant isolation is
the highest-severity invariant in this codebase (CLAUDE.md §7); a focus that could silently
span two projects would carry another team's entity into a widget's render path.

**`path` excludes the current entity.** A breadcrumb renders `[...focus.path, focus]`. An
empty path means the user landed here directly — search, deep link, or a widget's own list —
which is a normal state, not a missing one.

**`relation` points forward.** `path[i].relation` is the edge traversed from `path[i]` toward
`path[i+1]` (or toward the focus, for the last step). Defining it forward rather than
backward means every step has one; there is no null-origin case for consumers to handle.

**`Domain` mirrors `solus_api.models.Domain`** (ADR-027) — exactly those five spellings.
Adding a domain is a graph-wide decision, not a frontend one.

---

## The store

```ts
interface FocusStore {
  get(): Focus | null;
  set(focus: Focus | null): void;
  subscribe(listener: (focus: Focus | null) => void): () => void;
}
```

Three methods, deliberately. A store that also owned selection, history, or layout would be
a second thing six lanes have to agree on before any of them can start.

`createFocusStore(initial?)` is the **reference implementation**, and its behaviour is the
contract WS-01 must honour:

| Behaviour                                                                 | Why                                                                                                          |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| A no-op `set` does not notify                                             | A widget re-emitting the focus it was handed must not loop the app                                           |
| Reaching the same entity by a **different relation** _does_ notify        | The trail is state, not decoration — a breadcrumb that did not update would misreport how the user got there |
| Listeners are notified from a snapshot                                    | A listener that unsubscribes during delivery must not cause its neighbour to be skipped                      |
| A throwing listener does not stop the others, and the state still commits | One broken widget must not freeze the workspace                                                              |
| `unsubscribe()` is idempotent                                             | Double-cleanup in a React effect is normal, not an error                                                     |

It has no dependency on Zustand or any store library. The whole implementation is shorter
than the argument for adding one, and keeping `shared-types` framework-free means a lane can
import it into a plain Node test.

---

## `descend` — the one navigation helper

```ts
const next = descend(currentFocus, {
  entity: driverRef,
  domain: "electrical",
  label: "TB6612FNG",
  relation: "drives",
});
```

Appends the current focus to the trail and makes the target the new focus. Pure — the input
is never mutated. It **throws** if the target is in a different project.

This exists because every widget offering "jump to this" needs exactly this operation, and
six lanes hand-rolling it produces six subtly different breadcrumbs. It is the only helper;
anything richer (history, back/forward, pinning) belongs in WS-01.

---

## Using it before WS-01 lands

```ts
import { createFocusStore, descend, type Focus } from "@solus/shared-types";

const focus = createFocusStore(); // in a test, or a lane's dev harness
focus.subscribe((f) => render(f));
focus.set({
  entity: ref,
  domain: "mechanical",
  label: "drive_motor",
  path: [],
});
```

A widget never constructs a store. It receives the current focus as a prop and reports
changes through its `onFocusChange` callback — see [widget.md](./widget.md).

---

## Changing this contract

Additive changes (a new optional field, a new `Domain` member once ADR-027 adds one) go
through a LANE 0 ticket and land on `main`; lanes pick them up on their next merge.

Breaking changes — renaming a field, making `label` required, changing `path` semantics —
require every consuming lane merged-up in the same window and are a founder call
(docs/WORKTREES.md §5). A lane never edits this file to unblock itself.
