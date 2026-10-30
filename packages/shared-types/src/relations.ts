// SOLUSDEV-320 — the relation vocabulary, TypeScript twin of
// `solus_contracts.relations`. The Python side writes
// `fixtures/relations/_values.json`; `relations.test.ts` asserts these constants
// match it, so a value added on either side fails one suite.
//
// An edge says what kind of connection it is (class), which way it runs (type
// docstring on the Python side; `MatrixCell` here), what evidence made it and
// whether it is still a candidate (`isCandidate`).

export const RELATION_CLASSES = [
  "identity",
  "structure",
  "dependency",
  "outcome",
  "legacy",
] as const;
export type RelationClass = (typeof RELATION_CLASSES)[number];

export const RELATION_TYPES = [
  "same_as",
  "contains",
  "part_of",
  "commands",
  "reads",
  "wires",
  "powers",
  "drives",
  "mounts",
  "mates_with",
  "limits",
  "depends_on",
  "requires",
  "hosts",
  "publishes",
  "subscribes",
  "measured_by",
  "observed",
  "fixed_by",
  "verified_by",
  "connected_to",
  "configures",
  "binds",
  "hardware_connected_to",
  "hardware_topology_member",
  "hardware_evidence_for",
  "presence_prepared_for",
  "wiring_proposed_for",
  "deployment_for_target",
  "cad_visual_for",
  "clone_of",
  "references",
  "reads_from",
] as const;
export type RelationType = (typeof RELATION_TYPES)[number];

export const RELATION_CLASS: Readonly<Record<RelationType, RelationClass>> = {
  same_as: "identity",
  contains: "structure",
  part_of: "structure",
  commands: "dependency",
  reads: "dependency",
  wires: "dependency",
  powers: "dependency",
  drives: "dependency",
  mounts: "dependency",
  mates_with: "dependency",
  limits: "dependency",
  depends_on: "dependency",
  requires: "dependency",
  hosts: "dependency",
  publishes: "dependency",
  subscribes: "dependency",
  measured_by: "outcome",
  observed: "outcome",
  fixed_by: "outcome",
  verified_by: "outcome",
  connected_to: "legacy",
  configures: "legacy",
  binds: "legacy",
  hardware_connected_to: "legacy",
  hardware_topology_member: "legacy",
  hardware_evidence_for: "legacy",
  presence_prepared_for: "legacy",
  wiring_proposed_for: "legacy",
  deployment_for_target: "legacy",
  cad_visual_for: "legacy",
  clone_of: "legacy",
  references: "legacy",
  reads_from: "legacy",
};

export const EDGE_ORIGINS = [
  "connector",
  "manual",
  "inferred",
  "fingerprint",
  "system",
] as const;
export type EdgeOrigin = (typeof EDGE_ORIGINS)[number];

export const MATRIX_CELLS = [
  "software->software",
  "software->electrical",
  "software->mechanical",
  "electrical->software",
  "electrical->electrical",
  "electrical->mechanical",
  "mechanical->software",
  "mechanical->electrical",
  "mechanical->mechanical",
] as const;
export type MatrixCell = (typeof MATRIX_CELLS)[number];

export const EVIDENCE_KINDS = [
  "netlist",
  "firmware_symbol",
  "bus_enumeration",
  "mate",
  "manifest",
  "config",
  "fingerprint",
  "user_confirmed",
  "checker",
  "telemetry_routing",
  "run",
  "sim",
] as const;
export type EvidenceKind = (typeof EVIDENCE_KINDS)[number];

export interface EdgeEvidence {
  readonly kind: EvidenceKind;
  readonly ref: string;
  readonly detail?: string | null;
}
export const EDGE_EVIDENCE_FIELDS = [
  "detail",
  "kind",
  "ref",
] as const satisfies readonly (keyof EdgeEvidence)[];

/** Inferred edges below this confidence are candidates: drawn dashed, never treated as facts. */
export const CANDIDATE_THRESHOLD = 0.8;

const GRAPH_DOMAINS = new Set([
  "code",
  "electrical",
  "mechanical",
  "simulation",
  "runtime",
  "project",
  "workspace",
]);
const MATRIX_DOMAIN: Readonly<Record<string, string>> = {
  code: "software",
  electrical: "electrical",
  mechanical: "mechanical",
};

/** The class of a relation type; unknown (free-string) types read as `legacy` so the canvas never throws. */
export function relationClass(type: string): RelationClass {
  return (
    (RELATION_CLASS as Readonly<Record<string, RelationClass | undefined>>)[
      type
    ] ?? "legacy"
  );
}

/** `"a<->b"` with the domains in alphabetical order; `null` when either is not a graph domain. */
export function normalizeDomainPair(a: string, b: string): string | null {
  if (!GRAPH_DOMAINS.has(a) || !GRAPH_DOMAINS.has(b)) return null;
  const [lo, hi] = [a, b].sort();
  return `${lo}<->${hi}`;
}

/** The matrix cell for src → dst, or `null` outside the three worlds. */
export function matrixCell(
  srcDomain: string,
  dstDomain: string,
): MatrixCell | null {
  const src = MATRIX_DOMAIN[srcDomain];
  const dst = MATRIX_DOMAIN[dstDomain];
  if (src === undefined || dst === undefined) return null;
  return `${src}->${dst}` as MatrixCell;
}

export function isCandidate(
  origin: string | undefined,
  confidence: number | undefined,
): boolean {
  return (
    origin === "inferred" &&
    typeof confidence === "number" &&
    confidence < CANDIDATE_THRESHOLD
  );
}
