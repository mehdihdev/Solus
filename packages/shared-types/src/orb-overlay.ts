// SOLUSDEV-221 (CTR-06) — the orb ↔ overlay handoff contract.
//
// The orb lives in LANE C and the Guide overlay in LANE D, but the orb
// physically LEAVES the app window and becomes the overlay. That produced a
// cycle: the overlay host needed the orb, and the confirm/reject loop needed the
// overlay host. Defining the handoff as a message boundary means both lanes
// build independently and meet here.
//
// Two channels, two message unions, and a loopback transport so either side can
// be built and tested against a stub of the other — with no BrowserWindow, no
// Electron, and no other lane's code.
//
// SCOPE NOTE, because this contract sits next to tool-knowledge.ts: these
// payloads are PER-USER, in-process, on one machine. They may legitimately
// mention the user's own design. Nothing here is written to the shared
// tool-knowledge store, which may not (docs/contracts/tool-knowledge.md).
//
// See docs/contracts/orb-overlay.md.

import type { Focus } from "./focus";
import { parseFocus } from "./focus";
import type { ScreenLocator, ToolFamily } from "./tool-knowledge";
import { TOOL_FAMILIES, parseLocator } from "./tool-knowledge";

/**
 * The IPC channel names, exported as constants.
 *
 * Today main and preload repeat channel string literals independently, and
 * `folder.clone` already maps to a channel called `git:clone` — a rename
 * compiles clean on both sides. Both processes import these instead.
 */
export const ORB_OVERLAY_CHANNELS = {
  toOverlay: "orb-overlay:to-overlay",
  toOrb: "orb-overlay:to-orb",
} as const;

