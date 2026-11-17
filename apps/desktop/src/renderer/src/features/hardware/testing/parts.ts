// Robots, parts and the machine node as the typed client returns them (docs/api/hardware.md).
import type { HardwarePartRow } from '../../../lib/api/hardware'
import type { Entity } from '../../../lib/api/resources'

type Over = Record<string, unknown>
const TOP = ['origin', 'type', 'created_at', 'parent_id'] as const

function entity(id: string, name: string, type: string, over: Over): Entity {
  const properties = Object.fromEntries(
    Object.entries(over).filter(([key]) => !(TOP as readonly string[]).includes(key))
  )
  return {
    id,
    name,
    type: typeof over.type === 'string' ? over.type : type,
    domain: 'project',
    source_key: null,
    origin: typeof over.origin === 'string' ? over.origin : 'manual',
    created_at: typeof over.created_at === 'string' ? over.created_at : '2026-11-01T00:00:00Z',
    properties
  }
}

export const robot = (id: string, name: string, over: Over = {}): Entity =>
  entity(id, name, 'physical_robot', over)

export const part = (id: string, name: string, over: Over = {}): HardwarePartRow => ({
  ...entity(id, name, 'part', over),
  parent_id: typeof over.parent_id === 'string' ? over.parent_id : null
})

export const machine = (devices: readonly Over[]): Entity =>
  entity('m1', 'This computer', 'machine', { devices })
