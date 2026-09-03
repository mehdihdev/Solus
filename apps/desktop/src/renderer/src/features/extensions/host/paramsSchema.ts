// SOLUSDEV-235 / EXT-12 — per-method param validation (extensions-runtime.md
// §6.3 "params (validated)"). Every request's params are untrusted input from
// the frame: unknown keys reject, every string is capped, and ANY project or
// team id is `invalid_params` (§3 — scope comes from the host, never the
// message). Each validator returns a FRESH literal with only the declared keys.
import { DOMAINS, SEVERITIES, type Domain, type Severity } from '@solus/shared-types'
import { BRIDGE_LIMITS, type BridgeMethod } from './bridgeProtocol'

type Params = Readonly<Record<string, unknown>>

export type Empty = Record<never, never>

export type NetMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'

export interface ValidatedParams {
  'ui.ready': Empty
  'settings.get': Empty
  'ui.openExternal': { url: string }
  'graph.getFocus': Empty
  'graph.getEntity': { entityId: string }
  'graph.getNeighborhood': { entityId: string; depth: number; limit: number }
  'graph.search': { q: string; types: readonly string[]; limit: number }
  'telemetry.subscribe': { signalIds: readonly string[] }
  'telemetry.unsubscribe': { subscriptionId: string }
  'sources.list': Empty
  'findings.create': {
    title: string
    body: string
    severity: Severity
    entityIds: readonly string[]
  }
  'sol.ask': { prompt: string; entityIds: readonly string[] }
  'storage.get': { key: string }
  'storage.set': { key: string; value: string }
  'storage.delete': { key: string }
  'focus.get': Empty
  'focus.propose': { entityId: string; domain: Domain; label?: string; relation?: string }
  'net.fetch': {
    url: string
    method: NetMethod
    headers: Readonly<Record<string, string>>
    body?: string
  }
}

/* ---------------- primitive checks ---------------- */

/** "Present but wrong". Distinct from `undefined` ("absent"), so an optional
 *  field that is absent is dropped while one that is malformed rejects. */
const INVALID = Symbol('invalid')
type Checked<T> = T | typeof INVALID
type Field<T> = Checked<T> | undefined

const ID_MAX = 128
const LABEL_MAX = 256
const RELATION_MAX = 64
const URL_MAX = 2048
const HEADER_VALUE_MAX = 4096
const HEADERS_MAX = 32
const SEARCH_TYPES_MAX = 16
const STORAGE_KEY_RE = /^[A-Za-z0-9_.-]{1,64}$/
const SCOPE_KEYS = new Set(['projectId', 'project_id', 'teamId', 'team_id'])
const NET_METHODS: readonly NetMethod[] = ['GET', 'POST', 'PUT', 'DELETE']
/** Headers the extension may not set (§6.5); the transport owns them. */
const FORBIDDEN_HEADERS = new Set(['cookie', 'host', 'origin', 'referer', 'authorization'])
const HEADER_NAME_RE = /^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}$/
const encoder = new TextEncoder()

const utf8Bytes = (s: string): number => encoder.encode(s).byteLength

function str(v: unknown, max: number, min = 1): Checked<string> {
  return typeof v === 'string' && v.length >= min && v.length <= max ? v : INVALID
}

function bytesStr(v: unknown, maxBytes: number, min = 1): Checked<string> {
  return typeof v === 'string' && v.length >= min && utf8Bytes(v) <= maxBytes ? v : INVALID
}

function int(v: unknown, min: number, max: number): Checked<number> {
  return typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max ? v : INVALID
}

function strList(v: unknown, maxItems: number, maxLen: number, min = 0): Checked<string[]> {
  if (!Array.isArray(v) || v.length < min || v.length > maxItems) return INVALID
  const items = v.map((item) => str(item, maxLen))
  return items.every((item): item is string => item !== INVALID) ? items : INVALID
}

function oneOf<T extends string>(v: unknown, set: readonly T[]): Checked<T> {
  return typeof v === 'string' && (set as readonly string[]).includes(v) ? (v as T) : INVALID
}

function storageKey(v: unknown): Checked<string> {
  return typeof v === 'string' && STORAGE_KEY_RE.test(v) ? v : INVALID
}

function httpsUrl(v: unknown): Checked<string> {
  if (typeof v !== 'string' || v.length > URL_MAX) return INVALID
  try {
    return new URL(v).protocol === 'https:' ? v : INVALID
  } catch {
    return INVALID
  }
}

/** Any parseable URL: `net.fetch` reports a non-https scheme as
 *  `network_denied` (§6.4), so the scheme is the handler's call, not a schema one. */
function anyUrl(v: unknown): Checked<string> {
  if (typeof v !== 'string' || v.length > URL_MAX) return INVALID
  try {
    new URL(v)
    return v
  } catch {
    return INVALID
  }
}

function headerEntryOk([name, value]: [string, unknown]): boolean {
  return (
    HEADER_NAME_RE.test(name) &&
    !FORBIDDEN_HEADERS.has(name.toLowerCase()) &&
    typeof value === 'string' &&
    value.length <= HEADER_VALUE_MAX
  )
}

function headerMap(v: unknown): Checked<Record<string, string>> {
  if (typeof v !== 'object' || v === null || Array.isArray(v)) return INVALID
  const entries = Object.entries(v as Record<string, unknown>)
  if (entries.length > HEADERS_MAX || !entries.every(headerEntryOk)) return INVALID
  return Object.fromEntries(entries as [string, string][])
}

/** Optional: absent stays absent; present goes through `check`. */
function opt<T>(v: unknown, check: (v: unknown) => Checked<T>): Field<T> {
  return v === undefined ? undefined : check(v)
}

