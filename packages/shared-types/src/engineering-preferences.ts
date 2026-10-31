// SOLUSDEV-244 / HOME H3 (ADR-034 amendment 2026-09-06) — the user's
// engineering preferences: `~/.solus/preferences.json`.
// docs/contracts/local-state.md § `preferences.json`.
//
// The one Layer-1 file the USER authors rather than the machine: how this
// person engineers (code style, mechanical, electrical, documentation, units
// and standards, plus free text). The Solus equivalent of a claude.md. It is a
// document, not settings — no toggles, no server-owned values, no secrets.
//
// The server never reads ~/.solus: the desktop attaches this document to each
// SOL turn, where the API re-validates it against the same caps and fences it
// as data. The caps here therefore bound what a prompt can ever see, which is
// why over-cap text is TRUNCATED on parse rather than rejected — the file is
// the user's; the budget is Solus's.
//
// Ground rules (ADR-034): JSON, `schema_version`, atomic writes, 0600 under the
// 0700 home, byte-capped, newer `schema_version` ⇒ read-only, corrupt ⇒ empty.

import type { CompleteKeysOf } from "./json";

export const PREFERENCES_FILENAME = "preferences.json";
export const ENGINEERING_PREFERENCES_SCHEMA_VERSION = 1;
/** Per structured-field cap, in characters. */
export const PREFERENCES_FIELD_CAP = 800;
/** Free-text cap, in characters. */
export const PREFERENCES_FREE_TEXT_CAP = 2_400;
/** On-disk byte cap; a larger file is treated as corrupt (→ empty document). */
export const PREFERENCES_MAX_BYTES = 64 * 1024;

/** The five structured sections, in display and prompt order. */
export const PREFERENCE_SECTIONS = [
  "codeStyle",
  "mechanical",
  "electrical",
  "documentation",
  "unitsStandards",
] as const;
export type PreferenceSection = (typeof PREFERENCE_SECTIONS)[number];

/** SOLUSDEV-321 P6: the domains SOL sets its register by, and the levels a
 *  person may state for each. Mirrors `agent/expertise.py` (`Expertise`). */
export const EXPERTISE_DOMAINS = [
  "control",
  "electronics",
  "mechanical",
  "software",
] as const;
export type ExpertiseDomain = (typeof EXPERTISE_DOMAINS)[number];
export const EXPERTISE_LEVELS = ["novice", "working", "expert"] as const;
export type ExpertiseLevel = (typeof EXPERTISE_LEVELS)[number];

/** The whole of `~/.solus/preferences.json`. */
export interface EngineeringPreferences {
  readonly schema_version: number;
  /** RFC 3339 instant of the last save (informational). */
  readonly updatedAt?: string;
  /** Anything that does not fit a section. */
  readonly freeText: string;
  readonly codeStyle: string;
  readonly mechanical: string;
  readonly electrical: string;
  readonly documentation: string;
  readonly unitsStandards: string;
  /** SOLUSDEV-320: the structured sections the user lets the project mirror
   *  (`PUT /members/me/preferences`). Absent = nothing shared. `freeText` is
   *  never shareable, so it has no flag. */
  readonly shared?: Partial<Record<PreferenceSection, boolean>>;
  /** SOLUSDEV-321 P6: the person's own level per domain. Each stated domain
   *  wins over the level Solus inferred; absent = nothing stated. Sent with the
   *  turn, never stored by the server. */
  readonly expertise?: Partial<Record<ExpertiseDomain, ExpertiseLevel>>;
}

const FIELDS = [
  "schema_version",
  "updatedAt",
  "freeText",
  "shared",
  "expertise",
  ...PREFERENCE_SECTIONS,
] as const;
export const ENGINEERING_PREFERENCES_FIELDS: CompleteKeysOf<
  EngineeringPreferences,
  typeof FIELDS
> = FIELDS;

export type PreferencesParseResult =
  | { readonly ok: true; readonly preferences: EngineeringPreferences }
  | { readonly ok: false; readonly reason: "invalid" | "newer" };

const INVALID: PreferencesParseResult = { ok: false, reason: "invalid" };

/** A document with nothing in it — what a fresh machine starts from. */
export function emptyEngineeringPreferences(): EngineeringPreferences {
  return {
    schema_version: ENGINEERING_PREFERENCES_SCHEMA_VERSION,
    freeText: "",
    codeStyle: "",
    mechanical: "",
    electrical: "",
    documentation: "",
    unitsStandards: "",
  };
}

/** True when no field carries anything but whitespace and no level is
 *  stated — nothing to send. */
export function isEmptyPreferences(
  preferences: EngineeringPreferences,
): boolean {
  return (
    preferences.freeText.trim() === "" &&
    PREFERENCE_SECTIONS.every((key) => preferences[key].trim() === "") &&
    Object.keys(preferences.expertise ?? {}).length === 0
  );
}

