// SOLUSDEV-235 (ADR-035) — the extension.toml contract, TypeScript half.
//
// The Python side (solus_contracts.extension_manifest, exercised from the API
// suite) validates the SAME fixtures and regenerates _fields.json from its
// pydantic models; this file asserts the TS field lists match that manifest
// (json.ts drift-guard pattern) and that both parsers agree on what is invalid.
import { describe, expect, test } from "vitest";
import manifest from "../fixtures/extension-manifest/_fields.json";
import full from "../fixtures/extension-manifest/manifest-full.json";
import minimal from "../fixtures/extension-manifest/manifest-minimal.json";
import badId from "../fixtures/extension-manifest/bad-id.invalid.json";
import missingPrivacy from "../fixtures/extension-manifest/missing-privacy.invalid.json";
import unknownField from "../fixtures/extension-manifest/unknown-field.invalid.json";
import traversal from "../fixtures/extension-manifest/traversal.invalid.json";
import newer from "../fixtures/extension-manifest/newer-schema.json";
import v2FirstParty from "../fixtures/extension-manifest/manifest-v2-first-party.json";
import v2Community from "../fixtures/extension-manifest/manifest-v2-community.json";
import v2BadToolName from "../fixtures/extension-manifest/v2-bad-tool-name.invalid.json";
import v2CapabilityMismatch from "../fixtures/extension-manifest/v2-capability-mismatch.invalid.json";
import v1WithBackend from "../fixtures/extension-manifest/v1-with-backend.invalid.json";
import v2TooManyKinds from "../fixtures/extension-manifest/v2-too-many-kinds.invalid.json";
import type { JsonShapeOf } from "./json";
import {
  BACKEND_FIELDS,
  EXTENSION_FIELDS,
  EXTENSION_ID_RE,
  EXTENSION_MANIFEST_FIELDS,
  EXTENSION_MANIFEST_FILENAME,
  EXTENSION_MANIFEST_SCHEMA_VERSION,
  GRAPH_FIELDS,
  GRAPH_KIND_FIELDS,
  MANIFEST_LIMITS,
  SUPPORTED_SCHEMA_VERSIONS,
  TOOLS_FIELDS,
  composedToolName,
  declaresFirstParty,
  graphKindName,
  PAGE_VIEW_FIELDS,
  PERMISSIONS_FIELDS,
  PERMISSION_SCOPES,
  SETTING_FIELD_FIELDS,
  SETTINGS_FIELDS,
  STORE_FIELDS,
  STORE_LINKS_FIELDS,
  STORE_SECTION_FIELDS,
  VIEWS_FIELDS,
  WIDGET_VIEW_FIELDS,
  WINDOW_VIEW_FIELDS,
  isSafeExtensionId,
  parseExtensionManifest,
  type ExtensionManifest,
  type ExtensionManifestDocument,
} from "./extension-manifest";

const FULL = full satisfies JsonShapeOf<ExtensionManifestDocument>;
const MINIMAL = minimal satisfies JsonShapeOf<ExtensionManifestDocument>;
const V2_FIRST_PARTY =
  v2FirstParty satisfies JsonShapeOf<ExtensionManifestDocument>;
const V2_COMMUNITY =
  v2Community satisfies JsonShapeOf<ExtensionManifestDocument>;

function parsed(value: unknown): ExtensionManifest {
  const result = parseExtensionManifest(value);
  if (!result.ok) throw new Error(result.problems.join("; "));
  return result.manifest;
}

