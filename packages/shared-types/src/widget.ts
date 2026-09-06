// SOLUSDEV-216 (CTR-01) — the widget framework contract.
//
// THE LOAD-BEARING DECISION IS MANIFEST-BASED SELF-REGISTRATION. Each widget
// declares itself in a `widget.manifest.ts` inside its own directory, and the
// canvas discovers them with a glob import. There is no central registry file,
// no switch statement, and no array in a shared module — because that file
// would be edited by every lane every time a widget is added, and six lanes
// conflicting on one file is precisely what this ticket exists to prevent.
//
// The corollary: a lane can build a widget with NO CANVAS IN THE REPO. The
// canvas is the thing that renders manifests; nothing in this file needs it.
// See docs/contracts/widget.md.

import type { ComponentType } from "react";
import type { Domain, Focus } from "./focus";

const DOMAINS: readonly Domain[] = [
  "code",
  "electrical",
  "mechanical",
  "simulation",
  "runtime",
  "workspace",
];
const SLOT_SIZES = ["compact", "standard", "wide", "full"] as const;
/** Stable, URL-safe, lowercase. The id appears in saved layouts and telemetry. */
const WIDGET_ID_RE = /^[a-z][a-z0-9-]*$/;

/**
 * How much of the canvas a widget would like.
 *
 * Deliberately a coarse slot, not a grid measurement: the grid is LANE B's to
 * design, and a widget guessing at column counts would foreclose it. This is a
 * hint the canvas may override.
 */
export type WidgetSlotSize = (typeof SLOT_SIZES)[number];

export interface WidgetSizeHint {
  readonly preferred: WidgetSlotSize;
  /** Below this the widget is not worth rendering; the canvas may hide it. */
  readonly minimum?: WidgetSlotSize;
  /** Default true. Set false for a widget with a fixed intrinsic size. */
  readonly resizable?: boolean;
}

/**
 * What a widget is showing right now.
 *
 * Every widget has all four states — a widget that only ever renders data has
 * simply not met an empty project or a failed fetch yet. Naming them in the
 * contract is what stops each lane inventing its own spinner and error card.
 */
export type WidgetRenderState = "loading" | "empty" | "error" | "ready";

/**
 * What the canvas hands every widget. This is the whole surface: a widget that
 * needs more reaches for the typed API client or its own store, not for a
 * wider prop bag that every other lane then has to satisfy.
 */
export interface WidgetProps {
  /** What the user is looking at. `null` before anything is focused. */
  readonly focus: Focus | null;
  /**
   * Report a focus change. The canvas owns the store; a widget never calls
   * `set` on it directly, so focus changes stay routable and loggable.
   */
  readonly onFocusChange: (focus: Focus | null) => void;
  /**
   * Report render state so the canvas can show chrome (a slot skeleton, an
   * error badge) without reaching inside the widget. Optional: a widget that
   * renders its own states throughout may ignore it.
   */
  readonly onStateChange?: (state: WidgetRenderState) => void;
}

/** A widget is a React component over `WidgetProps`. Nothing more. */
export type Widget = ComponentType<WidgetProps>;

/**
 * Resource setup/teardown that must happen OUTSIDE React's render tree.
 *
 * ponytail: React's `useEffect` cleanup covers the ordinary case and widgets
 * should use it. These hooks exist for resources a widget must hold before
 * first paint or across a remount — a Live Bench socket, an overlay window.
 * Optional by design; most widgets will never define them.
 */
export interface WidgetLifecycle {
  readonly mount?: () => void | Promise<void>;
  readonly unmount?: () => void | Promise<void>;
}

/**
 * A widget's self-declaration. Lives at `<widget-dir>/widget.manifest.ts` as
 * the DEFAULT export, and is the only thing the canvas needs to render it.
 */
export interface WidgetManifest {
  /** Stable slug, unique across all lanes. Appears in saved layouts. */
  readonly id: string;
  /** Human-readable, shown in the widget's chrome and the add-widget picker. */
  readonly title: string;
  /** Domains this widget is relevant to. Empty means "relevant everywhere". */
  readonly domains: readonly Domain[];
  readonly size: WidgetSizeHint;
  readonly component: Widget;
  readonly lifecycle?: WidgetLifecycle;
}

