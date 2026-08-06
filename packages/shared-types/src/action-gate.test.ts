// SOLUSDEV-218 (CTR-03) — the destructive-action gate contract.
//
// TWO JOBS. (1) Assert the shared fixtures satisfy the TS types — the other half
// of the drift guard, whose Python twin is packages/api/tests/contracts/
// test_action_gate.py validating the SAME files under extra="forbid". Either
// side changing shape breaks one of the two suites. (2) Assert a UI can drive a
// full approval flow from fixtures alone, with no backend.
import { describe, expect, test } from "vitest";
import alreadyDecided from "../fixtures/action-gate/outcome-already-decided.json";
import approved from "../fixtures/action-gate/outcome-approved.json";
import expired from "../fixtures/action-gate/outcome-expired.json";
import notFound from "../fixtures/action-gate/outcome-not-found.json";
import rejected from "../fixtures/action-gate/outcome-rejected.json";
import stale from "../fixtures/action-gate/outcome-stale.json";
import toolGone from "../fixtures/action-gate/outcome-tool-gone.json";
import argsOnly from "../fixtures/action-gate/pending-args-only.json";
import withDiff from "../fixtures/action-gate/pending-with-diff.json";
import type { JsonShapeOf } from "./json";
import {
  CONFIRMATION_DECISIONS,
  CONFIRMATION_STATUSES,
  CONFIRMATION_TTL_MINUTES,
  confirmationDecisionPath,
  isConfirmationRefused,
  type ConfirmationOutcomeEnvelope,
  type ToolConfirmationEvent,
} from "./action-gate";

// The `satisfies` is the assertion: if a fixture gains a field the type does not
// have, or loses one it requires, `tsc` fails before any test runs. JsonShapeOf
// widens only the string-literal unions (JSON imports lose literal types); the
// values themselves are asserted below against the exported const arrays.
const PENDING = [
  withDiff,
  argsOnly,
] satisfies JsonShapeOf<ToolConfirmationEvent>[];
const OUTCOMES = [
  approved,
  rejected,
  expired,
  stale,
  alreadyDecided,
  toolGone,
  notFound,
] satisfies JsonShapeOf<ConfirmationOutcomeEnvelope>[];

const TOOL_ERROR_CODES = [
  "invalid_args",
  "not_found",
  "tool_error",
  "timeout",
  "unauthorized",
  "unavailable",
];

describe("the shipped statuses and decisions", () => {
  test("statuses match solus_api.models.ConfirmationStatus", () => {
    expect(CONFIRMATION_STATUSES).toEqual([
      "pending",
      "approved",
      "rejected",
      "expired",
      "stale",
    ]);
  });

  test("a decision is approve or reject — there is no amend", () => {
    // Amend would let a client supply arguments at decision time, which destroys
    // the whole security property of the round-trip. See docs/contracts/action-gate.md.
    expect(CONFIRMATION_DECISIONS).toEqual(["approve", "reject"]);
  });

  test("the TTL matches the server's CONFIRMATION_TTL", () => {
    expect(CONFIRMATION_TTL_MINUTES).toBe(30);
  });
});

describe("confirmationDecisionPath", () => {
  test("builds the shipped route", () => {
    expect(confirmationDecisionPath("proj-1", "conf-2")).toBe(
      "/api/v1/projects/proj-1/sol/confirmations/conf-2",
    );
  });

  test("escapes its segments", () => {
    expect(confirmationDecisionPath("a/b", "c d")).toBe(
      "/api/v1/projects/a%2Fb/sol/confirmations/c%20d",
    );
  });
});

describe("rendering an approval card from fixtures alone", () => {
  test("a diff-carrying action shows before -> after rows", () => {
    const event = PENDING[0]!;
    expect(event.preview).toHaveLength(2);
    expect(event.preview[0]).toEqual({
      label: "motor_mount_width",
      before: "58.0 mm",
      after: "62.0 mm",
    });
  });

  test("an action with no describable change still shows what it will run with", () => {
    // A flash, a shell command and a robot move do not REPLACE a value, so the
    // rows are argument rows: before is null, after is the stored argument.
    const event = PENDING[1]!;
    expect(event.preview.every((row) => row.before === null)).toBe(true);
    expect(event.preview.map((row) => row.label)).toEqual([
      "board",
      "port",
      "sketch",
    ]);
  });

  test("every pending fixture carries the concrete action, not just an id", () => {
    for (const event of PENDING) {
      expect(event.summary.length).toBeGreaterThan(0);
      expect(Object.keys(event.args).length).toBeGreaterThan(0);
      expect(event.tool).toMatch(/\S/);
    }
  });
});

describe("reading an outcome", () => {
  test("only the approval fixture succeeded", () => {
    expect(OUTCOMES.filter((o) => o.data.ok)).toHaveLength(1);
    expect(approved.data.value).not.toBeNull();
  });

  test("every refusal carries an error and no value", () => {
    for (const outcome of OUTCOMES.filter((o) => !o.data.ok)) {
      expect(outcome.data.error).not.toBeNull();
      expect(outcome.data.value).toBeNull();
    }
  });

  test("a rejection is a refusal, not a success", () => {
    // The trap: HTTP 200 does NOT mean the action ran.
    expect(isConfirmationRefused(rejected)).toBe(true);
    expect(isConfirmationRefused(approved)).toBe(false);
  });

  test("stale and expired are distinguishable to a UI", () => {
    expect(stale.data.error?.message).toMatch(/has changed since it was shown/);
    expect(expired.data.error?.message).toMatch(/expired/);
  });

  test("every error code is one the agent-tool contract defines", () => {
    // The runtime half of the drift guard: JsonShapeOf deferred the literal
    // values, so they are checked here rather than not at all.
    for (const outcome of OUTCOMES) {
      if (outcome.data.error === null) continue;
      expect(TOOL_ERROR_CODES).toContain(outcome.data.error.code);
    }
  });

  test("no refusal is marked retryable", () => {
    // Retrying a refused destructive action without a fresh approval is exactly
    // what single-use exists to prevent.
    for (const outcome of OUTCOMES)
      expect(outcome.data.error?.retryable ?? false).toBe(false);
  });
});
