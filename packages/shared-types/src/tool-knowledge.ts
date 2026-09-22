// SOLUSDEV-220 (CTR-05) — the tool-knowledge typed boundary.
//
// ⚠ HIGHEST-RISK CONTRACT ON THE BOARD. The tool-knowledge store holds TOOL
// knowledge only — "the extrude icon in Fusion v2.x is here and does this" —
// and it is read by EVERY tenant. A customer's parts, dimensions, files or
// designs entering it would be a cross-tenant leak of proprietary robot design.
//
// So the boundary is not a rule people follow. It is the SHAPE:
//
//   1. CLOSED COLUMN SET. `extra="forbid"` / no index signature. There is no
//      `properties`, `attrs`, `metadata`, `payload` or `notes` to put anything in.
//   2. NO IDENTIFIER OF ANYTHING CUSTOMER-OWNED. No project, team, entity,
//      document, element or file field exists to be filled.
//   3. EVERY CATEGORICAL FIELD IS AN ENUM. A free-text category is a blob with
//      extra steps.
//   4. THE TWO PROSE FIELDS ARE BRANDED. `VendorText` cannot be produced from a
//      raw string; it comes only from `vendorText()`. A plain string literal
//      does not type-check — see tool-knowledge.illegal.ts.
//
// ⚠ POINTS 1-3 ARE STRUCTURAL. POINT 4 IS NOT. Branding forces the text through
// a checker; it does not make the checker complete. `vendorText()` rejects an
// enumerated list of mechanical shapes (paths, ids, URLs, dimensioned values)
// and caps length at 400 — it CANNOT classify open-world prose, and a security
// review passed "Hero Arm Bracket Rev C" straight through it. Treat the prose
// fields as a bounded free-text channel with a backstop, and read the
// "What this contract does not do" section of the doc before building ingestion
// on top of it.
//
// The compile-time proof is `tool-knowledge.illegal.ts`, checked by
// `pnpm typecheck`. See docs/contracts/tool-knowledge.md.

import CUSTOMER_SHAPES from "../fixtures/tool-knowledge/customer-shapes.json";
import type { CompleteKeysOf } from "./json";

/** Tools Solus models the UI of. Closed: a new tool is a decision, not a value. */
export const TOOL_FAMILIES = [
  "fusion",
  "onshape",
  "solidworks",
  "autocad",
  "kicad",
  "altium",
  "spice",
  "code",
  "isaac",
] as const;
export type ToolFamily = (typeof TOOL_FAMILIES)[number];

/** Where in the tool's UI the control lives. */
export const UI_SURFACES = [
  "toolbar",
  "menu",
  "context_menu",
  "panel",
  "dialog",
  "keyboard",
  "status_bar",
  "terminal",
] as const;
export type UiSurface = (typeof UI_SURFACES)[number];

/**
 * What the control DOES, from a closed set.
 *
 * Categorising the effect rather than describing it freely is what lets the
 * Guide reason about a control without reading prose — and it removes one more
 * place a sentence about a customer's design could live.
 */
export const CONTROL_EFFECTS = [
  "create_feature",
  "modify_feature",
  "delete_feature",
  "select",
  "navigate",
  "measure",
  "toggle_visibility",
  "import",
  "export",
  "undo",
  "settings",
  "execute",
] as const;
export type ControlEffect = (typeof CONTROL_EFFECTS)[number];

/** Where the knowledge came from. Never "a customer's project". */
export const PROVENANCES = [
  "vendor_docs",
  "observed_ui",
  "operator_authored",
] as const;
export type Provenance = (typeof PROVENANCES)[number];

declare const brand: unique symbol;

/**
 * Text that has been checked to be about a TOOL, not about a design.
 *
 * Branded so a raw string cannot be assigned: the only way to get one is
 * `vendorText()`, which runs the rejections below. That turns "we reviewed it"
 * into "it does not compile".
 */
export type VendorText = string & { readonly [brand]: "VendorText" };