/** OS-pixel bounds of a window on the desktop. */
export interface WindowBounds {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** The tool window the overlay attaches itself to. */
export interface ToolWindowRef {
  readonly tool: ToolFamily;
  readonly windowTitle: string;
  /** Null on a single-display setup, or when the platform does not report it. */
  readonly displayId: string | null;
  readonly bounds: WindowBounds;
}

/** The control a guide step is about, addressed the way the tool-knowledge store addresses it. */
export interface ControlPointer {
  readonly tool: ToolFamily;
  readonly controlId: string;
  /** Normalised 0..1 box within the tool window; null when the position is unknown. */
  readonly locator: ScreenLocator | null;
}

/** One step of a guide, as the overlay renders it. */
export interface GuideStep {
  readonly stepId: string;
  readonly index: number;
  readonly total: number;
  readonly title: string;
  readonly instruction: string;
  /** Null when the step highlights nothing — "now look at the result" is a step. */
  readonly control: ControlPointer | null;
}

/** Why a handoff ended. Closed so both lanes branch on the same set. */
export type HandoffEndReason =
  | "completed"
  | "user_dismissed"
  | "focus_changed"
  | "tool_closed";

/** orb → overlay. */
export type OrbToOverlay =
  | {
      readonly type: "spawn";
      readonly handoffId: string;
      readonly focus: Focus | null;
      readonly step: GuideStep;
      readonly target: ToolWindowRef;
    }
  | {
      readonly type: "reposition";
      readonly handoffId: string;
      readonly target: ToolWindowRef;
    }
  | {
      readonly type: "advance";
      readonly handoffId: string;
      readonly step: GuideStep;
    }
  | {
      readonly type: "dismiss";
      readonly handoffId: string;
      readonly reason: HandoffEndReason;
    };

/** overlay → orb. */
export type OverlayToOrb =
  | { readonly type: "ready"; readonly handoffId: string }
  | {
      readonly type: "step_completed";
      readonly handoffId: string;
      readonly stepId: string;
    }
  | {
      readonly type: "reclaim";
      readonly handoffId: string;
      readonly focus: Focus | null;
      readonly step: GuideStep | null;
      readonly reason: HandoffEndReason;
    }
  | {
      readonly type: "dismissed";
      readonly handoffId: string;
      readonly reason: HandoffEndReason;
    }
  | {
      readonly type: "failed";
      readonly handoffId: string;
      readonly reason: string;
    };

// ── validation ───────────────────────────────────────────────────────────────

const END_REASONS: readonly HandoffEndReason[] = [
  "completed",
  "user_dismissed",
  "focus_changed",
  "tool_closed",
];
const CONTROL_ID_RE = /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/;
/** A correlation id, not a payload. Was accepting any 2000-char string. */
const HANDOFF_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

function obj(raw: unknown, what: string): Record<string, unknown> {
  if (typeof raw !== "object" || raw === null)
    throw new TypeError(`${what}: must be an object`);
  return raw as Record<string, unknown>;
}

/** Every string crossing the IPC boundary is bounded — parse defensively (CLAUDE.md §7). */
const MAX_IPC_STRING = 2000;

function str(value: unknown, what: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${what}: must be a non-empty string`);
  }
  if (value.length > MAX_IPC_STRING) {
    throw new TypeError(`${what}: exceeds the ${MAX_IPC_STRING}-character IPC limit`);
  }
  return value;
}

function num(value: unknown, what: string): number {
  // Number.isFinite, not !isNaN: `{x: Infinity, width: 1e12}` used to parse, and
  // these numbers position an always-on-top window.
  if (typeof value !== "number" || !Number.isFinite(value))
    throw new TypeError(`${what}: must be a finite number`);
  return value;
}

/** A count that has to be renderable as "2 of 5". */
function step(value: unknown, what: string): number {
  const n = num(value, what);
  if (!Number.isInteger(n) || n < 0 || n > 999) {
    throw new TypeError(`${what}: must be an integer in 0..999`);
  }
  return n;
}

function bounds(raw: unknown): WindowBounds {
  const b = obj(raw, "bounds");
  return {
    x: num(b.x, "bounds.x"),
    y: num(b.y, "bounds.y"),
    width: num(b.width, "bounds.width"),
    height: num(b.height, "bounds.height"),
  };
}

function target(raw: unknown): ToolWindowRef {
  const t = obj(raw, "target");
  if (!(TOOL_FAMILIES as readonly string[]).includes(t.tool as string)) {
    throw new TypeError(
      `target.tool: must be one of ${TOOL_FAMILIES.join(", ")}`,
    );
  }
  return {
    tool: t.tool as ToolFamily,
    windowTitle: str(t.windowTitle, "target.windowTitle"),
    displayId:
      t.displayId === null || t.displayId === undefined
        ? null
        : str(t.displayId, "target.displayId"),
    bounds: bounds(t.bounds),
  };
}

function control(raw: unknown): ControlPointer | null {
  if (raw === null || raw === undefined) return null;
  const c = obj(raw, "step.control");
  if (!(TOOL_FAMILIES as readonly string[]).includes(c.tool as string)) {
    throw new TypeError("step.control.tool: unknown tool family");
  }
  const id = str(c.controlId, "step.control.controlId");
  if (!CONTROL_ID_RE.test(id)) {
    // The overlay looks this up in the tool-knowledge store; an id that store
    // could never hold is a bug in the caller, not a highlight to attempt.
    throw new TypeError(
      "step.control.controlId: must be a tool-knowledge control id slug",
    );
  }
  return {
    tool: c.tool as ToolFamily,
    controlId: id,
    locator: parseLocator(c.locator, "step.control.locator"),
  };
}

function guideStep(raw: unknown): GuideStep {
  const s = obj(raw, "step");
  return {
    stepId: str(s.stepId, "step.stepId"),
    index: step(s.index, "step.index"),
    total: step(s.total, "step.total"),
    title: str(s.title, "step.title"),
    instruction: str(s.instruction, "step.instruction"),
    control: control(s.control),
  };
}

function endReason(value: unknown, what: string): HandoffEndReason {
  if (!END_REASONS.includes(value as HandoffEndReason)) {
    throw new TypeError(`${what}: must be one of ${END_REASONS.join(", ")}`);
  }
  return value as HandoffEndReason;
}

/**
 * Parse a message arriving on `ORB_OVERLAY_CHANNELS.toOverlay`, or throw.
 *
 * IPC crosses a process boundary, so it is untrusted input like any other
 * (CLAUDE.md §7): the renderer must not be able to hand main a shape it never
 * declared. Both processes parse; neither trusts.
 */
export function parseOrbToOverlay(raw: unknown): OrbToOverlay {
  const m = obj(raw, "message");
  const handoffId = str(m.handoffId, "handoffId");
  if (!HANDOFF_ID_RE.test(handoffId)) {
    throw new TypeError("handoffId: must be a short opaque correlation id");
  }
  switch (m.type) {
    case "spawn":
      return {
        type: "spawn",
        handoffId,
        focus: parseFocus(m.focus),
        step: guideStep(m.step),
        target: target(m.target),
      };
    case "reposition":
      return { type: "reposition", handoffId, target: target(m.target) };
    case "advance":
      return { type: "advance", handoffId, step: guideStep(m.step) };
    case "dismiss":
      return {
        type: "dismiss",
        handoffId,
        reason: endReason(m.reason, "reason"),
      };
    default:
      throw new TypeError(
        `unknown orb→overlay message type: ${String(m.type)}`,
      );
  }
}

/** Parse a message arriving on `ORB_OVERLAY_CHANNELS.toOrb`, or throw. */
export function parseOverlayToOrb(raw: unknown): OverlayToOrb {
  const m = obj(raw, "message");
  const handoffId = str(m.handoffId, "handoffId");
  if (!HANDOFF_ID_RE.test(handoffId)) {
    throw new TypeError("handoffId: must be a short opaque correlation id");
  }
  switch (m.type) {
    case "ready":
      return { type: "ready", handoffId };
    case "step_completed":
      return {
        type: "step_completed",
        handoffId,
        stepId: str(m.stepId, "stepId"),
      };
    case "reclaim":
      return {
        type: "reclaim",
        handoffId,
        focus: parseFocus(m.focus),
        step:
          m.step === null || m.step === undefined ? null : guideStep(m.step),
        reason: endReason(m.reason, "reason"),
      };
    case "dismissed":
      return {
        type: "dismissed",
        handoffId,
        reason: endReason(m.reason, "reason"),
      };
    case "failed":
      return { type: "failed", handoffId, reason: str(m.reason, "reason") };
    default:
      throw new TypeError(
        `unknown overlay→orb message type: ${String(m.type)}`,
      );
  }
}

// ── stubs: build either side against the other's absence ─────────────────────

/** One end of the handoff: send its own messages, receive the other side's. */
export interface OrbOverlayPort<Out, In> {
  send(message: Out): void;
  subscribe(listener: (message: In) => void): () => void;
}

export type OrbPort = OrbOverlayPort<OrbToOverlay, OverlayToOrb>;
export type OverlayPort = OrbOverlayPort<OverlayToOrb, OrbToOverlay>;

function channel<A, B>(): [OrbOverlayPort<A, B>, OrbOverlayPort<B, A>] {
  const listenersA = new Set<(m: B) => void>();
  const listenersB = new Set<(m: A) => void>();
  const deliver = <M>(listeners: Set<(m: M) => void>, message: M): void => {
    for (const listener of [...listeners]) listener(message);
  };
  return [
    {
      send: (m) => deliver(listenersB, m),
      subscribe: (l) => (listenersA.add(l), () => void listenersA.delete(l)),
    },
    {
      send: (m) => deliver(listenersA, m),
      subscribe: (l) => (listenersB.add(l), () => void listenersB.delete(l)),
    },
  ];
}

/**
 * An in-memory pair of ports. Wire a stub to one end and build against the other.
 *
 * Synchronous delivery on purpose: a test should not have to await a window
 * that does not exist. The real transport is Electron IPC, which is async — a
 * consumer that depends on synchronous delivery is depending on the stub.
 */
export function createLoopbackPorts(): { orb: OrbPort; overlay: OverlayPort } {
  const [orb, overlay] = channel<OrbToOverlay, OverlayToOrb>();
  return { orb, overlay };
}

/** A stub overlay: enough behaviour for LANE C to build the orb with no overlay window. */
export function createStubOverlay(
  port: OverlayPort,
  options: { failSpawn?: string } = {},
): {
  state: "idle" | "ready" | "dismissed";
  lastTarget: ToolWindowRef | null;
  lastStep: GuideStep | null;
  completeStep(): void;
  reclaim(reason: HandoffEndReason): void;
} {
  const stub = {
    state: "idle" as "idle" | "ready" | "dismissed",
    lastTarget: null as ToolWindowRef | null,
    lastStep: null as GuideStep | null,
    handoffId: "",
    focus: null as Focus | null,
    completeStep(): void {
      if (stub.lastStep === null)
        throw new Error("stub overlay: no active step");
      port.send({
        type: "step_completed",
        handoffId: stub.handoffId,
        stepId: stub.lastStep.stepId,
      });
    },
    reclaim(reason: HandoffEndReason): void {
      port.send({
        type: "reclaim",
        handoffId: stub.handoffId,
        focus: stub.focus,
        step: stub.lastStep,
        reason,
      });
      stub.state = "dismissed";
    },
  };

  port.subscribe((message) => {
    switch (message.type) {
      case "spawn":
        stub.handoffId = message.handoffId;
        stub.focus = message.focus;
        stub.lastStep = message.step;
        stub.lastTarget = message.target;
        if (options.failSpawn !== undefined) {
          // A stub that silently did nothing would let a consumer ship without
          // a failure path; attaching to a foreign window really does fail.
          port.send({
            type: "failed",
            handoffId: message.handoffId,
            reason: options.failSpawn,
          });
          return;
        }
        stub.state = "ready";
        port.send({ type: "ready", handoffId: message.handoffId });
        return;
      case "reposition":
        stub.lastTarget = message.target;
        return;
      case "advance":
        stub.lastStep = message.step;
        return;
      case "dismiss":
        stub.state = "dismissed";
        port.send({
          type: "dismissed",
          handoffId: message.handoffId,
          reason: message.reason,
        });
        return;
    }
  });

  return stub;
}

/** A stub orb: enough behaviour for LANE D to build the overlay with no orb. */
export function createStubOrb(port: OrbPort): {
  spawn(input: {
    handoffId: string;
    focus: Focus | null;
    step: GuideStep;
    target: ToolWindowRef;
  }): void;
  reposition(target: ToolWindowRef): void;
  advance(step: GuideStep): void;
  dismiss(reason: HandoffEndReason): void;
} {
  let handoffId = "";
  return {
    spawn(input) {
      handoffId = input.handoffId;
      port.send({ type: "spawn", ...input });
    },
    reposition(target_) {
      port.send({ type: "reposition", handoffId, target: target_ });
    },
    advance(step) {
      port.send({ type: "advance", handoffId, step });
    },
    dismiss(reason) {
      port.send({ type: "dismiss", handoffId, reason });
    },
  };
}