/** What a `import.meta.glob(..., { eager: true })` call evaluates to. */
export type WidgetModules = Record<string, unknown>;

function fail(path: string, message: string): never {
  throw new Error(`${path}: ${message}`);
}

/** One field, one check. Each returns an error string, or null if the field is fine. */
const FIELD_CHECKS: readonly ((m: Record<string, unknown>) => string | null)[] =
  [
    (m) =>
      typeof m.id === "string" && WIDGET_ID_RE.test(m.id)
        ? null
        : `manifest id must be a lowercase slug matching ${WIDGET_ID_RE}, got ${JSON.stringify(m.id)}`,

    (m) =>
      typeof m.title === "string" && m.title.length > 0
        ? null
        : "manifest title must be a non-empty string",

    (m) =>
      Array.isArray(m.domains) &&
      m.domains.every((d) => DOMAINS.includes(d as Domain))
        ? null
        : `manifest domains must be a subset of ${DOMAINS.join(", ")}`,

    (m) =>
      isValidSize(m.size)
        ? null
        : `manifest size must name a slot from ${SLOT_SIZES.join(", ")}`,

    // Function components, plus the object forms React produces (memo, forwardRef).
    (m) =>
      typeof m.component === "function" ||
      (typeof m.component === "object" && m.component !== null)
        ? null
        : "manifest component must be a React component",

    (m) => checkLifecycle(m.lifecycle),
  ];

function isValidSize(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false;
  const size = value as WidgetSizeHint;
  if (!SLOT_SIZES.includes(size.preferred)) return false;
  return size.minimum === undefined || SLOT_SIZES.includes(size.minimum);
}

function checkLifecycle(value: unknown): string | null {
  if (value === undefined) return null;
  if (typeof value !== "object" || value === null)
    return "manifest lifecycle must be an object";
  const lifecycle = value as WidgetLifecycle;
  for (const hook of ["mount", "unmount"] as const) {
    const fn = lifecycle[hook];
    if (fn !== undefined && typeof fn !== "function")
      return `manifest lifecycle.${hook} must be a function`;
  }
  return null;
}

function validate(path: string, value: unknown): WidgetManifest {
  if (typeof value !== "object" || value === null)
    fail(path, "manifest must be an object");
  const m = value as Record<string, unknown>;
  for (const check of FIELD_CHECKS) {
    const problem = check(m);
    if (problem !== null) fail(path, problem);
  }
  return m as unknown as WidgetManifest;
}

/**
 * Turn a glob import into the canvas's widget list.
 *
 * Takes the RESULT of `import.meta.glob(..., { eager: true })` rather than doing
 * the glob itself: `import.meta.glob` is a Vite transform, so a loader that
 * called it could only run inside the bundler. Passing the modules in keeps this
 * pure, keeps `shared-types` framework-free, and makes the whole discovery rule
 * testable with a plain object.
 *
 * THROWS on a malformed or duplicated manifest, naming the module path. These
 * are in-repo build-time errors, not untrusted input — a loader that silently
 * skipped a broken widget would ship a workspace with a widget mysteriously
 * missing and no way to tell why.
 */
export function collectManifests(modules: WidgetModules): WidgetManifest[] {
  const byId = new Map<string, string>();
  const manifests: WidgetManifest[] = [];

  for (const path of Object.keys(modules).sort()) {
    const mod = modules[path];
    if (typeof mod !== "object" || mod === null || !("default" in mod)) {
      fail(path, "widget.manifest.ts must have a default export");
    }
    const parsed = validate(path, (mod as { default: unknown }).default);
    const seen = byId.get(parsed.id);
    if (seen !== undefined)
      fail(
        path,
        `duplicate widget id "${parsed.id}" — already declared by ${seen}`,
      );
    byId.set(parsed.id, path);
    manifests.push(parsed);
  }

  // Stable order: bundlers do not promise glob ordering, and a canvas that
  // rendered in load order would reshuffle its layout between builds.
  return manifests.sort((a, b) => a.id.localeCompare(b.id));
}
