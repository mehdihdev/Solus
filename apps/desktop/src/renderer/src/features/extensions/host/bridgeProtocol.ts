// SOLUSDEV-235 / EXT-12 — the bridge wire protocol (docs/architecture/
// extensions-runtime.md §6). Pure: the message shapes, the strict parser for
// what a frame may send, and the CLOSED method → scope table. The table lives
// in host code, not configuration (§6.3): adding a method is an edit here AND
// to the architecture doc in the same MR; adding a scope is a contract change.
import type { PermissionScope } from '@solus/shared-types'

export const BRIDGE_VERSION = 1

/** Every cap §6 names, in one place. */
export const BRIDGE_LIMITS = {
  messageBytes: 64 * 1024,
  idLength: 64,
  methodLength: 64,
  windowMs: 10_000,
  windowRequests: 60,
  inFlight: 8,
  searchQuery: 200,
  searchLimit: 50,
  neighborhoodDepth: 2,
  neighborhoodLimit: 200,
  signalIds: 32,
  subscriptions: 8,
  telemetryEventsPerSecond: 10,
  findingTitle: 120,
  findingBodyBytes: 4 * 1024,
  entityIds: 16,
  promptBytes: 8 * 1024,
  storageKey: 64,
  storageValueBytes: 64 * 1024,
  netBodyBytes: 1024 * 1024,
  readyTimeoutMs: 10_000,
  /** SEC-C1: `ui.openExternal` calls per extension per rolling window. */
  openExternalWindowMs: 60_000,
  openExternalPerWindow: 3,
  /** SEC-M2: structural bounds on `params`, checked BEFORE serialization. */
  paramsDepth: 8,
  paramsKeys: 256,
  paramsNodes: 2048,
  paramsStringBytes: 64 * 1024
} as const

export type BridgeErrorCode =
  | 'unknown_method'
  | 'scope_denied'
  | 'invalid_params'
  | 'rate_limited'
  | 'network_denied'
  | 'blocked'
  | 'storage_quota'
  | 'unavailable'
  | 'internal'

/** The codes that are REFUSALS (§6.4) — each emits `extension.bridge_refused`.
 *  `unavailable` and `internal` are host/transport faults, not refusals. */
export const REFUSAL_CODES: ReadonlySet<BridgeErrorCode> = new Set<BridgeErrorCode>([
  'unknown_method',
  'scope_denied',
  'invalid_params',
  'rate_limited',
  'network_denied',
  'blocked',
  'storage_quota'
])

/** frame → host */
export interface BridgeRequest {
  readonly v: 1
  readonly id: string
  readonly method: string
  readonly params: Readonly<Record<string, unknown>>
}

export interface BridgeError {
  readonly code: BridgeErrorCode
  readonly message: string
}

/** host → frame, exactly one per request id */
export type BridgeResponse =
  | { readonly v: 1; readonly id: string; readonly ok: true; readonly result: unknown }
  | { readonly v: 1; readonly id: string; readonly ok: false; readonly error: BridgeError }

/** host → frame, unsolicited */
export interface BridgeEvent {
  readonly v: 1
  readonly event: string
  readonly data: unknown
}

export type BridgeOutbound = BridgeResponse | BridgeEvent

/** §6.7 — the events the host may send. */
export type BridgeEventName =
  | 'init'
  | 'focus.changed'
  | 'settings.changed'
  | 'theme.changed'
  | 'project.changed'
  | 'telemetry.sample'

/** The §6.2 `init` payload. `projectHandle` (SEC-L2) is a per-mount random
 *  opaque id — a display/cache key for the frame — and never the project's
 *  UUID, which stays host-side. It is not accepted back as scope either way. */
export interface BridgeInitPayload {
  readonly extensionId: string
  readonly version: string
  readonly projectHandle: string
  readonly settings: Readonly<Record<string, boolean | number | string>>
  readonly theme: Readonly<Record<string, string>>
  readonly focus: unknown
  readonly mode: 'widget' | 'page' | 'window' | 'dev'
}

/** Events delivered only to frames holding ANY of the listed scopes (§6.7:
 *  `focus.changed` goes "only to frames with focus.read or graph.read"). */
export const EVENT_SCOPES: Readonly<Partial<Record<BridgeEventName, readonly PermissionScope[]>>> =
  {
    'focus.changed': ['focus.read', 'graph.read'],
    'telemetry.sample': ['telemetry.read']
  }

/**
 * §6.3, verbatim. `null` = no scope required. `net.fetch` is null here because
 * its authorization is not a scope: the target origin must be in the granted
 * `permissions.network`, checked by the handler (`network_denied`).
 * `ui.openExternal` is gated the same way (SEC-C1): granted origin or an exact
 * `store.links` URL, through the one predicate in originAllow.ts.
 */