const INVALID_MANIFEST_CASES: [string, unknown][] = [
  ["null", null],
  ["array", []],
  ["string", "x"],
  ["no views", { ...MINIMAL, views: {} }],
  [
    "scope outside the closed set",
    {
      ...MINIMAL,
      permissions: { scopes: ["filesystem.write"], network: [] },
      store: { overview: "OVERVIEW.md", privacy_policy: "PRIVACY.md" },
    },
  ],
  [
    "http network origin",
    {
      ...MINIMAL,
      permissions: { scopes: [], network: ["http://api.example"] },
      store: { overview: "OVERVIEW.md", privacy_policy: "PRIVACY.md" },
    },
  ],
  [
    "network origin with a path",
    {
      ...MINIMAL,
      permissions: { scopes: [], network: ["https://api.example/v1"] },
      store: { overview: "OVERVIEW.md", privacy_policy: "PRIVACY.md" },
    },
  ],
  [
    "select without options",
    {
      ...MINIMAL,
      settings: { fields: [{ key: "mode", type: "select", label: "Mode" }] },
    },
  ],
  [
    "default of the wrong type",
    {
      ...MINIMAL,
      settings: {
        fields: [{ key: "n", type: "number", label: "N", default: "ten" }],
      },
    },
  ],
  [
    "duplicate setting keys",
    {
      ...MINIMAL,
      settings: {
        fields: [
          { key: "a", type: "boolean", label: "A" },
          { key: "a", type: "boolean", label: "B" },
        ],
      },
    },
  ],
  [
    "http store link",
    {
      ...MINIMAL,
      store: {
        overview: "OVERVIEW.md",
        links: { documentation: "http://x.example" },
      },
    },
  ],
  [
    "overview that is not markdown",
    { ...MINIMAL, store: { overview: "OVERVIEW.exe" } },
  ],
  [
    "absolute icon path",
    {
      ...MINIMAL,
      views: {
        page: { entry: "page.html", icon: "/etc/icon.svg", label: "P" },
      },
    },
  ],
  [
    "unknown requires kind",
    {
      ...MINIMAL,
      extension: { ...MINIMAL.extension, requires: [["bluetooth"]] },
    },
  ],
  [
    "empty requires group",
    {
      ...MINIMAL,
      extension: { ...MINIMAL.extension, requires: [[]] },
    },
  ],
  [
    "non-semver version",
    {
      ...MINIMAL,
      extension: { ...MINIMAL.extension, version: "v1" },
    },
  ],
  [
    "summary over the cap",
    {
      ...MINIMAL,
      extension: {
        ...MINIMAL.extension,
        summary: "x".repeat(MANIFEST_LIMITS.summary + 1),
      },
    },
  ],
  [
    "too many scopes",
    {
      ...MINIMAL,
      permissions: {
        scopes: [...PERMISSION_SCOPES, "graph.read"],
        network: [],
      },
      store: { overview: "OVERVIEW.md", privacy_policy: "PRIVACY.md" },
    },
  ],
];

describe("the shared fixtures parse", () => {
  test("full manifest is valid and every declared block survives", () => {
    const m = parsed(FULL);
    expect(m.extension.id).toBe("bom");
    expect(m.views.window?.width).toBe(960);
    expect(m.permissions.scopes).toEqual(["graph.read", "sources.read"]);
    expect(m.settings.fields).toHaveLength(4);
    expect(m.store.sections[0]?.body).toBe("docs/HOW.md");
  });

  test("minimal manifest fills the optional blocks with empty defaults", () => {
    const m = parsed(MINIMAL);
    expect(m.permissions).toEqual({ scopes: [], network: [] });
    expect(m.settings).toEqual({ fields: [] });
    expect(m.store.links).toEqual({});
    expect(m.store.screenshots).toEqual([]);
    expect(m.store.sections).toEqual([]);
    expect(m.store.privacy_policy).toBeUndefined();
  });

  test("the manifest file has one fixed name", () => {
    expect(EXTENSION_MANIFEST_FILENAME).toBe("extension.toml");
    // SOLUSDEV-246 (STORE ST1): v2 adds the first-party tables; v1 stays valid.
    expect(EXTENSION_MANIFEST_SCHEMA_VERSION).toBe(2);
    expect(SUPPORTED_SCHEMA_VERSIONS).toEqual([1, 2]);
  });

  test("v1 manifests default the first-party tables to nothing", () => {
    const m = parsed(MINIMAL);
    expect(m.schema_version).toBe(1);
    expect(m.backend).toBeUndefined();
    expect(m.graph).toEqual({ kinds: [] });
    expect(m.tools).toEqual({ names: [] });
    expect(declaresFirstParty(m)).toBe(false);
  });

  test("a v2 community manifest declares nothing first-party", () => {
    const m = parsed(V2_COMMUNITY);
    expect(m.schema_version).toBe(2);
    expect(declaresFirstParty(m)).toBe(false);
  });

  test("a v2 first-party manifest carries backend, graph and tools", () => {
    const m = parsed(V2_FIRST_PARTY);
    expect(m.backend).toEqual({ capability: "fixture-bundle", routes: true });
    expect(m.graph.kinds).toEqual([{ name: "note", domain: "code" }]);
    expect(m.tools.names).toEqual(["add_note", "clear_notes"]);
    expect(declaresFirstParty(m)).toBe(true);
  });

  test("namespacing helpers match the Python side", () => {
    expect(graphKindName("fixture-bundle", "note")).toBe(
      "ext:fixture-bundle:note",
    );
    expect(composedToolName("fixture-bundle", "add_note")).toBe(
      "fixture-bundle.add_note",
    );
    expect(
      composedToolName("a".repeat(64), "b".repeat(32)).length,
    ).toBeLessThanOrEqual(128);
  });
});