/** Optional with a default when absent. */
function dflt<T>(v: unknown, check: (v: unknown) => Checked<T>, fallback: T): Checked<T> {
  return v === undefined ? fallback : check(v)
}

/** Unknown keys and any scope key are invalid — before any per-field check. */
function onlyKeys(params: Params, allowed: readonly string[]): boolean {
  return Object.keys(params).every((key) => allowed.includes(key) && !SCOPE_KEYS.has(key))
}

/**
 * Assemble the result: any INVALID field → null; undefined (absent optional)
 * fields are dropped; required fields are `Checked<T>` so absence is INVALID.
 */
function build<T extends object>(fields: { [K in keyof T]: Field<T[K]> }): T | null {
  const out: Partial<T> = {}
  for (const key of Object.keys(fields) as (keyof T)[]) {
    const value = fields[key]
    if (value === INVALID) return null
    if (value !== undefined) out[key] = value as T[typeof key]
  }
  return out as T
}

/* ---------------- per-method validators ---------------- */

type Validator<M extends BridgeMethod> = (p: Params) => ValidatedParams[M] | null

// Annotated structurally (not via `Validator<M>`): TS treats the alias's M as
// invariant, so one shared function could not be assigned to several slots.
const empty = (p: Params): Empty | null => (onlyKeys(p, []) ? {} : null)

const keyOnly = (p: Params): { key: string } | null =>
  onlyKeys(p, ['key']) ? build({ key: storageKey(p.key) }) : null

const VALIDATORS: { [M in BridgeMethod]: Validator<M> } = {
  'ui.ready': empty,
  'settings.get': empty,
  'graph.getFocus': empty,
  'sources.list': empty,
  'focus.get': empty,

  'ui.openExternal': (p) => (onlyKeys(p, ['url']) ? build({ url: httpsUrl(p.url) }) : null),

  'graph.getEntity': (p) =>
    onlyKeys(p, ['entityId']) ? build({ entityId: str(p.entityId, ID_MAX) }) : null,

  'graph.getNeighborhood': (p) =>
    onlyKeys(p, ['entityId', 'depth', 'limit'])
      ? build({
          entityId: str(p.entityId, ID_MAX),
          depth: dflt(p.depth, (v) => int(v, 0, BRIDGE_LIMITS.neighborhoodDepth), 1),
          limit: dflt(
            p.limit,
            (v) => int(v, 1, BRIDGE_LIMITS.neighborhoodLimit),
            BRIDGE_LIMITS.neighborhoodLimit
          )
        })
      : null,

  'graph.search': (p) =>
    onlyKeys(p, ['q', 'types', 'limit'])
      ? build({
          q: str(p.q, BRIDGE_LIMITS.searchQuery),
          types: dflt(p.types, (v) => strList(v, SEARCH_TYPES_MAX, 64), []),
          limit: dflt(
            p.limit,
            (v) => int(v, 1, BRIDGE_LIMITS.searchLimit),
            BRIDGE_LIMITS.searchLimit
          )
        })
      : null,

  'telemetry.subscribe': (p) =>
    onlyKeys(p, ['signalIds'])
      ? build({ signalIds: strList(p.signalIds, BRIDGE_LIMITS.signalIds, ID_MAX, 1) })
      : null,

  'telemetry.unsubscribe': (p) =>
    onlyKeys(p, ['subscriptionId'])
      ? build({ subscriptionId: str(p.subscriptionId, ID_MAX) })
      : null,

  'findings.create': (p) =>
    onlyKeys(p, ['title', 'body', 'severity', 'entityIds'])
      ? build({
          title: str(p.title, BRIDGE_LIMITS.findingTitle),
          body: bytesStr(p.body, BRIDGE_LIMITS.findingBodyBytes),
          severity: oneOf(p.severity, SEVERITIES),
          entityIds: dflt(p.entityIds, (v) => strList(v, BRIDGE_LIMITS.entityIds, ID_MAX), [])
        })
      : null,

  'sol.ask': (p) =>
    onlyKeys(p, ['prompt', 'entityIds'])
      ? build({
          prompt: bytesStr(p.prompt, BRIDGE_LIMITS.promptBytes),
          entityIds: dflt(p.entityIds, (v) => strList(v, BRIDGE_LIMITS.entityIds, ID_MAX), [])
        })
      : null,

  'storage.get': keyOnly,
  'storage.delete': keyOnly,

  'storage.set': (p) =>
    onlyKeys(p, ['key', 'value'])
      ? build({
          key: storageKey(p.key),
          value: bytesStr(p.value, BRIDGE_LIMITS.storageValueBytes, 0)
        })
      : null,

  'focus.propose': (p) =>
    onlyKeys(p, ['entityId', 'domain', 'label', 'relation'])
      ? build({
          entityId: str(p.entityId, ID_MAX),
          domain: oneOf(p.domain, DOMAINS),
          label: opt(p.label, (v) => str(v, LABEL_MAX)),
          relation: opt(p.relation, (v) => str(v, RELATION_MAX))
        })
      : null,

  'net.fetch': (p) =>
    onlyKeys(p, ['url', 'method', 'headers', 'body'])
      ? build({
          url: anyUrl(p.url),
          method: dflt(p.method, (v) => oneOf(v, NET_METHODS), 'GET' as NetMethod),
          headers: dflt(p.headers, headerMap, {}),
          body: opt(p.body, (v) => bytesStr(v, BRIDGE_LIMITS.netBodyBytes, 0))
        })
      : null
}

/**
 * Validate a known method's params. Null = `invalid_params`. The returned
 * object contains only the declared keys, so nothing the frame sent rides
 * through to a handler unexamined.
 */
export function validateParams<M extends BridgeMethod>(
  method: M,
  params: Params
): ValidatedParams[M] | null {
  return VALIDATORS[method](params)
}
