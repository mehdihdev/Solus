// SOLUSDEV-166 (ADR-034) — the ~/.solus local-state contract, runtime half.
//
// The Python side (solus_contracts.local_state, exercised from the companion
// suite) validates the SAME fixtures and regenerates _fields.json from the
// pydantic models' serialization aliases; this file asserts the TS field lists
// match that manifest, closing the drift loop the same way tool-knowledge does.
import { describe, expect, test } from "vitest";
import manifest from "../fixtures/local-state/_fields.json";
import minimal from "../fixtures/local-state/registry-minimal.json";
import registry from "../fixtures/local-state/registry.json";
import type { JsonShapeOf } from "./json";
import {
  PROJECT_FOLDER_LINK_FIELDS,
  PROJECT_ID_RE,
  PROJECT_REGISTRY_FIELDS,
  PROJECT_REGISTRY_SCHEMA_VERSION,
  emptyProjectRegistry,
  parseProjectRegistry,
  type ProjectRegistry,
} from "./local-state";

const FULL = registry satisfies JsonShapeOf<ProjectRegistry>;
const MINIMAL = minimal satisfies JsonShapeOf<ProjectRegistry>;

describe("the shared fixtures parse", () => {
  test("full registry fixture is valid and preserved verbatim", () => {
    const result = parseProjectRegistry(FULL);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.registry).toEqual(FULL);
    expect(result.registry.projects["proj_a1B2c3"]?.repoUrl).toBe(
      "https://gitlab.com/team/rover.git",
    );
  });

  test("minimal registry fixture is valid", () => {
    expect(parseProjectRegistry(MINIMAL)).toEqual({
      ok: true,
      registry: { schema_version: 1, projects: {} },
    });
  });
});

describe("field lists match the Python-emitted manifest", () => {
  test("ProjectFolderLink", () => {
    expect([...PROJECT_FOLDER_LINK_FIELDS].sort()).toEqual(
      manifest.ProjectFolderLink,
    );
  });
  test("ProjectRegistry", () => {
    expect([...PROJECT_REGISTRY_FIELDS].sort()).toEqual(
      manifest.ProjectRegistry,
    );
  });
});

describe("strict rejection of malformed content", () => {
  test.each([
    ["null", null],
    ["an array", []],
    ["a string", "{}"],
    ["missing schema_version", { projects: {} }],
    ["a string schema_version", { schema_version: "1", projects: {} }],
    ["a zero schema_version", { schema_version: 0, projects: {} }],
    ["a fractional schema_version", { schema_version: 1.5, projects: {} }],
    ["missing projects", { schema_version: 1 }],
    ["projects as an array", { schema_version: 1, projects: [] }],
    [
      "an unknown top-level field",
      { schema_version: 1, projects: {}, extra: true },
    ],
    [
      "an unknown link field",
      { schema_version: 1, projects: { p1: { path: "/a", evil: "x" } } },
    ],
    [
      "an empty link path",
      { schema_version: 1, projects: { p1: { path: "" } } },
    ],
    [
      "a non-string repoUrl",
      { schema_version: 1, projects: { p1: { path: "/a", repoUrl: 7 } } },
    ],
    [
      "a link that is not an object",
      { schema_version: 1, projects: { p1: "/a" } },
    ],
  ])("rejects %s as invalid", (_why, value) => {
    expect(parseProjectRegistry(value)).toEqual({
      ok: false,
      reason: "invalid",
    });
  });

  test.each([["../evil"], ["a/b"], ["a b"], [".."], [""]])(
    "rejects project id %j — ids become path segments",
    (projectId) => {
      expect(PROJECT_ID_RE.test(projectId)).toBe(false);
      expect(
        parseProjectRegistry({
          schema_version: 1,
          projects: { [projectId]: { path: "/a" } },
        }),
      ).toEqual({ ok: false, reason: "invalid" });
    },
  );
});

describe("prototype-pollution-shaped ids (SOLUSDEV-166 L7)", () => {
  test.each([["__proto__"], ["constructor"], ["prototype"]])(
    "rejects the reserved id %j",
    (projectId) => {
      expect(
        parseProjectRegistry({
          schema_version: 1,
          projects: { [projectId]: { path: "/a" } },
        }),
      ).toEqual({ ok: false, reason: "invalid" });
    },
  );

  test("a valid registry parses to a null-prototype projects map", () => {
    const result = parseProjectRegistry(FULL);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(Object.getPrototypeOf(result.registry.projects)).toBeNull();
  });
});

describe("forward compatibility", () => {
  test("a newer schema_version is 'newer', never 'invalid' — readers must not rewrite it", () => {
    expect(
      parseProjectRegistry({
        schema_version: PROJECT_REGISTRY_SCHEMA_VERSION + 1,
        projects: {},
      }),
    ).toEqual({ ok: false, reason: "newer" });
  });
});

describe("emptyProjectRegistry", () => {
  test("starts at the current schema version with no projects", () => {
    expect(emptyProjectRegistry()).toEqual({
      schema_version: PROJECT_REGISTRY_SCHEMA_VERSION,
      projects: {},
    });
  });
});