describe("field lists match the Python-emitted manifest", () => {
  test.each([
    ["ExtensionManifest", EXTENSION_MANIFEST_FIELDS],
    ["ExtensionMeta", EXTENSION_FIELDS],
    ["Views", VIEWS_FIELDS],
    ["WidgetView", WIDGET_VIEW_FIELDS],
    ["PageView", PAGE_VIEW_FIELDS],
    ["WindowView", WINDOW_VIEW_FIELDS],
    ["Permissions", PERMISSIONS_FIELDS],
    ["Settings", SETTINGS_FIELDS],
    ["SettingField", SETTING_FIELD_FIELDS],
    ["Store", STORE_FIELDS],
    ["StoreLinks", STORE_LINKS_FIELDS],
    ["StoreSection", STORE_SECTION_FIELDS],
    ["Backend", BACKEND_FIELDS],
    ["Graph", GRAPH_FIELDS],
    ["GraphKind", GRAPH_KIND_FIELDS],
    ["Tools", TOOLS_FIELDS],
  ] as const)("%s", (name, fields) => {
    expect([...fields].sort()).toEqual(
      (manifest as Record<string, string[]>)[name],
    );
  });
});

describe("strict rejection (parity with the Python model)", () => {
  registerManifestFieldValidationTests();
  registerInvalidManifestShapeTests();
  registerNetworkPrivacyRequirementTests();
});

describe("ids", () => {
  test("slug rule is lowercase, folder-safe, 2–64 chars", () => {
    expect(EXTENSION_ID_RE.test("bom")).toBe(true);
    expect(EXTENSION_ID_RE.test("can-telemetry-2")).toBe(true);
    expect(EXTENSION_ID_RE.test("b")).toBe(false);
    expect(EXTENSION_ID_RE.test("Bom")).toBe(false);
    expect(EXTENSION_ID_RE.test("2bom")).toBe(false);
    expect(EXTENSION_ID_RE.test("a".repeat(65))).toBe(false);
  });

  test("object-internal names are refused even though the regex admits them", () => {
    expect(isSafeExtensionId("constructor")).toBe(false);
    expect(isSafeExtensionId("prototype")).toBe(false);
    expect(isSafeExtensionId("bom")).toBe(true);
  });
});

function registerManifestFieldValidationTests(): void {
  test.each([
    ["bad id", badId, /extension\.id/],
    ["missing privacy policy", missingPrivacy, /privacy_policy/],
    ["unknown field", unknownField, /postinstall/],
    ["path traversal", traversal, /views\.page\.entry/],
    ["v2 bad tool name", v2BadToolName, /tools\.names\.0/],
    ["v2 capability mismatch", v2CapabilityMismatch, /backend\.capability/],
    [
      "v1 carrying a backend table",
      v1WithBackend,
      /manifest\.backend: unknown field/,
    ],
    ["v2 too many kinds", v2TooManyKinds, /graph\.kinds/],
  ])("%s is invalid and names the field", (_label, fixture, pattern) => {
    const result = parseExtensionManifest(fixture);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.reason).toBe("invalid");
    expect(result.problems.join("\n")).toMatch(pattern);
  });

  test("a newer schema_version is reported as newer, not invalid", () => {
    expect(parseExtensionManifest(newer)).toMatchObject({
      ok: false,
      reason: "newer",
    });
  });
}

function registerInvalidManifestShapeTests(): void {
  test.each(INVALID_MANIFEST_CASES)("%s", (_label, value) => {
    expect(parseExtensionManifest(value).ok).toBe(false);
  });
}

function registerNetworkPrivacyRequirementTests(): void {
  test("declaring only network still requires a privacy policy", () => {
    const result = parseExtensionManifest({
      ...MINIMAL,
      permissions: { scopes: [], network: ["https://api.example"] },
    });
    expect(result.ok).toBe(false);
  });
}
