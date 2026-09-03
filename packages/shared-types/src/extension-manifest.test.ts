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
import type { JsonShapeOf } from "./json";
import {
  EXTENSION_FIELDS,
  EXTENSION_ID_RE,
  EXTENSION_MANIFEST_FIELDS,
  EXTENSION_MANIFEST_FILENAME,
  EXTENSION_MANIFEST_SCHEMA_VERSION,
  MANIFEST_LIMITS,
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

function parsed(value: unknown): ExtensionManifest {
  const result = parseExtensionManifest(value);
  if (!result.ok) throw new Error(result.problems.join("; "));
  return result.manifest;
}

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
    expect(EXTENSION_MANIFEST_SCHEMA_VERSION).toBe(1);
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
  ] as const)("%s", (name, fields) => {
    expect([...fields].sort()).toEqual(
      (manifest as Record<string, string[]>)[name],
    );
  });
});

describe("strict rejection (parity with the Python model)", () => {
  test.each([
    ["bad id", badId, /extension\.id/],
    ["missing privacy policy", missingPrivacy, /privacy_policy/],
    ["unknown field", unknownField, /postinstall/],
    ["path traversal", traversal, /views\.page\.entry/],
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

  test.each([
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
  ])("%s", (_label, value) => {
    expect(parseExtensionManifest(value).ok).toBe(false);
  });

  test("declaring only network still requires a privacy policy", () => {
    const result = parseExtensionManifest({
      ...MINIMAL,
      permissions: { scopes: [], network: ["https://api.example"] },
    });
    expect(result.ok).toBe(false);
  });
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