/** Characters of user text the document would put in front of a model. */
export function preferencesPromptChars(
  preferences: EngineeringPreferences,
): number {
  return (
    preferences.freeText.length +
    PREFERENCE_SECTIONS.reduce((n, key) => n + preferences[key].length, 0)
  );
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Keep printable text plus newline and tab; drop the C0/C1 control ranges —
 *  a prompt has no use for them and the JSON encoder would only spend budget
 *  escaping them. */
function isPromptSafeChar(ch: string): boolean {
  const code = ch.charCodeAt(0);
  if (code === 0x09 || code === 0x0a) return true;
  return code >= 0x20 && !(code >= 0x7f && code <= 0x9f);
}

/** Normalise one text field: CRLF → LF, control characters out, cap applied. */
function cleanText(value: string, cap: number): string {
  return Array.from(value.replace(/\r\n?/g, "\n"))
    .filter(isPromptSafeChar)
    .join("")
    .slice(0, cap);
}

const KNOWN_FIELDS: readonly string[] = FIELDS;

/** `schema_version` as an integer ≥ 1, or null when it is not one. */
function parseVersion(value: Record<string, unknown>): number | null {
  const version = value.schema_version;
  return typeof version === "number" &&
    Number.isInteger(version) &&
    version >= 1
    ? version
    : null;
}

const SECTION_KEYS: readonly string[] = PREFERENCE_SECTIONS;

/** `shared` normalised: known section keys only (anything else rejects →
 *  undefined), non-boolean values dropped. Null when the field is absent. */
function parseShared(
  value: unknown,
): Partial<Record<PreferenceSection, boolean>> | null | undefined {
  if (value === undefined) return null;
  if (
    !isPlainObject(value) ||
    !Object.getOwnPropertyNames(value).every((key) =>
      SECTION_KEYS.includes(key),
    )
  )
    return undefined;
  const shared: Partial<Record<PreferenceSection, boolean>> = {};
  for (const key of PREFERENCE_SECTIONS) {
    const flag = value[key];
    if (typeof flag === "boolean") shared[key] = flag;
  }
  return shared;
}

const DOMAIN_KEYS: readonly string[] = EXPERTISE_DOMAINS;
const LEVELS: readonly string[] = EXPERTISE_LEVELS;

/** `expertise` normalised: known domains only (anything else rejects →
 *  undefined), values that are no level dropped, since the API refuses a turn
 *  carrying one. Null when the field is absent. */
function parseExpertise(
  value: unknown,
): Partial<Record<ExpertiseDomain, ExpertiseLevel>> | null | undefined {
  if (value === undefined) return null;
  if (
    !isPlainObject(value) ||
    !Object.getOwnPropertyNames(value).every((key) => DOMAIN_KEYS.includes(key))
  )
    return undefined;
  const expertise: Partial<Record<ExpertiseDomain, ExpertiseLevel>> = {};
  for (const domain of EXPERTISE_DOMAINS) {
    const level = value[domain];
    if (typeof level === "string" && LEVELS.includes(level))
      expertise[domain] = level as ExpertiseLevel;
  }
  return expertise;
}

/** The flagged, non-empty sections — the only text that ever leaves the
 *  machine for the project's `members/<uid>` mirror. */
export function sharedSubset(
  preferences: EngineeringPreferences,
): Partial<Record<PreferenceSection, string>> {
  const subset: Partial<Record<PreferenceSection, string>> = {};
  for (const key of PREFERENCE_SECTIONS) {
    if (preferences.shared?.[key] === true && preferences[key].trim() !== "")
      subset[key] = preferences[key];
  }
  return subset;
}

/** Everything but `schema_version` and `updatedAt`, cleaned and capped; null
 *  when a section is missing, not a string, or `shared` is malformed. */
function parseBody(
  value: Record<string, unknown>,
): Omit<EngineeringPreferences, "schema_version" | "updatedAt"> | null {
  const { freeText } = value;
  if (typeof freeText !== "string") return null;
  const sections: Partial<Record<PreferenceSection, string>> = {};
  for (const key of PREFERENCE_SECTIONS) {
    const raw = value[key];
    if (typeof raw !== "string") return null;
    sections[key] = cleanText(raw, PREFERENCES_FIELD_CAP);
  }
  const shared = parseShared(value.shared);
  if (shared === undefined) return null;
  const expertise = parseExpertise(value.expertise);
  if (expertise === undefined) return null;
  return {
    freeText: cleanText(freeText, PREFERENCES_FREE_TEXT_CAP),
    ...(sections as Record<PreferenceSection, string>),
    ...(shared !== null ? { shared } : {}),
    ...(expertise !== null ? { expertise } : {}),
  };
}

/**
 * Validating parse of untrusted file content (hand-edited, fork-written or
 * corrupted — it must never crash a reader). Unknown fields reject; a
 * `"newer"` result means the file was written by a later schema version and the
 * caller must treat it as READ-ONLY. Over-cap text is truncated, never rejected.
 */
export function parseEngineeringPreferences(
  value: unknown,
): PreferencesParseResult {
  // Own keys only, and only the known ones — `__proto__` arrives as an own key
  // from JSON.parse and must not be silently accepted.
  if (
    !isPlainObject(value) ||
    !Object.getOwnPropertyNames(value).every((key) =>
      KNOWN_FIELDS.includes(key),
    )
  )
    return INVALID;
  const version = parseVersion(value);
  if (version === null) return INVALID;
  if (version > ENGINEERING_PREFERENCES_SCHEMA_VERSION)
    return { ok: false, reason: "newer" };
  const { updatedAt } = value;
  if (updatedAt !== undefined && typeof updatedAt !== "string") return INVALID;
  const body = parseBody(value);
  if (body === null) return INVALID;
  return {
    ok: true,
    preferences: {
      schema_version: version,
      ...(updatedAt !== undefined ? { updatedAt } : {}),
      ...body,
    },
  };
}
