# Widget Framework Contract

**Ticket:** SOLUSDEV-216 (SOLUS-CTR-01) · **Lane:** LANE 0
**Source:** `packages/shared-types/src/widget.ts` · **Loader:** `apps/desktop/src/renderer/src/widgets/discover.ts`
**Reference widget:** `apps/desktop/src/renderer/src/widgets/_reference/`

---

## Why this exists

Six lanes ship widgets: LANE B (parts, tool viewport, impact, map), LANE H (Live Bench),
LANE I (errors), LANE J (checkers), LANE K (environment). Every one of them was waiting on
the workspace canvas.

None of them needed it. A widget needs to know the **shape** it must satisfy, not to have
the thing that renders it. This contract is that shape, and the reference widget proves the
claim: it builds, renders and passes tests with **no canvas in the repo**.

---

## The load-bearing decision: manifest-based self-registration

Each widget declares itself in a `widget.manifest.ts` **inside its own directory**.
Discovery is a glob import. There is:

- **no central registry file**
- **no switch statement**
- **no array in a shared module**

That is not a style preference. Any of those three is a file every lane edits every time a
widget is added — six lanes, one file, a merge conflict per widget, forever. The glob makes
adding a widget a _create_, never an _edit_, so two lanes adding two widgets touch two
disjoint directories.

The only shared thing a new widget consumes is the **id namespace**, and a collision there
is caught loudly at discovery, naming both files.

---

## The interface

```ts
interface WidgetProps {
  readonly focus: Focus | null;
  readonly onFocusChange: (focus: Focus | null) => void;
  readonly onStateChange?: (state: WidgetRenderState) => void;
}

type Widget = ComponentType<WidgetProps>;
type WidgetRenderState = "loading" | "empty" | "error" | "ready";
```

Three props, and that is the whole surface. A widget needing more reaches for the typed API
client or its own store — widening the prop bag would make every other lane satisfy a
requirement it does not have.

**A widget never writes to the focus store.** It reports through `onFocusChange`, and the
canvas decides. That is what keeps focus changes routable, loggable, and undoable. Use
`descend()` from [focus.md](./focus.md) to build the next focus; it records the traversal
step so the breadcrumb stays honest.

**All four render states are yours to render.** A widget that has only ever rendered data
has simply not met an empty project or a failed fetch yet. Naming the states in the contract
is what stops five lanes inventing five spinners. `onStateChange` is optional and exists so
the canvas can show slot chrome without reaching inside the widget.

### Sizing hints

```ts
type WidgetSlotSize = "compact" | "standard" | "wide" | "full";

interface WidgetSizeHint {
  readonly preferred: WidgetSlotSize;
  readonly minimum?: WidgetSlotSize; // below this, the canvas may hide it
  readonly resizable?: boolean; // default true
}
```

A coarse slot, deliberately — **not** a grid measurement. The grid is LANE B's to design, and
a widget guessing at column counts would foreclose it. This is a hint the canvas may override.

### Lifecycle

```ts
interface WidgetLifecycle {
  readonly mount?: () => void | Promise<void>;
  readonly unmount?: () => void | Promise<void>;
}
```

Optional, and most widgets will never define it. **React's `useEffect` cleanup covers the
ordinary case and you should use it.** These hooks exist for a resource that must be held
before first paint or across a remount — a Live Bench socket, an overlay window. The
contract's real lifecycle obligation is simpler: **be remount-safe.** The canvas may unmount
and remount a widget on any layout change.

---

## The manifest

```ts
// apps/desktop/src/renderer/src/widgets/<your-widget>/widget.manifest.ts
import type { WidgetManifest } from "@solus/shared-types";
import { YourWidget } from "./YourWidget";

const manifest: WidgetManifest = {
  id: "impact", // stable lowercase slug, unique across ALL lanes
  title: "Impact", // shown in widget chrome and the picker
  domains: ["electrical", "code"], // [] means "relevant everywhere"
  size: { preferred: "wide" },
  component: YourWidget,
};

export default manifest;
```

It must be the **default export**. `id` must match `/^[a-z][a-z0-9-]*$/` — it ends up in
saved layouts and telemetry, so it is a stable identifier, not a label.

---

## Discovery

`discover.ts` is a single `import.meta.glob('./*/widget.manifest.ts', { eager: true })` handed
straight to `collectManifests`. It names no widget, so it is never edited when one is added.

`collectManifests` takes the **result** of the glob, not a glob pattern. `import.meta.glob`
is a Vite transform, so a loader that called it could only run inside the bundler. Passing
the modules in keeps `collectManifests` pure, keeps `@solus/shared-types` framework-free, and
makes the entire discovery rule testable with a plain object — which is exactly what
`widget.test.ts` does.

**It throws** on a malformed manifest, a missing default export, or a duplicate id, naming
the offending module path. These are in-repo build-time errors, not untrusted input. A loader
that silently skipped a broken widget would ship a workspace with one mysteriously missing
and no way to find out why.

Order is **id-sorted**, not glob order: bundlers make no ordering promise, and a canvas
rendering in load order would reshuffle its layout between builds.

---

## Building a widget before the canvas exists

This is the point of the ticket, so here is the whole recipe:

1. `mkdir apps/desktop/src/renderer/src/widgets/<your-widget>/` — your lane owns it
   (`CODEOWNERS`); no other lane's file is involved.
2. Write the component against `WidgetProps`.
3. Write `widget.manifest.ts` with a default export.
4. Test by rendering the component directly with the two required props.

`_reference/ReferenceWidget.test.tsx` is that test, and it imports no canvas, no layout and
no shell. If it passes, a lane blocked on LANE B is not actually blocked.

The reference widget also demonstrates the two things people get wrong: an in-flight async
read guarded against a focus change landing mid-flight, and reporting a focus change through
the callback rather than mutating the prop.

---

## Changing this contract

Additive (a new optional prop, a new slot size, a new manifest field with a default) goes
through a LANE 0 ticket. Breaking (renaming a prop, making `onStateChange` required, changing
`id` rules) requires every widget lane merged-up in the same window and is a founder call —
docs/WORKTREES.md §5. A lane never edits this file to unblock itself.
