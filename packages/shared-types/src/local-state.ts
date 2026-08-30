// SOLUSDEV-166 (ADR-034) — machine-local state files under `~/.solus`.
// docs/contracts/local-state.md
//
// The desktop MAIN process writes these files; the Python companion reads them
// (solus_contracts.local_state is the same shape). Both sides validate the
// shared fixtures in fixtures/local-state/, so the definitions cannot drift
// (json.ts pattern).
//
// Ground rules (ADR-034):
//   - JSON only; every file carries `schema_version`; writes are atomic
//     (temp + rename) and `~/.solus` is 0700.
//   - NO secrets, ever — HOME survives the companion's `env -i` scrub, so MCP
//     fork processes can read this directory.
//   - A reader that finds a NEWER `schema_version` must leave the file
//     untouched (`"newer"`), never rewrite it: that is data a future version
//     wrote, and clobbering it turns a downgrade into data loss.

import type { CompleteKeysOf } from "./json";

export const SOLUS_HOME_DIRNAME = ".solus";
export const PROJECTS_FILENAME = "projects.json";
/** `~/.solus` permission bits — private to the user. */
export const SOLUS_HOME_MODE = 0o700;
export const PROJECT_REGISTRY_SCHEMA_VERSION = 1;

/**
 * Registry keys are project ids, and a project id becomes a PATH SEGMENT later
 * (`~/.solus/projects/<id>/`), so anything with a slash, a dot-segment or an
 * escape is refused at the contract boundary. Same shape the companion's
 * bridge URL derivation enforces (`companionEnv.ts` SAFE_PROJECT_ID).
 */
export const PROJECT_ID_RE = /^[A-Za-z0-9_-]+$/;

/** Ids that collide with object internals — `projects["__proto__"] = link`
 *  hits the prototype setter and silently drops the entry (SOLUSDEV-166 review
 *  L7). PROJECT_ID_RE admits them, so they are excluded explicitly. */
const RESERVED_PROJECT_IDS = new Set(["__proto__", "constructor", "prototype"]);

/** One project's link to a working copy on THIS machine. */
export interface ProjectFolderLink {
  /** Absolute path of the working copy. Non-empty. */
  readonly path: string;
  /** The repo it was cloned from, when linked via clone (informational). */
  readonly repoUrl?: string;
  /** ISO-8601 instant the project was last opened here (informational). */
  readonly lastOpenedAt?: string;
}

/** The whole of `~/.solus/projects.json`. */
export interface ProjectRegistry {
  readonly schema_version: number;
  readonly projects: Readonly<Record<string, ProjectFolderLink>>;
}

// Runtime field lists, proven complete against the interfaces at compile time
// and compared to the Python-emitted manifest (_fields.json) in the test.
const LINK_FIELDS = ["path", "repoUrl", "lastOpenedAt"] as const;
export const PROJECT_FOLDER_LINK_FIELDS: CompleteKeysOf<
  ProjectFolderLink,
  typeof LINK_FIELDS
> = LINK_FIELDS;
const REGISTRY_FIELDS = ["schema_version", "projects"] as const;
export const PROJECT_REGISTRY_FIELDS: CompleteKeysOf<
  ProjectRegistry,
  typeof REGISTRY_FIELDS
> = REGISTRY_FIELDS;

export type RegistryParseResult =
  | { readonly ok: true; readonly registry: ProjectRegistry }
  | { readonly ok: false; readonly reason: "invalid" | "newer" };

const INVALID: RegistryParseResult = { ok: false, reason: "invalid" };

/** A registry with nothing in it — what a fresh machine starts from. */
export function emptyProjectRegistry(): ProjectRegistry {
  return { schema_version: PROJECT_REGISTRY_SCHEMA_VERSION, projects: {} };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKnownKeys(
  value: Record<string, unknown>,
  known: readonly string[],
): boolean {
  return Object.keys(value).every((key) => known.includes(key));
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === "string";
}

/** Strict parse of one link — unknown fields reject, mirroring the Python
 *  model's `extra="forbid"`. Null means invalid. */
function parseFolderLink(value: unknown): ProjectFolderLink | null {
  if (!isPlainObject(value) || !hasOnlyKnownKeys(value, LINK_FIELDS))
    return null;
  const { path, repoUrl, lastOpenedAt } = value;
  if (typeof path !== "string" || path.length === 0) return null;
  if (!isOptionalString(repoUrl) || !isOptionalString(lastOpenedAt))
    return null;
  return {
    path,
    ...(repoUrl !== undefined ? { repoUrl } : {}),
    ...(lastOpenedAt !== undefined ? { lastOpenedAt } : {}),
  };
}

/** Every entry strictly parsed, keyed by a safe project id; null means the
 *  map (or any entry in it) is invalid. */
function parseProjects(
  value: unknown,
): Record<string, ProjectFolderLink> | null {
  if (!isPlainObject(value)) return null;
  // Null-prototype map so a hostile id cannot reach Object.prototype at all.
  const projects: Record<string, ProjectFolderLink> = Object.create(null);
  for (const [projectId, raw] of Object.entries(value)) {
    if (!PROJECT_ID_RE.test(projectId) || RESERVED_PROJECT_IDS.has(projectId))
      return null;
    const link = parseFolderLink(raw);
    if (link === null) return null;
    projects[projectId] = link;
  }
  return projects;
}

/**
 * Validating parse of untrusted file content (a corrupted or hand-edited file
 * must never crash a reader). `"newer"` when the file was written by a later
 * schema version — the caller must then treat the file as READ-ONLY.
 */
export function parseProjectRegistry(value: unknown): RegistryParseResult {
  if (!isPlainObject(value) || !hasOnlyKnownKeys(value, REGISTRY_FIELDS))
    return INVALID;
  const version = value.schema_version;
  if (typeof version !== "number" || !Number.isInteger(version) || version < 1)
    return INVALID;
  if (version > PROJECT_REGISTRY_SCHEMA_VERSION)
    return { ok: false, reason: "newer" };
  const projects = parseProjects(value.projects);
  if (projects === null) return INVALID;
  return { ok: true, registry: { schema_version: version, projects } };
}