/** A vendor control identifier. Branded for the same reason. */
export type ControlId = string & { readonly [brand]: "ControlId" };

const MAX_VENDOR_TEXT = 400;
/** Matches the Pydantic mirror's `max_length=8`. */
const MAX_MENU_PATH = 8;

/**
 * Refuse any key the caller did not declare. The nested parsers used to drop
 * extras silently while their Pydantic mirrors set `extra="forbid"`, so TS
 * accepted records the API would 422.
 */
function rejectUnknown(
  value: Record<string, unknown>,
  allowed: readonly string[],
  what: string,
): void {
  const unknown = Object.keys(value).filter((key) => !allowed.includes(key));
  if (unknown.length > 0) {
    throw new TypeError(`${what}: unknown field(s): ${unknown.join(", ")}`);
  }
}

/**
 * Shapes that mean "this text is about a design, not about the tool".
 *
 * ⚠ THIS IS A BACKSTOP, NOT A FILTER. An earlier version of this comment claimed
 * these patterns "make the common leak impossible". They do not, and the
 * security review proved it: prose like "Hero Arm Bracket Rev C" or "Net
 * MOTOR_PWM_1 connects U3 pin 14 to Q2 gate" passed every check. No pattern list
 * can classify open-world prose, and pretending otherwise is worse than not
 * trying, because LANE D's ingestion guard (SOLUS-TU-06) is told what to trust.
 *
 * WHAT IS ACTUALLY STRUCTURAL is above this line: the closed column set, the
 * absent customer-owned identifiers, the enum-only categoricals. Those are the
 * boundary. These patterns catch the mechanical shapes — paths, ids, URLs,
 * dimensioned values — that leak most often by accident.
 *
 * Loaded from ONE json file shared with the Python mirror. The two lists were
 * hand-maintained and had already drifted within a single ticket (AWG was in
 * Python and not here), which is why they no longer live in two places.
 */
const CUSTOMER_SHAPED: readonly (readonly [RegExp, string])[] =
  CUSTOMER_SHAPES.patterns.map(
    (entry) => [new RegExp(entry.re, "i"), entry.why] as const,
  );

function check(raw: unknown, field: string): string {
  if (typeof raw !== "string")
    throw new TypeError(`${field}: must be a string`);
  // NFKC FIRST. Without it "／home／mehdi／chassis․f3d" (fullwidth solidus, one-dot
  // leader) is a different string to every pattern below while rendering
  // identically to a human — homoglyph evasion, demonstrated in review.
  const text = raw.normalize("NFKC").trim();
  if (text.length === 0) throw new TypeError(`${field}: must not be empty`);
  if (text.length > MAX_VENDOR_TEXT) {
    // An unbounded string IS a blob field. The cap is part of the boundary, and
    // it runs BEFORE the patterns so no pattern ever sees unbounded input.
    throw new TypeError(
      `${field}: exceeds the ${MAX_VENDOR_TEXT}-character length cap`,
    );
  }
  for (const [pattern, why] of CUSTOMER_SHAPED) {
    if (pattern.test(text)) {
      throw new TypeError(
        `${field}: rejected — ${why}. Tool knowledge never describes a design.`,
      );
    }
  }
  return text;
}

/** Check and brand a piece of vendor UI text. Throws on customer-shaped content. */
export function vendorText(raw: unknown, field = "text"): VendorText {
  return check(raw, field) as VendorText;
}

const CONTROL_ID_RE = /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/;

/** Check and brand a vendor control identifier: a slug, never a sentence. */
export function controlId(raw: unknown, field = "control_id"): ControlId {
  const text = check(raw, field);
  if (!CONTROL_ID_RE.test(text)) {
    throw new TypeError(
      `${field}: must be a lowercase dotted slug matching ${CONTROL_ID_RE}`,
    );
  }
  return text as ControlId;
}

