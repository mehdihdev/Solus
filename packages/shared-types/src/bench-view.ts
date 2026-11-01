// SOLUSDEV-319 — the team-shared Live Bench view: display settings, derived signals,
// and the versioned PATCH that edits them. docs/api/bench-view.md §1–§3 (frozen).
// A telemetry signal is the PAIR (device_id, signal): device ids may contain "/",
// so no shape here ever joins them into one string.

export interface SignalTarget {
  kind: "signal";
  device_id: string;
  signal: string;
}
export interface DerivedTarget {
  kind: "derived";
  id: string;
}
export type BenchViewTarget = SignalTarget | DerivedTarget;

export interface BenchViewLimits {
  min: number;
  max: number;
}

/** One non-default display entry; absent targets show with defaults. */
export interface BenchViewDisplayEntry {
  target: BenchViewTarget;
  pinned: boolean;
  hidden: boolean;
  order: number | null;
  unit: string | null;
  limits: BenchViewLimits | null;
  plot_group: string | null;
}

export interface BenchViewSignalRef {
  device_id: string;
  signal: string;
}

/** A derived signal. `node_count` and `refs` are server-computed, never sent. */
export interface BenchViewDerived {
  id: string;
  name: string;
  expression: string;
  unit: string | null;
  node_count: number;
  refs: BenchViewSignalRef[];
  created_at: string;
  updated_at: string;
}

/** `GET /projects/{id}/bench/view` data. */
export interface BenchView {
  version: number;
  display: BenchViewDisplayEntry[];
  derived: BenchViewDerived[];
  updated_at: string | null;
}

/** `null` resets a field to its default (false for pinned/hidden). */
export interface BenchViewDisplayPatch {
  pinned?: boolean | null;
  hidden?: boolean | null;
  order?: number | null;
  unit?: string | null;
  limits?: BenchViewLimits | null;
  plot_group?: string | null;
}

export interface SetDisplayOp {
  kind: "set_display";
  target: BenchViewTarget;
  patch: BenchViewDisplayPatch;
}
export interface UpsertDerivedOp {
  kind: "upsert_derived";
  id?: string;
  name: string;
  expression: string;
  unit?: string | null;
}
export interface DeleteDerivedOp {
  kind: "delete_derived";
  id: string;
}
export type BenchViewOp = SetDisplayOp | UpsertDerivedOp | DeleteDerivedOp;

/** `PATCH /view` body. `undo` is true only when `ops` are a returned `inverse_ops`. */
export interface BenchViewPatchBody {
  version: number;
  ops: BenchViewOp[];
  undo?: boolean;
}

/** `PATCH /view` data. `inverse_ops` undo this write when sent back with `version`. */
export interface BenchViewPatchResult {
  version: number;
  view: BenchView;
  inverse_ops: BenchViewOp[];
}

/** 409 `conflict` details[0]. */
export interface BenchViewConflictDetail {
  current_version: number;
}

/** 422 `expression_error` details entry; `message` never echoes the expression. */
export interface BenchViewExpressionErrorDetail {
  op_index: number;
  code: string;
  position: number;
  length: number;
  message: string;
}

export const BENCH_VIEW_LIMITS = {
  maxDisplay: 512,
  maxDerived: 32,
  maxOps: 32,
  maxInverseOps: 64,
  maxOrder: 1023,
  maxUnitChars: 32,
  maxGroupChars: 64,
  maxNameChars: 64,
  maxGroups: 16,
  maxGroupMembers: 8,
  maxRefs: 8,
  maxLimitMagnitude: 1e12,
} as const;

export const EMPTY_BENCH_VIEW: BenchView = Object.freeze({
  version: 0,
  display: [],
  derived: [],
  updated_at: null,
}) as BenchView;

/** A stable map key for a target (unambiguous even when device ids contain "/"). */
export function benchTargetKey(target: BenchViewTarget): string {
  return target.kind === "signal"
    ? JSON.stringify(["signal", target.device_id, target.signal])
    : JSON.stringify(["derived", target.id]);
}

