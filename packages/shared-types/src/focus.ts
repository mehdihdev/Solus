// SOLUSDEV-217 (CTR-02) — the shared-focus contract.
//
// WS-01 (the focus engine) and WS-03 (the widget canvas) each listed the other
// as a dependency — a deadlock. They do not depend on each other's CODE; they
// both depend on the SHAPE of focus. That shape is this file, so WS-01
// implements the store, WS-03 consumes it, and either can be built first.
//
// Focus is the workspace's one piece of ambient state: what the user is looking
// at. Every widget receives it, and any widget may change it. See
// docs/contracts/focus.md.

/**
 * The domains the graph spans. Mirrors `solus_api.models.Domain` (ADR-027) —
 * exactly these six, in these spellings. Adding one is a graph-wide decision,
 * not a frontend one. `project` (SOLUSDEV-240: the `.solus` node and imported documents)
 * and `workspace` (SOLUSDEV-246 ST2: the root, Live Bench and installed widgets) are the
 * two layers beyond the four robot domains and runtime.
 */
export const DOMAINS = [
  "code",
  "electrical",
  "mechanical",
  "simulation",
  "runtime",
  "project",
  "workspace",
] as const;
export type Domain = (typeof DOMAINS)[number];

/**
 * A graph entity, addressed the way the API returns it.
 *
 * `projectId` travels WITH the entity rather than being ambient. A focus is
 * scoped to one project, and carrying the scope in the value is what lets
 * `descend` refuse a cross-project trail instead of trusting a caller's context.
 */
export interface EntityRef {
  /** `project.id` — the tenant scope this entity belongs to. */
  readonly projectId: string;
  /** `graph_entity.id`. */
  readonly entityId: string;
}

/**
 * One hop of the trail that led to the current focus.
 *
 * `relation` is the edge traversed FROM this step toward the NEXT one (the
 * following step, or the focus itself for the last step). Defining it forward
 * rather than backward means every step has one — there is no null origin case
 * for consumers to special-case.
 */
export interface FocusStep {
  readonly entity: EntityRef;
  readonly domain: Domain;
  /** Display name, cached from the graph so a breadcrumb needs no fetch. */
  readonly label?: string;
  /** `graph_edge.relation_type`, e.g. "drives", "connected_to", "mates_with". */
  readonly relation: string;
}

/**
 * What the user is looking at, and how they got there.
 *
 * `path` is the ancestry EXCLUDING the current entity, oldest first. A
 * breadcrumb renders `[...focus.path, focus]`; an empty path means the user
 * landed here directly (search, deep link, a widget's own list).
 */
export interface Focus {
  readonly entity: EntityRef;
  readonly domain: Domain;
  /** Display name, cached from the graph. */
  readonly label?: string;
  readonly path: readonly FocusStep[];
}

/** Called with the new focus whenever it changes. */
export type FocusListener = (focus: Focus | null) => void;

/**
 * The subscribe/set surface. WS-01 implements this over the real engine; until
 * it lands, `createFocusStore()` below is a drop-in.
 *
 * Deliberately three methods. A store that also owned selection, history, or
 * layout would be a second thing six lanes have to agree on.
 */
export interface FocusStore {
  /** The current focus, or null when nothing is focused. */
  get(): Focus | null;
  /** Replace the focus. A no-op set does not notify. */
  set(focus: Focus | null): void;
  /** Subscribe to changes. Returns an idempotent unsubscribe. */
  subscribe(listener: FocusListener): () => void;
}

/** Whether two refs point at the same entity in the same project. */
export function isSameEntity(a: EntityRef, b: EntityRef): boolean {
  return a.projectId === b.projectId && a.entityId === b.entityId;
}

function isSameFocus(a: Focus | null, b: Focus | null): boolean {
  if (a === null || b === null) return a === b;
  if (!isSameEntity(a.entity, b.entity) || a.path.length !== b.path.length)
    return false;
  // The trail is part of the state, not decoration: reaching the same entity by
  // a different route is a different focus, and a breadcrumb that did not
  // update would be lying about how the user got there.
  return a.path.every((step, i) => {
    const other = b.path[i]!;
    return (
      isSameEntity(step.entity, other.entity) &&
      step.relation === other.relation
    );
  });
}

/**
 * Move focus to a related entity, recording the hop.
 *
 * Every widget that offers "jump to this" needs exactly this operation; six
 * lanes hand-rolling it is six subtly different breadcrumbs. Pure — the focus
 * passed in is never mutated.
 */