/** How a user triggers the control. Both halves optional; the control may be icon-only. */
export interface Invocation {
  /** Vendor menu labels, outermost first. Each is checked — a "Recent files" entry is not vendor text. */
  readonly menu_path: readonly VendorText[] | null;
  /** e.g. "E", "Ctrl+E", "Shift+Alt+D". */
  readonly shortcut: string | null;
}

/**
 * Where the control sits, as a NORMALISED box in 0..1 of the window.
 *
 * Numbers, never an image. A screenshot of a customer's screen is customer
 * content, so there is no field to put one in.
 */
export interface ScreenLocator {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

/**
 * One fact about one tool's UI.
 *
 * The complete column set. There is no escape hatch, and adding one is a
 * security change, not a contract change.
 */
export interface ToolKnowledge {
  readonly tool: ToolFamily;
  /** A version range the fact holds for, e.g. ">=2.0 <3.0". */
  readonly version_range: string;
  readonly surface: UiSurface;
  readonly control_id: ControlId;
  /** The on-screen text of the control. */
  readonly label: VendorText;
  readonly effect: ControlEffect;
  /** What the control does, in one or two sentences about the TOOL. */
  readonly description: VendorText;
  readonly invocation: Invocation | null;
  readonly locator: ScreenLocator | null;
  readonly provenance: Provenance;
}

/** `version_range` is the one string NOT routed through `check()`, so it carries its own cap. */
const MAX_VERSION_RANGE = 64;
// The `\s?` inside the starred group used to be ambiguous with the `\s+` that
// opened it, so every double space doubled the parse count: 83 characters took
// 2.4 SECONDS to reject. Dropping the redundant `\s?` and bounding the repeat
// makes it linear. Same reasoning as SHORTCUT_RE below — this one was missed.
const VERSION_RANGE_RE =
  /^(?:[<>=~^]{0,2}\d+(?:\.\d+){0,2})(?:\s+[<>=~^]{0,2}\d+(?:\.\d+){0,2}){0,3}$/;
// Key combinations: "E", "Ctrl+E", "Shift+Alt+D". Deliberately NOT an
// alternation of Ctrl|Alt|Shift|… against [A-Za-z0-9]+ — every one of those
// literals is also alphanumeric, so each token would have two parses and a
// non-matching input would backtrack exponentially. One unambiguous class, and
// bounded, because this string is not otherwise length-capped.
const SHORTCUT_RE = /^[A-Za-z0-9]{1,10}(\+[A-Za-z0-9]{1,10}){0,4}$/;

const KNOWN_FIELDS = new Set([
  "tool",
  "version_range",
  "surface",
  "control_id",
  "label",
  "effect",
  "description",
  "invocation",
  "locator",
  "provenance",
]);

function oneOf<T extends string>(
  allowed: readonly T[],
  raw: unknown,
  field: string,
): T {
  if (
    typeof raw !== "string" ||
    !(allowed as readonly string[]).includes(raw)
  ) {
    throw new TypeError(`${field}: must be one of ${allowed.join(", ")}`);
  }
  return raw as T;
}

function parseMenuPath(raw: unknown): readonly VendorText[] | null {
  if (raw === null || raw === undefined) return null;
  if (!Array.isArray(raw))
    throw new TypeError("invocation.menu_path: must be an array or null");
  if (raw.length > MAX_MENU_PATH) {
    // Unbounded here while Pydantic capped at 8: a 5000-segment path parsed
    // clean in TS and would have 422'd at the API. Each segment is up to 400
    // chars, so this was a multi-megabyte smuggling channel.
    throw new TypeError(
      `invocation.menu_path: at most ${MAX_MENU_PATH} segments`,
    );
  }
  // Every segment is checked: "File > Open Recent > ~/designs/arm.f3d" is a
  // real vendor menu carrying real customer content.
  return raw.map((seg, i) => vendorText(seg, `invocation.menu_path[${i}]`));
}

function parseShortcut(raw: unknown): string | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== "string" || !SHORTCUT_RE.test(raw)) {
    throw new TypeError(
      "invocation.shortcut: must be a key combination or null",
    );
  }
  return raw;
}

