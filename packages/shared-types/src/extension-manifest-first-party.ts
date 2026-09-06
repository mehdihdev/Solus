// SOLUSDEV-246 (STORE ST1) — the schema_version 2 first-party tables of
// `extension.toml`: `[backend]`, `[graph]`, `[tools]`. Python twin:
// solus_contracts.extension_manifest (Backend / GraphKind / Graph / Tools).
//
// These tables are a CLAIM. A manifest is untrusted developer input, so the
// desktop does nothing with them beyond parsing; the publish validator demands
// a staff publisher and an in-repo capability package before a version that
// declares any of them becomes visible (CLAUDE.md §7 — Solus code decides).
// They are unknown fields at schema_version 1, which is why a bundle that
// predates them fails exactly as it always did.

/** Every schema this parser accepts; the last entry is the one it writes. */
export const SUPPORTED_SCHEMA_VERSIONS = [1, 2] as const;
export const FIRST_PARTY_TABLES = ["backend", "graph", "tools"] as const;

/** Graph-kind and SOL-tool names: snake_case, ≤ 32, so `<id>.<name>` stays
 *  under the provider's 128-char tool-name cap (id ≤ 64). */
export const CAPABILITY_NAME_RE = /^[a-z][a-z0-9_]{0,31}$/;
/** The graph's Domain vocabulary (ADR-027). */
export const GRAPH_DOMAINS = [
  "code",
  "electrical",
  "mechanical",
  "simulation",
  "runtime",
  "workspace",
] as const;
export type GraphDomain = (typeof GRAPH_DOMAINS)[number];

export const FIRST_PARTY_LIMITS = {
  graphKinds: 8,
  toolNames: 16,
} as const;

export interface Backend {
  /** Must equal `extension.id`; names the in-repo capability package. */
  readonly capability: string;
  readonly routes: boolean;
}

export interface GraphKind {
  readonly name: string;
  readonly domain: GraphDomain;
}

export interface Graph {
  readonly kinds: readonly GraphKind[];
}

export interface Tools {
  readonly names: readonly string[];
}

/** Compile-time completeness guard, shared with the main parser. */
type CompleteKeysOf<T, K extends readonly (keyof T)[]> =
  Exclude<keyof T, K[number]> extends never ? K : never;

const BACKEND = ["capability", "routes"] as const;
export const BACKEND_FIELDS: CompleteKeysOf<Backend, typeof BACKEND> = BACKEND;
const GRAPH = ["kinds"] as const;
export const GRAPH_FIELDS: CompleteKeysOf<Graph, typeof GRAPH> = GRAPH;
const GRAPH_KIND = ["name", "domain"] as const;
export const GRAPH_KIND_FIELDS: CompleteKeysOf<GraphKind, typeof GRAPH_KIND> =
  GRAPH_KIND;
const TOOLS = ["names"] as const;
export const TOOLS_FIELDS: CompleteKeysOf<Tools, typeof TOOLS> = TOOLS;

/** What the main parser's `Problems` collector looks like from here. */
export interface ProblemSink {
  add(path: string, message: string): void;
}

