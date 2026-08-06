# Orb ↔ Overlay Handoff Contract

**Ticket:** SOLUSDEV-221 (SOLUS-CTR-06) · **Lane:** LANE 0
**Source:** `packages/shared-types/src/orb-overlay.ts`

---

## Why this exists

The orb lives in **LANE C** and the Guide overlay in **LANE D**, but the orb physically
_leaves the app window and becomes the overlay_. That produced a real cycle: the overlay host
needed the orb, and the confirm/reject loop needed the overlay host.

Defining the handoff as a **message boundary** dissolves it. Neither lane imports the other;
both import this file, and each builds against a stub of the other.

---

## The two channels

```ts
ORB_OVERLAY_CHANNELS = {
  toOverlay: "orb-overlay:to-overlay",
  toOrb: "orb-overlay:to-orb",
};
```

Exported constants, not literals. Today main and preload repeat channel strings independently
and `folder.clone` already maps to a channel named `git:clone` — a rename compiles clean on
both sides. Both processes import these.

> ⚠️ **This lifecycle needs a channel that does not exist yet.** Every IPC path in the app
> today is request/response `ipcRenderer.invoke` (`apps/desktop/src/preload/index.ts`); there
> is no `ipcRenderer.on` / `webContents.send` push channel anywhere. `spawn`, `reposition`,
> `advance` and every overlay→orb message are pushes. Wiring that channel is LANE C/LANE D
> work — this contract defines what travels over it.

---

## The messages

**orb → overlay**

| Type         | Payload                                | Meaning                                             |
| ------------ | -------------------------------------- | --------------------------------------------------- |
| `spawn`      | `handoffId`, `focus`, `step`, `target` | Leave the app window and attach to that tool window |
| `reposition` | `handoffId`, `target`                  | The tool window moved or resized                    |
| `advance`    | `handoffId`, `step`                    | Show the next guide step                            |
| `dismiss`    | `handoffId`, `reason`                  | Stand down                                          |

**overlay → orb**

| Type             | Payload                                | Meaning                            |
| ---------------- | -------------------------------------- | ---------------------------------- |
| `ready`          | `handoffId`                            | Attached and rendering             |
| `step_completed` | `handoffId`, `stepId`                  | The user did the thing             |
| `reclaim`        | `handoffId`, `focus`, `step`, `reason` | Hand control back, **with state**  |
| `dismissed`      | `handoffId`, `reason`                  | Closed, in response to a `dismiss` |
| `failed`         | `handoffId`, `reason`                  | Could not attach                   |

`handoffId` correlates one handoff session end to end.

### The payload

```ts
interface GuideStep {
  readonly stepId: string;
  readonly index: number;
  readonly total: number; // so the overlay can render "2 of 5" with no extra call
  readonly title: string;
  readonly instruction: string;
  readonly control: ControlPointer | null; // null when the step highlights nothing
}

interface ControlPointer {
  readonly tool: ToolFamily;
  readonly controlId: string; // a tool-knowledge control id
  readonly locator: ScreenLocator | null; // normalised 0..1 within the tool window
}

interface ToolWindowRef {
  readonly tool: ToolFamily;
  readonly windowTitle: string;
  readonly displayId: string | null;
  readonly bounds: WindowBounds; // OS pixels
}
```

`ControlPointer` addresses a control **the way the tool-knowledge store addresses it**
([tool-knowledge.md](./tool-knowledge.md)) — same `ToolFamily`, same `controlId` slug, same
normalised `ScreenLocator`. The overlay looks the position up rather than being told it
twice, and `parseOrbToOverlay` rejects a `controlId` the store could never hold.

**`reclaim` carries state, not just a notification.** The orb gets the focus and the step back,
so a user who dismisses the overlay mid-guide returns to an app that knows where they were.

`HandoffEndReason` is closed — `completed | user_dismissed | focus_changed | tool_closed` — so
both lanes branch on the same set.

### Scope note

These payloads are **per-user, in-process, on one machine**, and they may legitimately mention
the user's own design ("select the top face of your bracket"). Nothing here is written to the
shared, every-tenant tool-knowledge store, which may not
([tool-knowledge.md](./tool-knowledge.md)). Do not confuse the two boundaries.

---

## Validation at the process boundary

`parseOrbToOverlay` and `parseOverlayToOrb` throw on anything undeclared: unknown message
type, malformed `handoffId`, a `spawn` with no target, a non-object, a non-finite number in
`bounds`, a `focus` with an unknown domain or an unbounded breadcrumb, and a `locator` outside
0..1 or carrying an undeclared key.

Every field is **rebuilt as a fresh literal**, so an undeclared key on the sender's object
cannot ride along into whatever consumes the message. There is a test asserting the parsed
result shares no object identity with the input — an earlier version returned the sender's own
object for `focus` and `locator`, which made this section false.

`focus.entity.projectId` is a **tenant scope**, and the overlay is the process that attaches
itself to third-party tool windows — the least trustworthy end of this channel. It goes through
`parseFocus` like everything else.

IPC crosses a process boundary, so it is **untrusted input like any other** (CLAUDE.md §7).
The renderer must not be able to hand main a shape it never declared. Both sides parse;
neither trusts.

---

## Building either side against the other's absence

```ts
// LANE C — build the orb with no overlay window in existence
const { orb, overlay } = createLoopbackPorts();
const stub = createStubOverlay(overlay);
orb.subscribe((message) => {
  /* ready, step_completed, reclaim, failed … */
});
orb.send({ type: "spawn", handoffId, focus, step, target });
stub.completeStep();
stub.reclaim("user_dismissed");

// LANE D — build the overlay with no orb
const { orb, overlay } = createLoopbackPorts();
const driver = createStubOrb(orb);
overlay.subscribe((message) => {
  /* spawn, reposition, advance, dismiss */
});
driver.spawn({ handoffId, focus, step, target });
driver.advance(nextStep);
```

`createStubOverlay(port, { failSpawn: "no matching tool window" })` makes the attach fail. A
stub that only ever succeeded would let a consumer ship with no failure path, and attaching to
a foreign window really does fail — wrong display, window closed, permission refused on macOS.

Loopback delivery is **synchronous** so a test need not await a window that does not exist.
The real transport is Electron IPC and is asynchronous: a consumer that depends on synchronous
delivery is depending on the stub, not on the contract.

---

## Changing this contract

Additive (a new message variant, a new optional field on `GuideStep`) via a LANE 0 ticket —
note that a new variant means the other side's `switch` must stay exhaustive, so land it
before either lane needs it. Breaking (renaming a channel, changing `reclaim`'s payload,
removing an end reason) requires LANE C and LANE D merged-up in the same window and is a
founder call. docs/WORKTREES.md §5.
