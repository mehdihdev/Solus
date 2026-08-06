// SOLUSDEV-221 (CTR-06) — the orb ↔ overlay handoff.
//
// The acceptance criterion is "either side can be built and tested against a
// stub of the other". Every test here does exactly that: the orb side is
// exercised with no overlay window in existence, and the overlay side with no
// orb. Nothing in this file opens a BrowserWindow.
import { describe, expect, test, vi } from "vitest";
import type { Focus } from "./focus";
import {
  ORB_OVERLAY_CHANNELS,
  createLoopbackPorts,
  createStubOrb,
  createStubOverlay,
  parseOrbToOverlay,
  parseOverlayToOrb,
  type GuideStep,
  type ToolWindowRef,
} from "./orb-overlay";

const focus: Focus = {
  entity: {
    projectId: "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    entityId: "1f0a2b3c-4d5e-4f60-8a91-b2c3d4e5f601",
  },
  domain: "mechanical",
  label: "motor_mount",
  path: [],
};

const step: GuideStep = {
  stepId: "extrude-the-profile",
  index: 2,
  total: 5,
  title: "Extrude the profile",
  instruction: "Select the closed sketch profile, then press E and enter 6 mm.",
  control: {
    tool: "fusion",
    controlId: "fusion.solid.extrude",
    locator: { x: 0.31, y: 0.06, w: 0.04, h: 0.05 },
  },
};

const target: ToolWindowRef = {
  tool: "fusion",
  windowTitle: "Autodesk Fusion",
  displayId: "display-1",
  bounds: { x: 0, y: 0, width: 1920, height: 1080 },
};

const spawn = { type: "spawn", handoffId: "h1", focus, step, target } as const;

describe("the channel names", () => {
  test("are exported constants, not literals repeated on both sides", () => {
    // Today the app repeats channel strings in preload and main, and
    // `folder.clone` already maps to `git:clone`. A rename compiles clean on
    // both sides — these constants are what stops that here.
    expect(ORB_OVERLAY_CHANNELS.toOverlay).toBe("orb-overlay:to-overlay");
    expect(ORB_OVERLAY_CHANNELS.toOrb).toBe("orb-overlay:to-orb");
  });
});

describe("building the orb against no overlay", () => {
  test("a spawn reaches the stub overlay and comes back ready", () => {
    const { orb, overlay } = createLoopbackPorts();
    createStubOverlay(overlay);
    const seen = vi.fn();
    orb.subscribe(seen);

    orb.send(spawn);

    expect(seen).toHaveBeenCalledWith({ type: "ready", handoffId: "h1" });
  });

  test("the stub reports the step the user finished, then reclaims", () => {
    const { orb, overlay } = createLoopbackPorts();
    const stub = createStubOverlay(overlay);
    const seen = vi.fn();
    orb.subscribe(seen);

    orb.send(spawn);
    stub.completeStep();
    stub.reclaim("user_dismissed");

    expect(seen.mock.calls.map(([m]) => m.type)).toEqual([
      "ready",
      "step_completed",
      "reclaim",
    ]);
    const reclaim = seen.mock.calls[2]![0];
    // The orb gets its state back, not just a notification that it is over.
    expect(reclaim.focus).toEqual(focus);
    expect(reclaim.step?.stepId).toBe("extrude-the-profile");
  });

  test("an overlay that cannot attach fails loudly instead of hanging", () => {
    const { orb, overlay } = createLoopbackPorts();
    createStubOverlay(overlay, { failSpawn: "no matching tool window" });
    const seen = vi.fn();
    orb.subscribe(seen);

    orb.send(spawn);

    expect(seen).toHaveBeenCalledWith({
      type: "failed",
      handoffId: "h1",
      reason: "no matching tool window",
    });
  });

  test("reposition and dismiss need no reply", () => {
    const { orb, overlay } = createLoopbackPorts();
    const stub = createStubOverlay(overlay);
    orb.send(spawn);
    orb.send({
      type: "reposition",
      handoffId: "h1",
      target: { ...target, bounds: { x: 40, y: 0, width: 1600, height: 900 } },
    });
    orb.send({ type: "dismiss", handoffId: "h1", reason: "focus_changed" });

    expect(stub.state).toBe("dismissed");
    expect(stub.lastTarget?.bounds.x).toBe(40);
  });
});

