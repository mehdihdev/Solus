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
  readyTimeoutMs: 10_000
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
export function parseBridgeRequest(data: unknown): BridgeRequest | null {
  if (!isPlainRecord(data) || data.v !== BRIDGE_VERSION) return null
  const { id, method, params } = data
  if (typeof id !== 'string' || id.length > BRIDGE_LIMITS.idLength || !ID_RE.test(id)) return null
  if (
    typeof method !== 'string' ||
    method.length === 0 ||
    method.length > BRIDGE_LIMITS.methodLength
  )
    return null
  if (!isPlainRecord(params)) return null
  const bytes = serializedBytes(data)
  if (bytes === null || bytes > BRIDGE_LIMITS.messageBytes) return null
  return { v: 1, id, method, params }
}
