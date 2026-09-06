// SOLUSDEV-235 (ADR-035) — the `extension.toml` manifest contract, TypeScript half.
// docs/contracts/extension-manifest.md
//
// The Python twin is solus_contracts.extension_manifest; both validate the shared
// fixtures in fixtures/extension-manifest/ (json.ts pattern), so the publish
// validator (API), the desktop developer mode, and the Store read ONE shape.
//
// Posture (CLAUDE.md §7, ADR-034/035): a manifest is UNTRUSTED developer input.
// Unknown fields reject everywhere; every free-text field is capped; file refs
// are relative, traversal-free and extension-checked; nothing here can name a
// command. Byte caps on referenced files live in MANIFEST_LIMITS for the bundle
// validator and the desktop installer to share.
//
// This module takes the DECODED TOML object (a TOML parser's output), never TOML
// text, so JSON fixtures and API bodies validate through the same code.

import {
  FIRST_PARTY_LIMITS,
  FIRST_PARTY_TABLES,
  SUPPORTED_SCHEMA_VERSIONS,
  parseBackend,
  parseGraph,
  parseTools,
  type Backend,
  type Graph,
  type Tools,
} from "./extension-manifest-first-party";
import type { CompleteKeysOf } from "./json";
import type { WidgetSlotSize } from "./widget";

export {
  BACKEND_FIELDS,
  CAPABILITY_NAME_RE,
  FIRST_PARTY_TABLES,
  GRAPH_DOMAINS,
  GRAPH_FIELDS,
  GRAPH_KIND_FIELDS,
  SUPPORTED_SCHEMA_VERSIONS,
  TOOLS_FIELDS,
  composedToolName,
  declaresFirstParty,
  graphKindName,
  type Backend,
  type Graph,
  type GraphDomain,
  type GraphKind,
  type Tools,
} from "./extension-manifest-first-party";

export const EXTENSION_MANIFEST_FILENAME = "extension.toml";
// SOLUSDEV-246 (STORE ST1): 2 adds the first-party tables; 1 stays valid.
export const EXTENSION_MANIFEST_SCHEMA_VERSION = 2;

/** The id doubles as the bundle folder name on case-insensitive file systems,
 *  so it is a lowercase slug, 2–64 chars, and nothing else. */
export const EXTENSION_ID_RE = /^[a-z][a-z0-9-]{1,63}$/;
const RESERVED_EXTENSION_IDS = new Set([
  "__proto__",
  "constructor",
  "prototype",
]);

