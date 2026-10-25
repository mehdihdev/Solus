// SOLUSDEV-244 (ADR-034 amendment 2026-09-06) — ~/.solus/preferences.json,
// the user's engineering conventions. docs/contracts/local-state.md.
import { describe, expect, test } from "vitest";
import empty from "../fixtures/local-state/preferences-empty.json";
import full from "../fixtures/local-state/preferences.json";
import {
  ENGINEERING_PREFERENCES_FIELDS,
  ENGINEERING_PREFERENCES_SCHEMA_VERSION,
  PREFERENCES_FIELD_CAP,
  PREFERENCES_FILENAME,
  PREFERENCES_FREE_TEXT_CAP,
  PREFERENCES_MAX_BYTES,
  PREFERENCE_SECTIONS,
  emptyEngineeringPreferences,
  isEmptyPreferences,
  parseEngineeringPreferences,
  preferencesPromptChars,
  sharedSubset,
  type EngineeringPreferences,
} from "./engineering-preferences";
import type { JsonShapeOf } from "./json";

const FULL = full satisfies JsonShapeOf<EngineeringPreferences>;
const EMPTY = empty satisfies JsonShapeOf<EngineeringPreferences>;

describe("constants", () => {
  test("the file name and caps are the ADR-034 values", () => {
    expect(PREFERENCES_FILENAME).toBe("preferences.json");
    expect(ENGINEERING_PREFERENCES_SCHEMA_VERSION).toBe(1);
    expect(PREFERENCES_FIELD_CAP).toBe(800);
    expect(PREFERENCES_FREE_TEXT_CAP).toBe(2400);
    expect(PREFERENCES_MAX_BYTES).toBe(64 * 1024);
    // The whole document, at cap, is 6 400 CHARACTERS — under the prompt's
    // 8 000-char block cap for ASCII; the API bounds the ENCODED length.
    expect(PREFERENCES_FREE_TEXT_CAP + 5 * PREFERENCES_FIELD_CAP).toBeLessThan(
      8_000,
    );
  });

  test("the five structured sections are fixed and ordered", () => {
    expect(PREFERENCE_SECTIONS).toEqual([
      "codeStyle",
      "mechanical",
      "electrical",
      "documentation",
      "unitsStandards",
    ]);
    expect([...ENGINEERING_PREFERENCES_FIELDS].sort()).toEqual(
      [
        "schema_version",
        "updatedAt",
        "freeText",
        "shared",
        ...PREFERENCE_SECTIONS,
      ].sort(),
    );
  });
});

describe("the shared fixtures parse", () => {
  test("full fixture is valid and preserved verbatim", () => {
    expect(parseEngineeringPreferences(FULL)).toEqual({
      ok: true,
      preferences: FULL,
    });
  });

  test("empty fixture is the empty document", () => {
    const result = parseEngineeringPreferences(EMPTY);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(isEmptyPreferences(result.preferences)).toBe(true);
    expect(result.preferences).toEqual(emptyEngineeringPreferences());
  });

  test("emptyEngineeringPreferences carries no updatedAt and is empty", () => {
    const doc = emptyEngineeringPreferences();
    expect(doc.schema_version).toBe(ENGINEERING_PREFERENCES_SCHEMA_VERSION);
    expect("updatedAt" in doc).toBe(false);
    expect(isEmptyPreferences(doc)).toBe(true);
    expect(isEmptyPreferences({ ...doc, freeText: "   " })).toBe(true);
    expect(isEmptyPreferences({ ...doc, electrical: "x" })).toBe(false);
  });
});

function without<K extends keyof EngineeringPreferences>(
  doc: EngineeringPreferences,
  key: K,
): Omit<EngineeringPreferences, K> {
  const copy: Record<string, unknown> = { ...doc };
  delete copy[key];
  return copy as Omit<EngineeringPreferences, K>;
}