export function descend(
  from: Focus,
  to: { entity: EntityRef; domain: Domain; label?: string; relation: string },
): Focus {
  if (from.entity.projectId !== to.entity.projectId) {
    throw new Error(
      `descend: refusing to cross a project boundary (${from.entity.projectId} -> ${to.entity.projectId}). ` +
        "A focus is scoped to one project.",
    );
  }
  const step: FocusStep = {
    entity: from.entity,
    domain: from.domain,
    ...(from.label === undefined ? {} : { label: from.label }),
    relation: to.relation,
  };
  return {
    entity: to.entity,
    domain: to.domain,
    ...(to.label === undefined ? {} : { label: to.label }),
    path: [...from.path, step],
  };
}

/**
 * An in-memory `FocusStore`. THE REFERENCE IMPLEMENTATION — consumers develop
 * and test against this before the real engine exists, and its behaviour is the
 * contract WS-01 must honour.
 *
 * No dependency on Zustand or any store library: the whole thing is shorter
 * than the argument for adding one, and shared-types stays framework-free so a
 * lane can import it into a plain node test.
 */
export function createFocusStore(initial: Focus | null = null): FocusStore {
  let current = initial;
  const listeners = new Set<FocusListener>();

  return {
    get: () => current,

    set(focus) {
      // A widget re-emitting the focus it was just handed must not loop the app.
      if (isSameFocus(current, focus)) return;
      current = focus;
      // Snapshot: a listener may unsubscribe (or subscribe) during delivery, and
      // iterating the live Set would silently skip its neighbour.
      for (const listener of [...listeners]) {
        try {
          listener(focus);
        } catch {
          // One broken widget must not stop the rest of the workspace updating,
          // and must not leave the store half-notified. Swallowed rather than
          // logged: shared-types has no logger, and the renderer's error
          // boundary is where a widget crash belongs.
        }
      }
    },

    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

// ── parsing ──────────────────────────────────────────────────────────────────

/** A breadcrumb longer than this is not a breadcrumb. Bounds an IPC/API payload. */
export const MAX_FOCUS_PATH = 16;
const MAX_FOCUS_STRING = 512;

function focusString(value: unknown, what: string): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > MAX_FOCUS_STRING
  ) {
    throw new TypeError(
      `${what}: must be a non-empty string under ${MAX_FOCUS_STRING} chars`,
    );
  }
  return value;
}

function parseEntityRef(raw: unknown, what: string): EntityRef {
  if (typeof raw !== "object" || raw === null)
    throw new TypeError(`${what}: must be an object`);
  const value = raw as Record<string, unknown>;
  return {
    // projectId is the TENANT SCOPE. It is the last field that should arrive
    // unexamined, and it used to cross the orb↔overlay IPC boundary as a cast.
    projectId: focusString(value.projectId, `${what}.projectId`),
    entityId: focusString(value.entityId, `${what}.entityId`),
  };
}

function parseDomain(raw: unknown, what: string): Domain {
  if (
    typeof raw !== "string" ||
    !(DOMAINS as readonly string[]).includes(raw)
  ) {
    throw new TypeError(`${what}: must be one of ${DOMAINS.join(", ")}`);
  }
  return raw as Domain;
}

/**
 * Parse an untrusted `Focus`, or throw.
 *
 * Focus travels across the orb↔overlay IPC boundary, which is a PROCESS boundary
 * and therefore untrusted input (CLAUDE.md §7) — the overlay in particular is the
 * process that attaches itself to third-party tool windows. Every field is
 * rebuilt as a FRESH literal, so an undeclared key on the sender's object cannot
 * ride along into whatever consumes the message.
 */
export function parseFocus(raw: unknown): Focus | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== "object")
    throw new TypeError("focus: must be an object or null");
  const value = raw as Record<string, unknown>;

  const rawPath = value.path ?? [];
  if (!Array.isArray(rawPath))
    throw new TypeError("focus.path: must be an array");
  if (rawPath.length > MAX_FOCUS_PATH) {
    throw new TypeError(`focus.path: at most ${MAX_FOCUS_PATH} steps`);
  }

  const path: FocusStep[] = rawPath.map((step, i) => {
    if (typeof step !== "object" || step === null) {
      throw new TypeError(`focus.path[${i}]: must be an object`);
    }
    const s = step as Record<string, unknown>;
    return {
      entity: parseEntityRef(s.entity, `focus.path[${i}].entity`),
      domain: parseDomain(s.domain, `focus.path[${i}].domain`),
      ...(s.label === undefined || s.label === null
        ? {}
        : { label: focusString(s.label, `focus.path[${i}].label`) }),
      relation: focusString(s.relation, `focus.path[${i}].relation`),
    };
  });

  return {
    entity: parseEntityRef(value.entity, "focus.entity"),
    domain: parseDomain(value.domain, "focus.domain"),
    ...(value.label === undefined || value.label === null
      ? {}
      : { label: focusString(value.label, "focus.label") }),
    path,
  };
}