function isTable(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function rejectUnknown(
  p: ProblemSink,
  path: string,
  v: Record<string, unknown>,
  known: readonly string[],
): void {
  for (const key of Object.keys(v))
    if (!known.includes(key)) p.add(`${path}.${key}`, "unknown field");
}

function capabilityName(
  p: ProblemSink,
  path: string,
  v: unknown,
): string | undefined {
  if (typeof v !== "string" || !CAPABILITY_NAME_RE.test(v)) {
    p.add(path, "must be a lowercase snake_case name (≤32 chars)");
    return undefined;
  }
  return v;
}

function distinct(p: ProblemSink, path: string, items: readonly string[]) {
  if (new Set(items).size !== items.length)
    p.add(path, "entries must be distinct");
}

/** `[backend]` — absent when undeclared. The capability/id equality is checked
 *  by the caller, which holds both. */
export function parseBackend(
  p: ProblemSink,
  v: unknown,
  extensionIdRe: RegExp,
): Backend | undefined {
  if (v === undefined) return undefined;
  if (!isTable(v)) return void p.add("backend", "must be a table");
  rejectUnknown(p, "backend", v, BACKEND);
  const capability =
    typeof v.capability === "string" && extensionIdRe.test(v.capability)
      ? v.capability
      : undefined;
  if (!capability)
    p.add("backend.capability", "must be a lowercase slug (2–64 chars)");
  if (v.routes !== undefined && typeof v.routes !== "boolean")
    p.add("backend.routes", "must be a boolean");
  if (!capability) return undefined;
  return { capability, routes: v.routes === true };
}

function parseGraphKind(
  p: ProblemSink,
  path: string,
  v: unknown,
): GraphKind | undefined {
  if (!isTable(v)) return void p.add(path, "must be a table");
  rejectUnknown(p, path, v, GRAPH_KIND);
  const name = capabilityName(p, `${path}.name`, v.name);
  const domain = (GRAPH_DOMAINS as readonly string[]).includes(
    v.domain as string,
  )
    ? (v.domain as GraphDomain)
    : undefined;
  if (!domain)
    p.add(`${path}.domain`, `must be one of ${GRAPH_DOMAINS.join(", ")}`);
  return name && domain ? { name, domain } : undefined;
}

/** `[graph]` — `{ kinds: [] }` when undeclared. */
export function parseGraph(p: ProblemSink, v: unknown): Graph {
  if (v === undefined) return { kinds: [] };
  if (!isTable(v)) {
    p.add("graph", "must be a table");
    return { kinds: [] };
  }
  rejectUnknown(p, "graph", v, GRAPH);
  const raw = v.kinds ?? [];
  if (!Array.isArray(raw) || raw.length > FIRST_PARTY_LIMITS.graphKinds) {
    p.add(
      "graph.kinds",
      `must be a list of at most ${FIRST_PARTY_LIMITS.graphKinds} kinds`,
    );
    return { kinds: [] };
  }
  const kinds = raw
    .map((k, i) => parseGraphKind(p, `graph.kinds.${i}`, k))
    .filter((k): k is GraphKind => k !== undefined);
  distinct(
    p,
    "graph.kinds",
    kinds.map((k) => k.name),
  );
  return { kinds };
}

/** `[tools]` — `{ names: [] }` when undeclared. */
export function parseTools(p: ProblemSink, v: unknown): Tools {
  if (v === undefined) return { names: [] };
  if (!isTable(v)) {
    p.add("tools", "must be a table");
    return { names: [] };
  }
  rejectUnknown(p, "tools", v, TOOLS);
  const raw = v.names ?? [];
  if (!Array.isArray(raw) || raw.length > FIRST_PARTY_LIMITS.toolNames) {
    p.add(
      "tools.names",
      `must be a list of at most ${FIRST_PARTY_LIMITS.toolNames} names`,
    );
    return { names: [] };
  }
  const names = raw
    .map((n, i) => capabilityName(p, `tools.names.${i}`, n))
    .filter((n): n is string => n !== undefined);
  distinct(p, "tools.names", names);
  return { names };
}

/** The `graph_entity.kind` a declared kind lands as. */
export function graphKindName(extensionId: string, name: string): string {
  return `ext:${extensionId}:${name}`;
}

/** The `ToolDescriptor.name` a declared tool registers as — dotted, like
 *  `solus.*` and `{server}.{tool}`; the prompt layer translates it. */
export function composedToolName(extensionId: string, name: string): string {
  return `${extensionId}.${name}`;
}

/** True when any first-party table is in use: the publish validator then
 *  demands a staff publisher and a matching in-repo capability. */
export function declaresFirstParty(m: {
  readonly backend?: Backend;
  readonly graph: Graph;
  readonly tools: Tools;
}): boolean {
  return (
    m.backend !== undefined ||
    m.graph.kinds.length > 0 ||
    m.tools.names.length > 0
  );
}