describe("strict rejection of malformed content", () => {
  test.each([
    ["null", null],
    ["array", []],
    ["string", "{}"],
    ["missing schema_version", without(EMPTY, "schema_version")],
    ["float schema_version", { ...EMPTY, schema_version: 1.5 }],
    ["zero schema_version", { ...EMPTY, schema_version: 0 }],
    ["unknown field", { ...EMPTY, toggles: {} }],
    [
      "prototype key",
      JSON.parse(
        '{"schema_version":1,"freeText":"","codeStyle":"","mechanical":"",' +
          '"electrical":"","documentation":"","unitsStandards":"","__proto__":{"x":1}}',
      ),
    ],
    ["missing section", without(EMPTY, "electrical")],
    ["non-string section", { ...EMPTY, mechanical: 3 }],
    ["non-string updatedAt", { ...EMPTY, updatedAt: 5 }],
  ])("%s is invalid", (_label, value) => {
    expect(parseEngineeringPreferences(value)).toEqual({
      ok: false,
      reason: "invalid",
    });
  });

  test("a newer schema_version is reported, not parsed", () => {
    expect(
      parseEngineeringPreferences({ ...EMPTY, schema_version: 2 }),
    ).toEqual({
      ok: false,
      reason: "newer",
    });
  });
});

describe("caps bound what a prompt can see, without rejecting the user's text", () => {
  test("over-cap fields are truncated on parse", () => {
    const result = parseEngineeringPreferences({
      ...EMPTY,
      freeText: "f".repeat(PREFERENCES_FREE_TEXT_CAP + 50),
      electrical: "e".repeat(PREFERENCES_FIELD_CAP + 50),
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.preferences.freeText).toHaveLength(PREFERENCES_FREE_TEXT_CAP);
    expect(result.preferences.electrical).toHaveLength(PREFERENCES_FIELD_CAP);
  });

  test("control characters other than newline and tab are stripped", () => {
    const result = parseEngineeringPreferences({
      ...EMPTY,
      codeStyle: "a\x00b\r\nc\td\x1b",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.preferences.codeStyle).toBe("ab\nc\td");
  });

  test("preferencesPromptChars counts every text field", () => {
    expect(preferencesPromptChars(emptyEngineeringPreferences())).toBe(0);
    const result = parseEngineeringPreferences(FULL);
    if (!result.ok) throw new Error("fixture must parse");
    const expected =
      FULL.freeText.length +
      PREFERENCE_SECTIONS.reduce((n, key) => n + FULL[key].length, 0);
    expect(preferencesPromptChars(result.preferences)).toBe(expected);
  });
});

// SOLUSDEV-320 P5-T1d — `shared`: which structured sections the user lets the
// project mirror (`PUT /members/me/preferences`). Absent = nothing shared;
// freeText is never shareable.
describe("shared flags", () => {
  test("absent shared parses to a document without the field", () => {
    const result = parseEngineeringPreferences(EMPTY);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect("shared" in result.preferences).toBe(false);
  });

  test("boolean flags on known sections are kept; non-booleans are dropped", () => {
    const result = parseEngineeringPreferences({
      ...EMPTY,
      shared: { electrical: true, mechanical: false, codeStyle: "yes" },
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.preferences.shared).toEqual({
      electrical: true,
      mechanical: false,
    });
  });

  test("an unknown key inside shared rejects — freeText included", () => {
    expect(
      parseEngineeringPreferences({ ...EMPTY, shared: { freeText: true } }),
    ).toEqual({ ok: false, reason: "invalid" });
    expect(
      parseEngineeringPreferences({
        ...EMPTY,
        shared: JSON.parse('{"__proto__": true}'),
      }),
    ).toEqual({ ok: false, reason: "invalid" });
    expect(parseEngineeringPreferences({ ...EMPTY, shared: [] })).toEqual({
      ok: false,
      reason: "invalid",
    });
  });

  test("sharedSubset returns only flagged, non-empty sections", () => {
    const result = parseEngineeringPreferences({
      ...FULL,
      shared: { electrical: true, mechanical: true, documentation: false },
    });
    if (!result.ok) throw new Error("must parse");
    expect(sharedSubset(result.preferences)).toEqual({
      electrical: FULL.electrical,
      mechanical: FULL.mechanical,
    });
    expect(
      sharedSubset({
        ...emptyEngineeringPreferences(),
        shared: { electrical: true },
      }),
    ).toEqual({});
    expect(sharedSubset(emptyEngineeringPreferences())).toEqual({});
  });
});