function parseInvocation(raw: unknown): Invocation | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== "object")
    throw new TypeError("invocation: must be an object or null");
  const value = raw as Record<string, unknown>;
  // Nested objects are closed too. The top level rejected unknown fields while
  // these silently dropped them, so TS accepted records Pydantic would refuse.
  rejectUnknown(value, ["menu_path", "shortcut"], "invocation");
  return {
    menu_path: parseMenuPath(value.menu_path),
    shortcut: parseShortcut(value.shortcut),
  };
}

/**
 * Parse a normalised screen box, or throw. EXPORTED because the orb↔overlay
 * contract needs exactly this check and was casting instead — a `locator` of
 * `{w: 1e9, h: 1e9, image_b64: "..."}` reached the overlay unexamined.
 */
export function parseLocator(
  raw: unknown,
  what = "locator",
): ScreenLocator | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== "object")
    throw new TypeError(`${what}: must be an object or null`);
  const value = raw as Record<string, unknown>;
  rejectUnknown(value, ["x", "y", "w", "h"], what);
  const box = { x: value.x, y: value.y, w: value.w, h: value.h };
  for (const [axis, n] of Object.entries(box)) {
    if (typeof n !== "number" || !Number.isFinite(n) || n < 0 || n > 1) {
      throw new TypeError(
        `${what}.${axis}: must be a finite number in 0..1 (normalised, never pixels)`,
      );
    }
  }
  return box as ScreenLocator;
}

/**
 * Parse an untrusted record into `ToolKnowledge`, or throw.
 *
 * This is the only constructor. It is deliberately strict twice over: unknown
 * fields are refused by name (so a `notes` column cannot appear by accident),
 * and every string goes through the vendor-text checks.
 */
export function parseToolKnowledge(raw: unknown): ToolKnowledge {
  if (typeof raw !== "object" || raw === null)
    throw new TypeError("must be an object");
  const value = raw as Record<string, unknown>;

  const unknownFields = Object.keys(value).filter(
    (key) => !KNOWN_FIELDS.has(key),
  );
  if (unknownFields.length > 0) {
    // A field nobody declared is the exact shape a leak takes: someone adds
    // `notes` and pastes a design review into it.
    throw new TypeError(
      `unknown field(s): ${unknownFields.join(", ")}. The column set is closed.`,
    );
  }

  if (
    typeof value.version_range !== "string" ||
    value.version_range.length > MAX_VERSION_RANGE ||
    !VERSION_RANGE_RE.test(value.version_range)
  ) {
    throw new TypeError(
      "version_range: must be a version range like '>=2.0 <3.0'",
    );
  }

  return {
    tool: oneOf(TOOL_FAMILIES, value.tool, "tool"),
    version_range: value.version_range,
    surface: oneOf(UI_SURFACES, value.surface, "surface"),
    control_id: controlId(value.control_id),
    label: vendorText(value.label, "label"),
    effect: oneOf(CONTROL_EFFECTS, value.effect, "effect"),
    description: vendorText(value.description, "description"),
    invocation: parseInvocation(value.invocation),
    locator: parseLocator(value.locator),
    provenance: oneOf(PROVENANCES, value.provenance, "provenance"),
  };
}

// ── the field lists the drift guard checks against (see action-gate.ts) ──────

const TK = [
  "tool",
  "version_range",
  "surface",
  "control_id",
  "label",
  "effect",
  "description",
  "invocation",
  "locator",
  "provenance",
] as const;
export const TOOL_KNOWLEDGE_FIELDS: CompleteKeysOf<ToolKnowledge, typeof TK> =
  TK;

const INV = ["menu_path", "shortcut"] as const;
export const INVOCATION_FIELDS: CompleteKeysOf<Invocation, typeof INV> = INV;

const SL = ["x", "y", "w", "h"] as const;
export const SCREEN_LOCATOR_FIELDS: CompleteKeysOf<ScreenLocator, typeof SL> =
  SL;
