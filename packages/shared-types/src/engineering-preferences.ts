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
}

const FIELDS = [
  "schema_version",
  "updatedAt",
  "freeText",
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

/** True when no field carries anything but whitespace — nothing to send. */
export function isEmptyPreferences(
  preferences: EngineeringPreferences,
): boolean {
  return (
    preferences.freeText.trim() === "" &&
    PREFERENCE_SECTIONS.every((key) => preferences[key].trim() === "")
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
  return typeof version === "number" && Number.isInteger(version) && version >= 1
    ? version
    : null;
}

/** The five structured sections, cleaned and capped; null if any is missing
 *  or not a string. */
function parseSections(
  value: Record<string, unknown>,
): Record<PreferenceSection, string> | null {
  const sections: Partial<Record<PreferenceSection, string>> = {};
  for (const key of PREFERENCE_SECTIONS) {
    const raw = value[key];
    if (typeof raw !== "string") return null;
    sections[key] = cleanText(raw, PREFERENCES_FIELD_CAP);
  }
  return sections as Record<PreferenceSection, string>;
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
    !Object.getOwnPropertyNames(value).every((key) => KNOWN_FIELDS.includes(key))
  )
    return INVALID;
  const version = parseVersion(value);
  if (version === null) return INVALID;
  if (version > ENGINEERING_PREFERENCES_SCHEMA_VERSION)
    return { ok: false, reason: "newer" };
  const { updatedAt, freeText } = value;
  if (updatedAt !== undefined && typeof updatedAt !== "string") return INVALID;
  if (typeof freeText !== "string") return INVALID;
  const sections = parseSections(value);
  if (sections === null) return INVALID;
  return {
    ok: true,
    preferences: {
      schema_version: version,
      ...(updatedAt !== undefined ? { updatedAt } : {}),
      freeText: cleanText(freeText, PREFERENCES_FREE_TEXT_CAP),
      ...sections,
    },
  };
}
