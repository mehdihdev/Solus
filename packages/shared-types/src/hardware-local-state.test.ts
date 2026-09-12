import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  emptyHardwareLocalState,
  parseHardwareLocalState,
} from "./hardware-local-state";

const accountId = "00000000-0000-4000-8000-000000000001";
const sourceId = "00000000-0000-4000-8000-000000000002";
const configId = "00000000-0000-4000-8000-000000000003";
const fixture = JSON.parse(
  readFileSync(
    new URL("../fixtures/hardware-local-state/valid.json", import.meta.url),
    "utf8",
  ),
) as Record<string, unknown>;
const source = {
  path: "/workspace/config.json",
  contentSha256: "a".repeat(64),
};
const document = (entry: unknown): unknown => ({
  schema_version: 1,
  accounts: { [accountId]: entry },
});
const withSource = (value: unknown): unknown =>
  document({ sources: { [sourceId]: value }, bindings: {} });

describe("private hardware state contract", () => {
  it("rejects newline-suffixed IDs and digests rather than regex prefix matches", () => {
    expect(
      parseHardwareLocalState({
        schema_version: 1,
        accounts: { [accountId + "\n"]: { sources: {}, bindings: {} } },
      }).ok,
    ).toBe(false);
    expect(
      parseHardwareLocalState(
        withSource({ ...source, contentSha256: "a".repeat(64) + "\n" }),
      ).ok,
    ).toBe(false);
  });

  it("accepts equivalent JSON integer encodings", () => {
    expect(
      parseHardwareLocalState(
        JSON.parse('{"schema_version":1.0,"accounts":{}}'),
      ).ok,
    ).toBe(true);
  });

  it("bounds binding maps and rejects null or empty hints", () => {
    for (const lastSeenPath of [null, "", "\u0085", "\ud800"]) {
      expect(
        parseHardwareLocalState(
          document({ sources: {}, bindings: { [configId]: { lastSeenPath } } }),
        ).ok,
      ).toBe(false);
    }
    const bindings = Object.fromEntries(
      Array.from({ length: 257 }, (_, i) => [
        `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
        {},
      ]),
    );
    expect(
      parseHardwareLocalState(document({ sources: {}, bindings })).ok,
    ).toBe(false);
  });
  it("round-trips the same portable wire fixture as Python", () => {
    const result = parseHardwareLocalState(fixture);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.state).toEqual(fixture);
  });

  it("accepts an empty document without inventing local bindings", () => {
    expect(parseHardwareLocalState(emptyHardwareLocalState())).toEqual({
      ok: true,
      state: { schema_version: 1, accounts: {} },
    });
  });
});

describe("private hardware state malformed input", () => {
  it.each([
    null,
    [],
    {},
    { schema_version: true, accounts: {} },
    { schema_version: 0, accounts: {} },
    { schema_version: 1, accounts: {}, extra: true },
    {
      schema_version: 1,
      accounts: { "../other": { sources: {}, bindings: {} } },
    },
    document({ sources: {}, bindings: {}, calibration: {} }),
    withSource({ ...source, path: "relative/config.json" }),
    withSource({ ...source, path: "/workspace/unsafe\u0000.json" }),
    withSource({ ...source, path: "/" + "x".repeat(4096) }),
    withSource({ ...source, path: 12 }),
    withSource({ ...source, contentSha256: "A".repeat(64) }),
    withSource({ ...source, contentSha256: "a".repeat(63) }),
    withSource({ ...source, credentials: "not-allowed" }),
    document({
      sources: {},
      bindings: { [configId]: { lastSeenPath: "x".repeat(513) } },
    }),
    document({
      sources: {},
      bindings: { [configId]: { lastSeenPath: "bad\npath" } },
    }),
    document({ sources: {}, bindings: { [configId]: { confirmed: true } } }),
    JSON.parse(
      '{"schema_version":1,"accounts":{"__proto__":{"sources":{},"bindings":{}}}}',
    ),
  ])("rejects malformed or undeclared input %#", (value) => {
    expect(parseHardwareLocalState(value)).toEqual({
      ok: false,
      reason: "invalid",
    });
  });

  it("distinguishes a newer version so a writer cannot clobber it", () => {
    expect(
      parseHardwareLocalState({
        schema_version: 2,
        accounts: {},
        futureField: true,
      }),
    ).toEqual({ ok: false, reason: "newer" });
  });

  it("accepts absolute Windows source paths independently of the host OS", () => {
    expect(
      parseHardwareLocalState(
        withSource({ ...source, path: "C:\\work\\config.json" }),
      ).ok,
    ).toBe(true);
  });
});

describe("private hardware state size limits", () => {
  it("rejects oversized account/source maps and total encoded size", () => {
    const ids = (count: number): string[] =>
      Array.from(
        { length: count },
        (_, i) => `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
      );
    expect(
      parseHardwareLocalState({
        schema_version: 1,
        accounts: Object.fromEntries(
          ids(17).map((id) => [id, { sources: {}, bindings: {} }]),
        ),
      }).ok,
    ).toBe(false);
    expect(
      parseHardwareLocalState(
        document({
          sources: Object.fromEntries(ids(257).map((id) => [id, source])),
          bindings: {},
        }),
      ).ok,
    ).toBe(false);
    expect(
      parseHardwareLocalState(
        document({
          sources: Object.fromEntries(
            ids(100).map((id) => [
              id,
              { ...source, path: "/" + "é".repeat(2048) },
            ]),
          ),
          bindings: {},
        }),
      ).ok,
    ).toBe(false);
  });
});
