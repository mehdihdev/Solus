// SOLUSDEV-220 (CTR-05) — the tool-knowledge boundary.
//
// This table is read by EVERY tenant. Leakage would be severe, so the test that
// matters most is not "does a valid record validate" — it is "can a customer's
// part, dimension, file or document get in at all".
//
// The COMPILE-TIME half lives in tool-knowledge.illegal.ts and runs under
// `pnpm typecheck`. This file is the runtime half.
import { describe, expect, test } from "vitest";
import knowledge from "../fixtures/tool-knowledge/fusion-extrude.json";
import type { JsonShapeOf } from "./json";
import {
  CONTROL_EFFECTS,
  PROVENANCES,
  TOOL_FAMILIES,
  UI_SURFACES,
  controlId,
  parseToolKnowledge,
  vendorText,
  type ToolKnowledge,
} from "./tool-knowledge";

const FIXTURE = knowledge satisfies JsonShapeOf<ToolKnowledge>;

describe("the closed vocabularies", () => {
  test("every categorical field is an enum, never free text", () => {
    // A free-text category is a blob with extra steps.
    expect(TOOL_FAMILIES.length).toBeGreaterThan(0);
    expect(UI_SURFACES).toContain("toolbar");
    expect(CONTROL_EFFECTS).toContain("create_feature");
    expect(PROVENANCES).toEqual([
      "vendor_docs",
      "observed_ui",
      "operator_authored",
    ]);
  });
});

describe("vendorText refuses customer-shaped content", () => {
  test.each([
    ["an absolute posix path", "/home/mehdi/robot/chassis.f3d"],
    ["a windows path", "C:\\Users\\pratham\\Desktop\\arm_v3.sldprt"],
    ["a home-relative path", "~/designs/gripper.step"],
    ["a URL", "https://cad.onshape.com/documents/9a1c2ef4b7d8"],
    ["an Onshape document id", "d/9a1c2ef4b7d80a3c5e6f1b29"],
    ["an Onshape element path", "w/1a2b3c/e/4d5e6f"],
    ["a UUID", "7c9e6679-7425-40de-944b-e07fc1f90ae7"],
    ["an email", "someone@example.com"],
    ["a filename with a CAD extension", "motor_mount.step"],
    ["a dimensioned value", "62.5 mm"],
  ])("rejects %s", (_why, raw) => {
    expect(() => vendorText(raw)).toThrow();
  });

  test.each([
    ["Extrude"],
    ["Create"],
    [
      "Adds depth to a closed sketch profile, producing a solid or surface body.",
    ],
    ["Push/Pull"],
    ["Sketch Dimension"],
  ])("accepts vendor UI text: %s", (raw) => {
    expect(vendorText(raw)).toBe(raw);
  });

  test("rejects text long enough to smuggle a payload", () => {
    // An unbounded string IS a blob field. The cap is part of the boundary.
    expect(() => vendorText("x".repeat(2000))).toThrow(/length/i);
  });

  test("rejects empty and whitespace-only text", () => {
    expect(() => vendorText("")).toThrow();
    expect(() => vendorText("   ")).toThrow();
  });
});

describe("controlId is a slug, not a sentence", () => {
  test("accepts a vendor control identifier", () => {
    expect(controlId("fusion.solid.extrude")).toBe("fusion.solid.extrude");
  });

  test.each(["Extrude", "my part", "chassis.f3d", "d/9a1c2e", ""])(
    "rejects %s",
    (raw) => {
      expect(() => controlId(raw)).toThrow();
    },
  );
});

describe("parseToolKnowledge", () => {
  test("accepts the fixture", () => {
    const record = parseToolKnowledge(FIXTURE);
    expect(record.tool).toBe("fusion");
    expect(record.effect).toBe("create_feature");
    expect(record.invocation?.menu_path).toEqual(["Create", "Extrude"]);
  });

  test("rejects an unknown field rather than ignoring it", () => {
    // extra="forbid" in both languages. A field nobody declared is the exact
    // shape a leak takes: someone adds `notes` and pastes a design review in.
    expect(() =>
      parseToolKnowledge({ ...FIXTURE, notes: "the customer's gripper" }),
    ).toThrow(/notes/);
  });

  test.each([
    ["project_id", "7c9e6679-7425-40de-944b-e07fc1f90ae7"],
    ["entity_id", "7c9e6679-7425-40de-944b-e07fc1f90ae7"],
    ["document_id", "d/9a1c2ef4b7d8"],
    ["properties", { width_mm: 62 }],
    ["attrs", {}],
    ["payload", "…"],
    ["metadata", {}],
  ])("rejects a %s field outright", (field, value) => {
    expect(() => parseToolKnowledge({ ...FIXTURE, [field]: value })).toThrow();
  });
});