describe("building the overlay against no orb", () => {
  test("the stub orb drives a full handoff", () => {
    const { orb, overlay } = createLoopbackPorts();
    const driver = createStubOrb(orb);
    const seen = vi.fn();
    overlay.subscribe(seen);

    driver.spawn({ handoffId: "h9", focus, step, target });
    driver.advance({ ...step, stepId: "fillet-the-edge", index: 3 });
    driver.dismiss("completed");

    expect(seen.mock.calls.map(([m]) => m.type)).toEqual([
      "spawn",
      "advance",
      "dismiss",
    ]);
    expect(seen.mock.calls[1]![0].step.stepId).toBe("fillet-the-edge");
  });
});

describe("the messages are validated at the process boundary", () => {
  test("a well-formed message round-trips", () => {
    expect(parseOrbToOverlay(JSON.parse(JSON.stringify(spawn)))).toMatchObject({
      type: "spawn",
    });
    expect(parseOverlayToOrb({ type: "ready", handoffId: "h1" })).toMatchObject(
      { type: "ready" },
    );
  });

  test.each([
    ["an unknown type", { type: "explode", handoffId: "h1" }],
    ["a missing handoffId", { type: "ready" }],
    ["a spawn with no target", { type: "spawn", handoffId: "h1", focus, step }],
    ["not an object", "spawn"],
    ["null", null],
  ])("rejects %s", (_why, message) => {
    // IPC crosses a process boundary, so it is untrusted input like any other
    // (CLAUDE.md §7) — the renderer must not be able to hand main a shape it
    // did not declare.
    expect(() => parseOrbToOverlay(message)).toThrow();
    expect(() => parseOverlayToOrb(message)).toThrow();
  });

  test("a spawn step must reference a control the tool-knowledge store can address", () => {
    const bad = {
      ...spawn,
      step: {
        ...step,
        control: { tool: "fusion", controlId: "Extrude!", locator: null },
      },
    };
    expect(() => parseOrbToOverlay(JSON.parse(JSON.stringify(bad)))).toThrow();
  });

  test("a guide step with no control is legal — not every step highlights something", () => {
    const noControl = { ...spawn, step: { ...step, control: null } };
    expect(
      parseOrbToOverlay(JSON.parse(JSON.stringify(noControl))),
    ).toMatchObject({ type: "spawn" });
  });
});

// ── SOLUSDEV-216 security review: focus and locator crossed the process boundary
// as `as` casts while the doc claimed "both sides parse; neither trusts". ──

describe("the IPC boundary actually parses what it claimed to", () => {
  const spawnWith = (patch: Record<string, unknown>) =>
    JSON.parse(JSON.stringify({ ...spawn, ...patch }));

  test.each([
    ["a focus that is not an object", { focus: "not-an-object" }],
    ["a focus with an unknown domain", { focus: { ...focus, domain: "thermal" } }],
    ["a focus missing its tenant scope", { focus: { ...focus, entity: { entityId: "x" } } }],
    [
      "a focus whose breadcrumb is unbounded",
      { focus: { ...focus, path: Array.from({ length: 40 }, () => ({ entity: focus.entity, domain: "code", relation: "r" })) } },
    ],
  ])("rejects %s", (_why, patch) => {
    expect(() => parseOrbToOverlay(spawnWith(patch))).toThrow();
  });

  test("rejects a locator outside 0..1 or carrying an image", () => {
    const bad = (locator: unknown) =>
      spawnWith({ step: { ...step, control: { ...step.control, locator } } });
    expect(() => parseOrbToOverlay(bad({ x: 0, y: 0, w: 1e9, h: 1e9 }))).toThrow();
    expect(() => parseOrbToOverlay(bad({ x: 0, y: 0, w: 1, h: 1, image_b64: "iVBOR" }))).toThrow();
  });

  test("rejects Infinity in the window bounds", () => {
    expect(() =>
      parseOrbToOverlay(spawnWith({ target: { ...target, bounds: { x: 0, y: 0, width: Infinity, height: 1 } } })),
    ).toThrow(/finite/);
  });

  test("rejects a handoffId used as a payload", () => {
    expect(() => parseOrbToOverlay(spawnWith({ handoffId: "x".repeat(2000) }))).toThrow();
  });

  test("the parsed message shares no object identity with the input", () => {
    // The real test for "cannot hand main a shape it never declared": the old
    // cast returned the sender's object, so undeclared keys rode along.
    const input = spawnWith({});
    input.focus.smuggled = "customer content";
    const parsed = parseOrbToOverlay(input);
    expect(parsed).not.toBe(input);
    expect(parsed.type === "spawn" && parsed.focus).not.toBe(input.focus);
    expect(parsed.type === "spawn" && JSON.stringify(parsed.focus)).not.toContain("smuggled");
  });
});