// ── Runtime guards: responses are untrusted input until narrowed. ─────────────

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isStr = (value: unknown, max = 4096): value is string =>
  typeof value === "string" && value.length <= max;
const isNullableStr = (value: unknown, max: number): boolean =>
  value === null || isStr(value, max);
const isInt = (value: unknown, min: number, max: number): boolean =>
  Number.isInteger(value) &&
  (value as number) >= min &&
  (value as number) <= max;
const isList = (value: unknown, max: number): value is unknown[] =>
  Array.isArray(value) && value.length <= max;

function isTarget(value: unknown): value is BenchViewTarget {
  if (!isRec(value)) return false;
  if (value.kind === "derived") return isStr(value.id, 64);
  return (
    value.kind === "signal" &&
    isStr(value.device_id, 512) &&
    isStr(value.signal, 128)
  );
}

function isLimits(value: unknown): boolean {
  if (value === null) return true;
  if (!isRec(value)) return false;
  const { min, max } = value;
  const bound = BENCH_VIEW_LIMITS.maxLimitMagnitude;
  return (
    typeof min === "number" &&
    typeof max === "number" &&
    Number.isFinite(min) &&
    Number.isFinite(max) &&
    min < max &&
    Math.abs(min) <= bound &&
    Math.abs(max) <= bound
  );
}

function isDisplayEntry(value: unknown): boolean {
  if (!isRec(value)) return false;
  return (
    isTarget(value.target) &&
    typeof value.pinned === "boolean" &&
    typeof value.hidden === "boolean" &&
    (value.order === null ||
      isInt(value.order, 0, BENCH_VIEW_LIMITS.maxOrder)) &&
    isNullableStr(value.unit, BENCH_VIEW_LIMITS.maxUnitChars) &&
    isLimits(value.limits) &&
    isNullableStr(value.plot_group, BENCH_VIEW_LIMITS.maxGroupChars)
  );
}

const isRef = (value: unknown): boolean =>
  isRec(value) && isStr(value.device_id, 512) && isStr(value.signal, 128);

function isDerived(value: unknown): boolean {
  if (!isRec(value)) return false;
  return (
    isStr(value.id, 64) &&
    isStr(value.name, BENCH_VIEW_LIMITS.maxNameChars) &&
    isStr(value.expression, 512) &&
    isNullableStr(value.unit, BENCH_VIEW_LIMITS.maxUnitChars) &&
    isInt(value.node_count, 0, 64) &&
    isList(value.refs, BENCH_VIEW_LIMITS.maxRefs) &&
    value.refs.every(isRef) &&
    isStr(value.created_at, 64) &&
    isStr(value.updated_at, 64)
  );
}

export function isBenchView(value: unknown): value is BenchView {
  if (!isRec(value)) return false;
  return (
    isInt(value.version, 0, Number.MAX_SAFE_INTEGER) &&
    isList(value.display, BENCH_VIEW_LIMITS.maxDisplay) &&
    value.display.every(isDisplayEntry) &&
    isList(value.derived, BENCH_VIEW_LIMITS.maxDerived) &&
    value.derived.every(isDerived) &&
    isNullableStr(value.updated_at, 64)
  );
}

const PATCH_FIELDS = [
  "pinned",
  "hidden",
  "order",
  "unit",
  "limits",
  "plot_group",
];

function isPatch(value: unknown): boolean {
  if (!isRec(value)) return false;
  const keys = Object.keys(value);
  return keys.length > 0 && keys.every((key) => PATCH_FIELDS.includes(key));
}

export function isBenchViewOp(value: unknown): value is BenchViewOp {
  if (!isRec(value)) return false;
  switch (value.kind) {
    case "set_display":
      return isTarget(value.target) && isPatch(value.patch);
    case "upsert_derived":
      return (
        isStr(value.name, BENCH_VIEW_LIMITS.maxNameChars) &&
        isStr(value.expression, 512)
      );
    case "delete_derived":
      return isStr(value.id, 64);
    default:
      return false;
  }
}