describe("parseToolKnowledge — the traps", () => {
  test("rejects customer content smuggled through a legal field", () => {
    // The Onshape trap: per-document `featurespecs` returns a customer's
    // IMPORTED CUSTOM FEATURES — vendor-looking data that is customer content.
    // It arrives in exactly the fields a real control would use.
    expect(() =>
      parseToolKnowledge({
        ...FIXTURE,
        label: "Chassis Rib Pattern",
        control_id: "d/9a1c2ef4b7d80a3c5e6f1b29",
      }),
    ).toThrow();
  });

  test("rejects a menu path segment that is a recent-file entry", () => {
    // "File > Open Recent > ~/designs/arm_v3.f3d" is a real vendor menu holding
    // real customer content.
    expect(() =>
      parseToolKnowledge({
        ...FIXTURE,
        invocation: {
          menu_path: ["File", "Open Recent", "~/designs/arm_v3.f3d"],
          shortcut: null,
        },
      }),
    ).toThrow();
  });

  test("a screen locator is a normalised box, never an image", () => {
    expect(() =>
      parseToolKnowledge({
        ...FIXTURE,
        locator: { x: 0.1, y: 0.2, w: 2, h: 0.1 },
      }),
    ).toThrow();
    expect(
      parseToolKnowledge({ ...FIXTURE, locator: null }).locator,
    ).toBeNull();
  });

  test("rejects an unknown tool family, surface, effect or provenance", () => {
    for (const [field, value] of [
      ["tool", "customers_internal_cad"],
      ["surface", "wherever"],
      ["effect", "does_something"],
      ["provenance", "a_customer_told_us"],
    ] as const) {
      expect(() =>
        parseToolKnowledge({ ...FIXTURE, [field]: value }),
      ).toThrow();
    }
  });

  test("rejects a version range that is not a version range", () => {
    expect(() =>
      parseToolKnowledge({ ...FIXTURE, version_range: "the one Mehdi has" }),
    ).toThrow();
  });
});

// ── SOLUSDEV-216 security review: the findings, asserted so they cannot return ──

describe("customer content the review actually got through", () => {
  test.each([
    ["a net description", "Net MOTOR_PWM_1 connects U3 pin 14 to Q2 gate"],
    [
      "an assembly hierarchy",
      "Chassis/DriveArm/Gripper_v3/FingerLeft revision 7",
    ],
    ["a base64 blob", "U29sdXNQcm9wcmlldGFyeVNjaGVtYXRpY0R1bXBWMQ".repeat(6)],
    [
      "units not in the old allowlist",
      "Motor rated 250W at 3000RPM, 12psi clamp, 40Hz loop",
    ],
    ["a homoglyph path", "／home／mehdi／robot／chassis․f3d"],
    ["a drive-less windows path", "Users\\mehdi\\Documents\\robot\\chassis"],
    ["mAh", "Battery pack 2200mAh"],
    ["AWG — the drifted pattern", "Harness uses 24 AWG wire to the driver"],
  ])("rejects %s", (_why, raw) => {
    expect(() => vendorText(raw)).toThrow();
  });

  test.each(["Extrude", "Push/Pull", "3D Sketch", "Sketch Dimension"])(
    "still accepts vendor UI text: %s",
    (raw) => {
      expect(vendorText(raw)).toBe(raw);
    },
  );
});

describe("the two languages cannot drift again", () => {
  test("the pattern list is loaded from one shared file, not duplicated", async () => {
    // The TS list was missing AWG while Python had it — a security filter kept in
    // two hand-maintained copies. The Python mirror reads this same file.
    const shapes = await import(
      "../fixtures/tool-knowledge/customer-shapes.json"
    );
    expect(shapes.default.patterns.length).toBeGreaterThan(8);
    expect(JSON.stringify(shapes.default.patterns)).toContain("AWG");
  });
});

describe("bounded inputs", () => {
  test("version_range cannot be used to hang the process", () => {
    // 83 chars of "1  1  1…!" took 2.4 SECONDS against the old ambiguous regex.
    const evil = "1" + "  1".repeat(30) + "!";
    const started = Date.now();
    expect(() =>
      parseToolKnowledge({ ...FIXTURE, version_range: evil }),
    ).toThrow();
    expect(Date.now() - started).toBeLessThan(50);
  });

  test("menu_path is capped, matching the Pydantic mirror", () => {
    // 5000 segments × 400 chars parsed clean in TS and would 422 at the API.
    const long = Array.from({ length: 9 }, (_, i) => `Menu${i}`);
    expect(() =>
      parseToolKnowledge({
        ...FIXTURE,
        invocation: { menu_path: long, shortcut: null },
      }),
    ).toThrow(/segments/);
  });

  test("nested objects reject unknown fields, like the top level does", () => {
    expect(() =>
      parseToolKnowledge({
        ...FIXTURE,
        invocation: { menu_path: null, shortcut: null, notes: "customer" },
      }),
    ).toThrow(/unknown field/);
    expect(() =>
      parseToolKnowledge({
        ...FIXTURE,
        locator: { x: 0, y: 0, w: 1, h: 1, image_b64: "iVBORw0KGgo=" },
      }),
    ).toThrow(/unknown field/);
  });

  test("a locator cannot be infinite", () => {
    expect(() =>
      parseToolKnowledge({
        ...FIXTURE,
        locator: { x: 0, y: 0, w: Infinity, h: 1 },
      }),
    ).toThrow(/finite/);
  });
});

test.each(["code", "isaac"])(
  "execution knowledge for %s retains the closed boundary",
  (tool) => {
    const record = { ...FIXTURE, tool, surface: "terminal", effect: "execute" };
    expect(parseToolKnowledge(record).tool).toBe(tool);
    expect(() =>
      parseToolKnowledge({ ...record, command: "arbitrary input" }),
    ).toThrow();
    expect(() =>
      parseToolKnowledge({
        ...record,
        description: "/home/customer/private.ino",
      }),
    ).toThrow();
  },
);