const SEMVER_RE =
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$/;
/** An https ORIGIN: scheme + host (+ optional port), no path, no query. */
const NETWORK_ORIGIN_RE =
  /^https:\/\/[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+(:\d{1,5})?$/;
const HTTPS_URL_RE = /^https:\/\/\S+$/;
const SETTING_KEY_RE = /^[a-z][a-z0-9_]{0,31}$/;
const PATH_SEGMENT_RE = /^[A-Za-z0-9_.-]+$/;

export const SOURCE_KINDS = [
  "code",
  "eda",
  "cad",
  "canbus",
  "runtime",
] as const;
export const SETTING_TYPES = ["boolean", "number", "string", "select"] as const;
const SLOT_SIZES = ["compact", "standard", "wide", "full"] as const;
/** The CLOSED set of bridge scopes (ADR-035 §2). Adding one is a contract change. */
export const PERMISSION_SCOPES = [
  "graph.read",
  "telemetry.read",
  "sources.read",
  "findings.write",
  "sol.ask",
  "storage.own",
  "focus.read",
  "focus.write",
] as const;

export type SourceKind = (typeof SOURCE_KINDS)[number];
export type SettingType = (typeof SETTING_TYPES)[number];
export type PermissionScope = (typeof PERMISSION_SCOPES)[number];

/** Every cap in one place; the Python twin (`LIMITS`) carries the same numbers. */
export const MANIFEST_LIMITS = {
  ...FIRST_PARTY_LIMITS,
  name: 60,
  publisher: 60,
  summary: 160,
  pageLabel: 24,
  windowTitle: 60,
  windowMinPx: 320,
  windowMaxPx: 4096,
  requiresGroups: 4,
  scopes: 8,
  network: 8,
  settingFields: 16,
  settingLabel: 40,
  settingOptions: 12,
  settingOptionLen: 40,
  sectionTitle: 40,
  sections: 4,
  screenshots: 6,
  pathLen: 200,
  iconBytes: 16 * 1024,
  overviewBytes: 32 * 1024,
  sectionBytes: 16 * 1024,
  screenshotBytes: 1024 * 1024,
  bundleBytes: 25 * 1024 * 1024,
} as const;

// ---------------------------------------------------------------------------
// Shapes. `*Document` is the manifest AS AUTHORED (optional blocks may be
// absent); `ExtensionManifest` is the parsed result with defaults applied.
// ---------------------------------------------------------------------------

export interface ExtensionMeta {
  readonly id: string;
  readonly name: string;
  readonly version: string;
  readonly publisher: string;
  readonly summary: string;
  /** AND of ORs over source kinds: every group must be met by one connected kind. */
  readonly requires: readonly (readonly SourceKind[])[];
  readonly min_solus?: string;
}

export interface WidgetView {
  readonly entry: string;
  readonly preferred: WidgetSlotSize;
  readonly minimum?: WidgetSlotSize;
}

export interface PageView {
  readonly entry: string;
  readonly icon: string;
  readonly label: string;
}

export interface WindowView {
  readonly entry: string;
  readonly title: string;
  readonly width?: number;
  readonly height?: number;
}

export interface Views {
  readonly widget?: WidgetView;
  readonly page?: PageView;
  readonly window?: WindowView;
}

export interface Permissions {
  readonly scopes: readonly PermissionScope[];
  readonly network: readonly string[];
}

export interface SettingField {
  readonly key: string;
  readonly type: SettingType;
  readonly label: string;
  readonly options?: readonly string[];
  readonly default?: boolean | number | string;
  readonly min?: number;
  readonly max?: number;
}

export interface Settings {
  readonly fields: readonly SettingField[];
}

export interface StoreLinks {
  readonly documentation?: string;
  readonly issues?: string;
  readonly terms?: string;
}

export interface StoreSection {
  readonly title: string;
  readonly body: string;
}

export interface Store {
  readonly overview: string;
  readonly privacy_policy?: string;
  readonly links: StoreLinks;
  readonly screenshots: readonly string[];
  readonly sections: readonly StoreSection[];
}

/** The manifest as a developer writes it: optional blocks may be omitted. */
export interface ExtensionManifestDocument {
  readonly schema_version: number;
  readonly extension: ExtensionMeta;
  readonly views: Views;
  readonly permissions?: Partial<Permissions>;
  readonly settings?: Partial<Settings>;
  readonly store: Partial<Store> & Pick<Store, "overview">;
  /** schema_version 2, first-party only (SOLUSDEV-246). */
  readonly backend?: Partial<Backend> & Pick<Backend, "capability">;
  readonly graph?: Partial<Graph>;
  readonly tools?: Partial<Tools>;
}

export type SupportedSchemaVersion = (typeof SUPPORTED_SCHEMA_VERSIONS)[number];

/** The parsed manifest: every optional block present, defaults applied. */
export interface ExtensionManifest {
  readonly schema_version: SupportedSchemaVersion;
  readonly extension: ExtensionMeta;
  readonly views: Views;
  readonly permissions: Permissions;
  readonly settings: Settings;
  readonly store: Store;
  /** Absent unless declared (schema_version 2). */
  readonly backend?: Backend;
  readonly graph: Graph;
  readonly tools: Tools;
}

// Runtime field lists, proven complete against the interfaces at compile time
// and compared to the Python-emitted manifest (_fields.json) in the test.
const MANIFEST_FIELDS_V1 = [
  "schema_version",
  "extension",
  "views",
  "permissions",
  "settings",
  "store",
] as const;
const MANIFEST_FIELDS = [...MANIFEST_FIELDS_V1, ...FIRST_PARTY_TABLES] as const;
export const EXTENSION_MANIFEST_FIELDS: CompleteKeysOf<
  ExtensionManifest,
  typeof MANIFEST_FIELDS
> = MANIFEST_FIELDS;
const META_FIELDS = [
  "id",
  "name",
  "version",
  "publisher",
  "summary",
  "requires",
  "min_solus",
] as const;
export const EXTENSION_FIELDS: CompleteKeysOf<
  ExtensionMeta,
  typeof META_FIELDS
> = META_FIELDS;
const VIEWS = ["widget", "page", "window"] as const;
export const VIEWS_FIELDS: CompleteKeysOf<Views, typeof VIEWS> = VIEWS;
const WIDGET = ["entry", "preferred", "minimum"] as const;
export const WIDGET_VIEW_FIELDS: CompleteKeysOf<WidgetView, typeof WIDGET> =
  WIDGET;
const PAGE = ["entry", "icon", "label"] as const;
export const PAGE_VIEW_FIELDS: CompleteKeysOf<PageView, typeof PAGE> = PAGE;
const WINDOW = ["entry", "title", "width", "height"] as const;
export const WINDOW_VIEW_FIELDS: CompleteKeysOf<WindowView, typeof WINDOW> =
  WINDOW;
const PERMS = ["scopes", "network"] as const;
export const PERMISSIONS_FIELDS: CompleteKeysOf<Permissions, typeof PERMS> =
  PERMS;
const SETTINGS = ["fields"] as const;
export const SETTINGS_FIELDS: CompleteKeysOf<Settings, typeof SETTINGS> =
  SETTINGS;
const SETTING_FIELD = [
  "key",
  "type",
  "label",
  "options",
  "default",
  "min",
  "max",
] as const;
export const SETTING_FIELD_FIELDS: CompleteKeysOf<
  SettingField,
  typeof SETTING_FIELD
> = SETTING_FIELD;
const STORE = [
  "overview",
  "privacy_policy",
  "links",
  "screenshots",
  "sections",
] as const;
export const STORE_FIELDS: CompleteKeysOf<Store, typeof STORE> = STORE;
const LINKS = ["documentation", "issues", "terms"] as const;
export const STORE_LINKS_FIELDS: CompleteKeysOf<StoreLinks, typeof LINKS> =
  LINKS;
const SECTION = ["title", "body"] as const;
export const STORE_SECTION_FIELDS: CompleteKeysOf<
  StoreSection,
  typeof SECTION
> = SECTION;

export type ManifestParseResult =
  | { readonly ok: true; readonly manifest: ExtensionManifest }
  | {
      readonly ok: false;
      readonly reason: "invalid" | "newer";
      readonly problems: readonly string[];
    };

export function isSafeExtensionId(id: string): boolean {
  return EXTENSION_ID_RE.test(id) && !RESERVED_EXTENSION_IDS.has(id);
}

/** A relative, traversal-free path inside the bundle with an allowed suffix —
 *  the desktop serves these from the installed bundle directory, so a path that
 *  escapes it is a file read. Same rule as the Python side. */
export function isSafeBundlePath(
  value: string,
  extensions: readonly string[],
): boolean {
  if (value.length === 0 || value.length > MANIFEST_LIMITS.pathLen)
    return false;
  if (value.startsWith("/") || value.includes("\\")) return false;
  const segments = value.split("/");
  if (
    segments.some(
      (s) => s === "" || s === "." || s === ".." || !PATH_SEGMENT_RE.test(s),
    )
  )
    return false;
  const lowered = value.toLowerCase();
  return extensions.some((ext) => lowered.endsWith(ext));
}

// ---------------------------------------------------------------------------
// The parser. One `Problems` collector; every check appends a dotted path so
// the developer mode and the publish validator show the same messages.
// ---------------------------------------------------------------------------

class Problems {
  readonly list: string[] = [];
  add(path: string, message: string): void {
    this.list.push(`${path}: ${message}`);
  }
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function rejectUnknown(
  p: Problems,
  path: string,
  v: Record<string, unknown>,
  known: readonly string[],
): void {
  for (const key of Object.keys(v))
    if (!known.includes(key)) p.add(`${path}.${key}`, "unknown field");
}

function str(
  p: Problems,
  path: string,
  v: unknown,
  min: number,
  max: number,
): string | undefined {
  if (typeof v !== "string") {
    p.add(path, "must be a string");
    return undefined;
  }
  if (v.length < min || v.length > max) {
    p.add(path, `length must be ${min}–${max}`);
    return undefined;
  }
  return v;
}

function pattern(
  p: Problems,
  path: string,
  v: unknown,
  re: RegExp,
  what: string,
): string | undefined {
  if (typeof v !== "string" || !re.test(v)) {
    p.add(path, `must be ${what}`);
    return undefined;
  }
  return v;
}

function optPattern(
  p: Problems,
  path: string,
  v: unknown,
  re: RegExp,
  what: string,
): string | undefined {
  return v === undefined ? undefined : pattern(p, path, v, re, what);
}

function optOneOf<T extends string>(
  p: Problems,
  path: string,
  v: unknown,
  set: readonly T[],
): T | undefined {
  return v === undefined ? undefined : oneOf(p, path, v, set);
}

function bundlePath(
  p: Problems,
  path: string,
  v: unknown,
  exts: readonly string[],
): string | undefined {
  if (typeof v !== "string" || !isSafeBundlePath(v, exts)) {
    p.add(
      path,
      `must be a relative path inside the bundle ending in ${exts.join("/")}`,
    );
    return undefined;
  }
  return v;
}

function oneOf<T extends string>(
  p: Problems,
  path: string,
  v: unknown,
  set: readonly T[],
): T | undefined {
  if (typeof v !== "string" || !(set as readonly string[]).includes(v)) {
    p.add(path, `must be one of ${set.join(", ")}`);
    return undefined;
  }
  return v as T;
}

function distinct(p: Problems, path: string, items: readonly string[]): void {
  if (new Set(items).size !== items.length)
    p.add(path, "entries must be distinct");
}

function parseRequires(
  p: Problems,
  path: string,
  raw: unknown,
): SourceKind[][] {
  const requires: SourceKind[][] = [];
  const groups = raw === undefined ? [] : raw;
  if (
    !Array.isArray(groups) ||
    groups.length > MANIFEST_LIMITS.requiresGroups
  ) {
    p.add(
      path,
      `must be a list of at most ${MANIFEST_LIMITS.requiresGroups} groups`,
    );
    return requires;
  }
  groups.forEach((group, i) => {
    if (!Array.isArray(group) || group.length === 0) {
      p.add(`${path}.${i}`, "each group must be a non-empty list of kinds");
      return;
    }
    const kinds = group.map((k, j) =>
      oneOf(p, `${path}.${i}.${j}`, k, SOURCE_KINDS),
    );
    if (kinds.every((k): k is SourceKind => k !== undefined)) {
      distinct(p, `${path}.${i}`, kinds);
      requires.push(kinds);
    }
  });
  return requires;
}

function parseMeta(p: Problems, v: unknown): ExtensionMeta | undefined {
  const path = "extension";
  if (!isPlainObject(v)) return void p.add(path, "must be a table");
  rejectUnknown(p, path, v, META_FIELDS);
  const id = pattern(
    p,
    `${path}.id`,
    v.id,
    EXTENSION_ID_RE,
    "a lowercase slug (2–64 chars)",
  );
  if (id !== undefined && RESERVED_EXTENSION_IDS.has(id))
    p.add(`${path}.id`, "reserved id");
  const name = str(p, `${path}.name`, v.name, 1, MANIFEST_LIMITS.name);
  const version = pattern(p, `${path}.version`, v.version, SEMVER_RE, "semver");
  const publisher = str(
    p,
    `${path}.publisher`,
    v.publisher,
    1,
    MANIFEST_LIMITS.publisher,
  );
  const summary = str(
    p,
    `${path}.summary`,
    v.summary,
    1,
    MANIFEST_LIMITS.summary,
  );
  const min_solus = optPattern(
    p,
    `${path}.min_solus`,
    v.min_solus,
    SEMVER_RE,
    "semver",
  );
  const requires = parseRequires(p, `${path}.requires`, v.requires);
  if (!id || !name || !version || !publisher || !summary) return undefined;
  return {
    id,
    name,
    version,
    publisher,
    summary,
    requires,
    ...(min_solus ? { min_solus } : {}),
  };
}

function parseWidget(p: Problems, v: unknown): WidgetView | undefined {
  const path = "views.widget";
  if (!isPlainObject(v)) return void p.add(path, "must be a table");
  rejectUnknown(p, path, v, WIDGET);
  const entry = bundlePath(p, `${path}.entry`, v.entry, [".html"]);
  const preferred = oneOf(p, `${path}.preferred`, v.preferred, SLOT_SIZES);
  const minimum = optOneOf(p, `${path}.minimum`, v.minimum, SLOT_SIZES);
  if (!entry || !preferred) return undefined;
  return { entry, preferred, ...(minimum ? { minimum } : {}) };
}

function parsePage(p: Problems, v: unknown): PageView | undefined {
  const path = "views.page";
  if (!isPlainObject(v)) return void p.add(path, "must be a table");
  rejectUnknown(p, path, v, PAGE);
  const entry = bundlePath(p, `${path}.entry`, v.entry, [".html"]);
  const icon = bundlePath(p, `${path}.icon`, v.icon, [".svg"]);
  const label = str(p, `${path}.label`, v.label, 1, MANIFEST_LIMITS.pageLabel);
  if (!entry || !icon || !label) return undefined;
  return { entry, icon, label };
}

function px(p: Problems, path: string, v: unknown): number | undefined {
  if (v === undefined) return undefined;
  if (
    typeof v !== "number" ||
    !Number.isInteger(v) ||
    v < MANIFEST_LIMITS.windowMinPx ||
    v > MANIFEST_LIMITS.windowMaxPx
  ) {
    p.add(
      path,
      `must be an integer ${MANIFEST_LIMITS.windowMinPx}–${MANIFEST_LIMITS.windowMaxPx}`,
    );
    return undefined;
  }
  return v;
}

function parseWindow(p: Problems, v: unknown): WindowView | undefined {
  const path = "views.window";
  if (!isPlainObject(v)) return void p.add(path, "must be a table");
  rejectUnknown(p, path, v, WINDOW);
  const entry = bundlePath(p, `${path}.entry`, v.entry, [".html"]);
  const title = str(
    p,
    `${path}.title`,
    v.title,
    1,
    MANIFEST_LIMITS.windowTitle,
  );
  const width = px(p, `${path}.width`, v.width);
  const height = px(p, `${path}.height`, v.height);
  if (!entry || !title) return undefined;
  return {
    entry,
    title,
    ...(width !== undefined ? { width } : {}),
    ...(height !== undefined ? { height } : {}),
  };
}

function optParse<T>(
  raw: unknown,
  parse: (v: unknown) => T | undefined,
): T | undefined {
  return raw === undefined ? undefined : parse(raw);
}

function compactViews(views: {
  widget?: WidgetView;
  page?: PageView;
  window?: WindowView;
}): Views {
  return Object.fromEntries(
    Object.entries(views).filter(([, value]) => value !== undefined),
  ) as Views;
}

function parseViews(p: Problems, v: unknown): Views | undefined {
  if (!isPlainObject(v)) return void p.add("views", "must be a table");
  rejectUnknown(p, "views", v, VIEWS);
  const declared = VIEWS.some((k) => v[k] !== undefined);
  if (!declared) {
    p.add("views", "must declare at least one of widget, page, window");
    return undefined;
  }
  return compactViews({
    widget: optParse(v.widget, (x) => parseWidget(p, x)),
    page: optParse(v.page, (x) => parsePage(p, x)),
    window: optParse(v.window, (x) => parseWindow(p, x)),
  });
}

function parsePermissions(p: Problems, v: unknown): Permissions {
  const none: Permissions = { scopes: [], network: [] };
  if (v === undefined) return none;
  if (!isPlainObject(v)) {
    p.add("permissions", "must be a table");
    return none;
  }
  rejectUnknown(p, "permissions", v, PERMS);
  const scopes: PermissionScope[] = [];
  const rawScopes = v.scopes ?? [];
  if (!Array.isArray(rawScopes) || rawScopes.length > MANIFEST_LIMITS.scopes) {
    p.add(
      "permissions.scopes",
      `must be a list of at most ${MANIFEST_LIMITS.scopes} scopes`,
    );
  } else {
    rawScopes.forEach((s, i) => {
      const scope = oneOf(p, `permissions.scopes.${i}`, s, PERMISSION_SCOPES);
      if (scope) scopes.push(scope);
    });
    distinct(p, "permissions.scopes", scopes);
  }
  const network: string[] = [];
  const rawNetwork = v.network ?? [];
  if (
    !Array.isArray(rawNetwork) ||
    rawNetwork.length > MANIFEST_LIMITS.network
  ) {
    p.add(
      "permissions.network",
      `must be a list of at most ${MANIFEST_LIMITS.network} https origins`,
    );
  } else {
    rawNetwork.forEach((o, i) => {
      const origin = pattern(
        p,
        `permissions.network.${i}`,
        o,
        NETWORK_ORIGIN_RE,
        "an https origin (no path)",
      );
      if (origin) network.push(origin);
    });
    distinct(p, "permissions.network", network);
  }
  return { scopes, network };
}

function defaultMatches(type: SettingType, d: unknown): boolean {
  if (type === "boolean") return typeof d === "boolean";
  if (type === "number") return typeof d === "number" && Number.isFinite(d);
  return typeof d === "string";
}

function parseOptions(
  p: Problems,
  path: string,
  raw: unknown,
): string[] | undefined {
  if (raw === undefined) return undefined;
  if (
    !Array.isArray(raw) ||
    raw.length === 0 ||
    raw.length > MANIFEST_LIMITS.settingOptions
  ) {
    p.add(path, `must list 1–${MANIFEST_LIMITS.settingOptions} options`);
    return undefined;
  }
  const parsed = raw.map((o, i) =>
    str(p, `${path}.${i}`, o, 1, MANIFEST_LIMITS.settingOptionLen),
  );
  return parsed.every((o): o is string => o !== undefined) ? parsed : undefined;
}

function checkSelectRules(
  p: Problems,
  path: string,
  type: SettingType,
  options: string[] | undefined,
  v: Record<string, unknown>,
): void {
  if (type !== "select") {
    if (options !== undefined)
      p.add(`${path}.options`, "only select fields take options");
    return;
  }
  if (!options) {
    p.add(`${path}.options`, "select fields must list options");
    return;
  }
  if (v.default !== undefined && !options.includes(v.default as string))
    p.add(`${path}.default`, "must be one of options");
}

function checkRangeRules(
  p: Problems,
  path: string,
  type: SettingType,
  v: Record<string, unknown>,
): void {
  const hasRange = v.min !== undefined || v.max !== undefined;
  if (type !== "number" && hasRange)
    p.add(`${path}.min`, "only number fields take min/max");
  if (v.min !== undefined && typeof v.min !== "number")
    p.add(`${path}.min`, "must be a number");
  if (v.max !== undefined && typeof v.max !== "number")
    p.add(`${path}.max`, "must be a number");
}

/** Type-specific rules: select needs options and an in-range default; only
 *  number takes min/max; the default must match the declared type. */
function checkSettingRules(
  p: Problems,
  path: string,
  type: SettingType,
  options: string[] | undefined,
  v: Record<string, unknown>,
): void {
  checkSelectRules(p, path, type, options, v);
  checkRangeRules(p, path, type, v);
  if (v.default !== undefined && !defaultMatches(type, v.default))
    p.add(`${path}.default`, `must be a ${type}`);
}

function parseSettingField(
  p: Problems,
  path: string,
  v: unknown,
): SettingField | undefined {
  if (!isPlainObject(v)) return void p.add(path, "must be a table");
  rejectUnknown(p, path, v, SETTING_FIELD);
  const key = pattern(
    p,
    `${path}.key`,
    v.key,
    SETTING_KEY_RE,
    "a lowercase snake_case key (≤32 chars)",
  );
  const type = oneOf(p, `${path}.type`, v.type, SETTING_TYPES);
  const label = str(
    p,
    `${path}.label`,
    v.label,
    1,
    MANIFEST_LIMITS.settingLabel,
  );
  const options = parseOptions(p, `${path}.options`, v.options);
  if (!key || !type || !label) return undefined;
  checkSettingRules(p, path, type, options, v);
  return {
    key,
    type,
    label,
    ...(options ? { options } : {}),
    ...(v.default !== undefined
      ? { default: v.default as boolean | number | string }
      : {}),
    ...(typeof v.min === "number" ? { min: v.min } : {}),
    ...(typeof v.max === "number" ? { max: v.max } : {}),
  };
}

function parseSettings(p: Problems, v: unknown): Settings {
  if (v === undefined) return { fields: [] };
  if (!isPlainObject(v)) {
    p.add("settings", "must be a table");
    return { fields: [] };
  }
  rejectUnknown(p, "settings", v, SETTINGS);
  const raw = v.fields ?? [];
  if (!Array.isArray(raw) || raw.length > MANIFEST_LIMITS.settingFields) {
    p.add(
      "settings.fields",
      `must be a list of at most ${MANIFEST_LIMITS.settingFields} fields`,
    );
    return { fields: [] };
  }
  const fields = raw
    .map((f, i) => parseSettingField(p, `settings.fields.${i}`, f))
    .filter((f): f is SettingField => f !== undefined);
  distinct(
    p,
    "settings.fields",
    fields.map((f) => f.key),
  );
  return { fields };
}

function parseLinks(p: Problems, v: unknown): StoreLinks {
  if (v === undefined) return {};
  if (!isPlainObject(v)) {
    p.add("store.links", "must be a table");
    return {};
  }
  rejectUnknown(p, "store.links", v, LINKS);
  const out: Record<string, string> = {};
  for (const key of LINKS) {
    if (v[key] === undefined) continue;
    const url = pattern(
      p,
      `store.links.${key}`,
      v[key],
      HTTPS_URL_RE,
      "an https URL",
    );
    if (url && url.length <= 2048) out[key] = url;
  }
  return out;
}

function parseScreenshots(p: Problems, raw: unknown): string[] {
  const shots: string[] = [];
  const list = raw ?? [];
  if (!Array.isArray(list) || list.length > MANIFEST_LIMITS.screenshots) {
    p.add(
      "store.screenshots",
      `must be a list of at most ${MANIFEST_LIMITS.screenshots} images`,
    );
    return shots;
  }
  list.forEach((s, i) => {
    const shot = bundlePath(p, `store.screenshots.${i}`, s, [".png", ".webp"]);
    if (shot) shots.push(shot);
  });
  return shots;
}

function parseSections(p: Problems, raw: unknown): StoreSection[] {
  const sections: StoreSection[] = [];
  const list = raw ?? [];
  if (!Array.isArray(list) || list.length > MANIFEST_LIMITS.sections) {
    p.add(
      "store.sections",
      `must be a list of at most ${MANIFEST_LIMITS.sections} sections`,
    );
    return sections;
  }
  list.forEach((s, i) => {
    const path = `store.sections.${i}`;
    if (!isPlainObject(s)) return void p.add(path, "must be a table");
    rejectUnknown(p, path, s, SECTION);
    const title = str(
      p,
      `${path}.title`,
      s.title,
      1,
      MANIFEST_LIMITS.sectionTitle,
    );
    const body = bundlePath(p, `${path}.body`, s.body, [".md"]);
    if (title && body) sections.push({ title, body });
  });
  return sections;
}

function parseStore(p: Problems, v: unknown): Store | undefined {
  if (!isPlainObject(v)) return void p.add("store", "must be a table");
  rejectUnknown(p, "store", v, STORE);
  const overview = bundlePath(p, "store.overview", v.overview, [".md"]);
  const privacy_policy =
    v.privacy_policy === undefined
      ? undefined
      : bundlePath(p, "store.privacy_policy", v.privacy_policy, [".md"]);
  const links = parseLinks(p, v.links);
  const screenshots = parseScreenshots(p, v.screenshots);
  const sections = parseSections(p, v.sections);
  if (!overview) return undefined;
  return {
    overview,
    ...(privacy_policy ? { privacy_policy } : {}),
    links,
    screenshots,
    sections,
  };
}

type SchemaCheck =
  | { readonly ok: true; readonly version: SupportedSchemaVersion }
  | Exclude<ManifestParseResult, { ok: true }>;

function isSupportedVersion(sv: number): sv is SupportedSchemaVersion {
  return (SUPPORTED_SCHEMA_VERSIONS as readonly number[]).includes(sv);
}

function checkSchemaVersion(value: Record<string, unknown>): SchemaCheck {
  const sv = value.schema_version;
  if (typeof sv !== "number" || !Number.isInteger(sv))
    return {
      ok: false,
      reason: "invalid",
      problems: ["schema_version: must be an integer"],
    };
  if (sv > EXTENSION_MANIFEST_SCHEMA_VERSION)
    return {
      ok: false,
      reason: "newer",
      problems: [
        `schema_version: ${sv} is newer than ${EXTENSION_MANIFEST_SCHEMA_VERSION}`,
      ],
    };
  if (!isSupportedVersion(sv))
    return {
      ok: false,
      reason: "invalid",
      problems: [
        `schema_version: must be one of ${SUPPORTED_SCHEMA_VERSIONS.join(", ")}`,
      ],
    };
  return { ok: true, version: sv };
}

interface ManifestParts {
  readonly schema_version: SupportedSchemaVersion;
  readonly extension: ExtensionMeta | undefined;
  readonly views: Views | undefined;
  readonly permissions: Permissions;
  readonly settings: Settings;
  readonly store: Store | undefined;
  readonly backend: Backend | undefined;
  readonly graph: Graph;
  readonly tools: Tools;
}

/** Rules that need two blocks at once. */
function crossBlockChecks(p: Problems, parts: ManifestParts): void {
  const { extension, permissions, store, backend } = parts;
  const permissioned =
    permissions.scopes.length > 0 || permissions.network.length > 0;
  if (store && permissioned && !store.privacy_policy)
    p.add(
      "store.privacy_policy",
      "required when permissions.scopes or permissions.network is non-empty",
    );
  if (backend && extension && backend.capability !== extension.id)
    p.add("backend.capability", "must equal extension.id");
}

function finish(p: Problems, parts: ManifestParts): ManifestParseResult {
  const { extension, views, permissions, settings, store, backend } = parts;
  crossBlockChecks(p, parts);
  if (p.list.length > 0 || !extension || !views || !store)
    return { ok: false, reason: "invalid", problems: p.list };
  return {
    ok: true,
    manifest: {
      schema_version: parts.schema_version,
      extension,
      views,
      permissions,
      settings,
      store,
      ...(backend ? { backend } : {}),
      graph: parts.graph,
      tools: parts.tools,
    },
  };
}

/**
 * Strict parse of a decoded `extension.toml`. `reason: "newer"` means a manifest
 * written for a later schema — the desktop treats it as read-only, the publish
 * validator refuses it. Problems name the offending dotted path.
 */
export function parseExtensionManifest(value: unknown): ManifestParseResult {
  if (!isPlainObject(value))
    return {
      ok: false,
      reason: "invalid",
      problems: ["manifest must be a table"],
    };
  const schema = checkSchemaVersion(value);
  if (!schema.ok) return schema;
  const p = new Problems();
  // The first-party tables are unknown fields at schema_version 1, so a bundle
  // written before SOLUSDEV-246 fails exactly as it always did.
  const v2 = schema.version >= 2;
  rejectUnknown(
    p,
    "manifest",
    value,
    v2 ? MANIFEST_FIELDS : MANIFEST_FIELDS_V1,
  );
  return finish(p, {
    schema_version: schema.version,
    extension: parseMeta(p, value.extension),
    views: parseViews(p, value.views),
    permissions: parsePermissions(p, value.permissions),
    settings: parseSettings(p, value.settings),
    store: parseStore(p, value.store),
    backend: v2 ? parseBackend(p, value.backend, EXTENSION_ID_RE) : undefined,
    graph: v2 ? parseGraph(p, value.graph) : { kinds: [] },
    tools: v2 ? parseTools(p, value.tools) : { names: [] },
  });
}