export const METHOD_SCOPES = {
  'ui.ready': null,
  'settings.get': null,
  'ui.openExternal': null,
  'graph.getFocus': 'graph.read',
  'graph.getEntity': 'graph.read',
  'graph.getNeighborhood': 'graph.read',
  'graph.search': 'graph.read',
  'telemetry.subscribe': 'telemetry.read',
  'telemetry.unsubscribe': 'telemetry.read',
  'sources.list': 'sources.read',
  'findings.create': 'findings.write',
  'sol.ask': 'sol.ask',
  'storage.get': 'storage.own',
  'storage.set': 'storage.own',
  'storage.delete': 'storage.own',
  'focus.get': 'focus.read',
  'focus.propose': 'focus.write',
  'net.fetch': null
} as const satisfies Record<string, PermissionScope | null>

export type BridgeMethod = keyof typeof METHOD_SCOPES

/** Methods the SERVER verifies against an install row (§6.6, §7 of the route
 *  plan). A dev registration has no row, so these are `blocked` in dev mode
 *  (architecture §10, open question 2). */
export const SERVER_ATTRIBUTED_METHODS: ReadonlySet<BridgeMethod> = new Set<BridgeMethod>([
  'sol.ask',
  'findings.create',
  'storage.get',
  'storage.set',
  'storage.delete'
])

export function isKnownMethod(method: string): method is BridgeMethod {
  return Object.prototype.hasOwnProperty.call(METHOD_SCOPES, method)
}

const ID_RE = /^[A-Za-z0-9_-]+$/
const encoder = new TextEncoder()

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** UTF-8 byte length of the serialized message, or null when unserializable. */
function serializedBytes(data: unknown): number | null {
  try {
    return encoder.encode(JSON.stringify(data)).byteLength
  } catch {
    return null
  }
}

/**
 * Strict parse of an inbound `postMessage` payload (§6.1, §6.5). Anything that
 * is not exactly `{ v: 1, id, method, params: object }` within the size cap
 * yields null — the caller DROPS it without a response (a refusal would itself
 * be an oracle). The result is a fresh literal: undeclared keys never ride along.
 */
function isValidRequestId(id: unknown): id is string {
  return typeof id === 'string' && id.length <= BRIDGE_LIMITS.idLength && ID_RE.test(id)
}

function isValidMethodName(method: unknown): method is string {
  return (
    typeof method === 'string' && method.length > 0 && method.length <= BRIDGE_LIMITS.methodLength
  )
}

function withinMessageCap(data: unknown): boolean {
  const bytes = serializedBytes(data)
  return bytes !== null && bytes <= BRIDGE_LIMITS.messageBytes
}

interface Frame {
  readonly value: unknown
  readonly depth: number
}

/** Children of a container plus the text its keys carry (arrays have none). */
function expand(value: object): { children: unknown[]; keyChars: number } {
  if (Array.isArray(value)) return { children: value, keyChars: 0 }
  const entries = Object.entries(value)
  return {
    children: entries.map(([, child]) => child),
    keyChars: entries.reduce((sum, [key]) => sum + key.length, 0)
  }
}

/**
 * SEC-M2: bound `params` structurally — depth, keys per object, total nodes,
 * per-string length, and total text — BEFORE `JSON.stringify` ever sees it, so
 * a hostile frame cannot make the host serialize a megabyte-scale (or cyclic)
 * graph just to learn it is over the 64 KiB cap. Every string is ≥ one byte
 * per UTF-16 unit, so total text over the message cap is over the cap.
 */
function isContainer(value: unknown): value is object {
  return typeof value === 'object' && value !== null
}

function withinBudget(nodes: number, chars: number, value: unknown): boolean {
  if (nodes > BRIDGE_LIMITS.paramsNodes || chars > BRIDGE_LIMITS.messageBytes) return false
  return typeof value !== 'string' || value.length <= BRIDGE_LIMITS.paramsStringBytes
}

function withinStructuralBounds(params: Record<string, unknown>): boolean {
  let nodes = 0
  let chars = 0
  const stack: Frame[] = [{ value: params, depth: 1 }]
  while (stack.length > 0) {
    const { value, depth } = stack.pop() as Frame
    nodes += 1
    if (typeof value === 'string') chars += value.length
    if (!withinBudget(nodes, chars, value)) return false
    if (!isContainer(value)) continue
    if (depth > BRIDGE_LIMITS.paramsDepth) return false
    const { children, keyChars } = expand(value)
    if (children.length > BRIDGE_LIMITS.paramsKeys) return false
    chars += keyChars
    for (const child of children) stack.push({ value: child, depth: depth + 1 })
  }
  return chars <= BRIDGE_LIMITS.messageBytes
}

export function parseBridgeRequest(data: unknown): BridgeRequest | null {
  if (!isPlainRecord(data) || data.v !== BRIDGE_VERSION) return null
  const { id, method, params } = data
  if (!isValidRequestId(id) || !isValidMethodName(method) || !isPlainRecord(params)) return null
  if (!withinStructuralBounds(params) || !withinMessageCap(data)) return null
  return { v: 1, id, method, params }
}
