// SOLUSDEV-319 — the team-shared bench view shapes (docs/api/bench-view.md §1–§3).
import { describe, expect, test } from "vitest";
import {
  BENCH_VIEW_LIMITS,
  EMPTY_BENCH_VIEW,
  benchTargetKey,
  isBenchView,
  isBenchViewOp,
  type BenchView,
} from "./bench-view";

const view: BenchView = {
  version: 7,
  display: [
    {
      target: {
        kind: "signal",
        device_id: "usb:5A7A/3",
        signal: "shoulder_lift.position",
      },
      pinned: true,
      hidden: false,
      order: 0,
      unit: "rad",
      limits: { min: -1.6, max: 1.6 },
      plot_group: "Shoulder",
    },
  ],
  derived: [
    {
      id: "0b9f0000-0000-0000-0000-000000000001",
      name: "Lift error",
      expression: 'sig("usb:5A7A/3", "a") - sig("usb:5A7A/3", "b")',
      unit: "deg",
      node_count: 3,
      refs: [
        { device_id: "usb:5A7A/3", signal: "a" },
        { device_id: "usb:5A7A/3", signal: "b" },
      ],
      created_at: "2026-10-31T21:04:11Z",
      updated_at: "2026-10-31T21:04:11Z",
    },
  ],
  updated_at: "2026-10-31T21:04:11Z",
};

describe("isBenchView", () => {
  test("accepts the documented GET /view shape", () => {
    expect(isBenchView(view)).toBe(true);
  });

  test("accepts the empty view before the first write", () => {
    expect(isBenchView(EMPTY_BENCH_VIEW)).toBe(true);
    expect(EMPTY_BENCH_VIEW).toEqual({
      version: 0,
      display: [],
      derived: [],
      updated_at: null,
    });
  });

  test.each([
    ["negative version", { ...view, version: -1 }],
    ["fractional version", { ...view, version: 1.5 }],
    ["display not an array", { ...view, display: {} }],
    [
      "unknown target kind",
      { ...view, display: [{ ...view.display[0], target: { kind: "x" } }] },
    ],
    [
      "limits min >= max",
      {
        ...view,
        display: [{ ...view.display[0], limits: { min: 2, max: 1 } }],
      },
    ],
    [
      "order out of range",
      { ...view, display: [{ ...view.display[0], order: 1024 }] },
    ],
    [
      "derived without refs",
      { ...view, derived: [{ ...view.derived[0], refs: "nope" }] },
    ],
    [
      "too many display entries",
      {
        ...view,
        display: Array.from(
          { length: BENCH_VIEW_LIMITS.maxDisplay + 1 },
          () => view.display[0],
        ),
      },
    ],
    ["null", null],
  ])("rejects %s", (_label, value) => {
    expect(isBenchView(value)).toBe(false);
  });
});

describe("isBenchViewOp", () => {
  test("accepts the three frozen op kinds", () => {
    expect(
      isBenchViewOp({
        kind: "set_display",
        target: { kind: "derived", id: "d1" },
        patch: { pinned: null, limits: null },
      }),
    ).toBe(true);
    expect(
      isBenchViewOp({
        kind: "upsert_derived",
        id: "d1",
        name: "n",
        expression: "1",
        unit: null,
      }),
    ).toBe(true);
    expect(isBenchViewOp({ kind: "delete_derived", id: "d1" })).toBe(true);
  });

  test("rejects an empty patch and unknown kinds", () => {
    expect(
      isBenchViewOp({
        kind: "set_display",
        target: { kind: "derived", id: "d1" },
        patch: {},
      }),
    ).toBe(false);
    expect(isBenchViewOp({ kind: "drop_table" })).toBe(false);
    expect(isBenchViewOp("set_display")).toBe(false);
  });
});

describe("benchTargetKey", () => {
  test("keeps device ids containing '/' unambiguous", () => {
    const a = benchTargetKey({ kind: "signal", device_id: "a/b", signal: "c" });
    const b = benchTargetKey({ kind: "signal", device_id: "a", signal: "b/c" });
    expect(a).not.toBe(b);
    expect(benchTargetKey({ kind: "derived", id: "x" })).not.toBe(a);
  });
});
