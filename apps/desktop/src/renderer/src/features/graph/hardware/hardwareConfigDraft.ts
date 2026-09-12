import type { EntityHardwareConfig } from '../../../lib/api/hardware'

const FIELDS = new Set([
  'schema_version',
  'entity_id',
  'component',
  'identity',
  'protocol',
  'bus_map',
  'disambiguated_by',
  'provenance'
])
const PRIVATE = /^(?:\/|[a-z]:[\\/]|\\\\|file:)/iu
const BAD_KEYS = new Set(['__proto__', 'constructor', 'prototype', 'last_seen_path'])
type Json = null | boolean | number | string | Json[] | { [key: string]: Json }

function safe(value: unknown, depth = 0): asserts value is Json {
  if (depth > 12) throw new Error('Configuration is too deeply nested.')
  safeScalar(value)
  if (Array.isArray(value)) value.forEach((item) => safe(item, depth + 1))
  else if (value !== null && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      if (BAD_KEYS.has(key)) throw new Error('This field is not portable hardware configuration.')
      safe(item, depth + 1)
    }
  }
}

function safeScalar(value: unknown): void {
  if (typeof value === 'string' && PRIVATE.test(value))
    throw new Error('Use the local file picker instead of a private path.')
  if (typeof value === 'number' && !Number.isFinite(value))
    throw new Error('Configuration numbers must be finite.')
}

function leaves(value: Json, path = '', result: Record<string, Json> = {}): Record<string, Json> {
  if (value !== null && typeof value === 'object') {
    for (const [key, item] of Object.entries(value))
      leaves(item, path ? `${path}.${key}` : key, result)
  } else if (value !== null) result[path] = value
  return result
}

export function configDraft(config: EntityHardwareConfig): string {
  return JSON.stringify({ ...config, provenance: undefined }, null, 2)
}

/** Local portability/size validation; the API applies the complete Pydantic schema. */
export function prepareHardwareConfig(
  raw: string,
  entityId: string,
  saved: EntityHardwareConfig | null
): EntityHardwareConfig {
  if (new TextEncoder().encode(raw).byteLength > 64 * 1024)
    throw new Error('Configuration exceeds 64 KiB.')
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    throw new Error('Enter a valid JSON configuration.')
  }
  safe(value)
  validateIdentity(value, entityId)
  const old = saved ? leaves(JSON.parse(JSON.stringify(saved)) as Json) : {}
  const provenance = { ...saved?.provenance }
  for (const [path, item] of Object.entries(leaves(value))) {
    if (path === 'schema_version' || path === 'entity_id' || path.startsWith('provenance.'))
      continue
    if (old[path] !== item) provenance[path] = { by: 'user' }
  }
  defaultLifecycle(value, provenance)
  return { ...value, provenance } as EntityHardwareConfig
}

export function hardwareSourceRefs(config: EntityHardwareConfig | null): string[] {
  if (config === null) return []
  return [
    ...new Set(
      Object.values(leaves(JSON.parse(JSON.stringify(config)) as Json)).filter(
        (value): value is string =>
          typeof value === 'string' && /^source:[0-9a-f-]{36}$/iu.test(value)
      )
    )
  ]
}

function validateIdentity(value: Json, entityId: string): asserts value is { [key: string]: Json } {
  if (
    value === null ||
    Array.isArray(value) ||
    typeof value !== 'object' ||
    value.schema_version !== 2 ||
    value.entity_id !== entityId ||
    Object.keys(value).some((key) => !FIELDS.has(key))
  )
    throw new Error('Keep schema version 2 and this configuration’s entity identity.')
}

function defaultLifecycle(
  value: { [key: string]: Json },
  provenance: NonNullable<EntityHardwareConfig['provenance']>
): void {
  if (
    value.component !== null &&
    typeof value.component === 'object' &&
    !Array.isArray(value.component) &&
    value.component.lifecycle === undefined
  ) {
    value.component.lifecycle = 'planned'
    provenance['component.lifecycle'] = { by: 'user' }
  }
}
