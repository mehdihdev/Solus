import { expect, it } from 'vitest'
import type { EntityHardwareConfig } from '../../../lib/api/hardware'
import { configDraft, hardwareSourceRefs, prepareHardwareConfig } from './hardwareConfigDraft'

const base: EntityHardwareConfig = {
  schema_version: 2,
  entity_id: 'owner',
  component: { lifecycle: 'planned' },
  provenance: { 'component.lifecycle': { by: 'repo', source: 'repo:fixture' } }
}

it.each([
  '{',
  'null',
  '[]',
  JSON.stringify({ ...base, entity_id: 'foreign' }),
  JSON.stringify({ ...base, schema_version: 1 }),
  JSON.stringify({ ...base, unexpected: true }),
  '{"schema_version":2,"entity_id":"owner","component":{"mass_kg":1e999}}',
  '{"schema_version":2,"entity_id":"owner","component":{"__proto__":{}}}',
  JSON.stringify({ ...base, identity: { model: '/private/file.json' } }),
  JSON.stringify({ ...base, identity: { model: 'C:\\private\\file.json' } }),
  JSON.stringify({ ...base, identity: { model: 'file:///private/file.json' } }),
  JSON.stringify({ ...base, identity: { model: 'x'.repeat(65536) } })
])('refuses invalid, nonportable or oversized drafts', (raw) => {
  expect(() => prepareHardwareConfig(raw, 'owner', base)).toThrow()
})

it('preserves unchanged evidence and attributes changed values to the user', () => {
  const unchanged = prepareHardwareConfig(configDraft(base), 'owner', base)
  expect(unchanged.provenance).toEqual(base.provenance)
  const changed = prepareHardwareConfig(
    JSON.stringify({ ...base, component: { lifecycle: 'installed' } }),
    'owner',
    base
  )
  expect(changed.provenance?.['component.lifecycle']).toEqual({ by: 'user' })
  expect(base.component?.lifecycle).toBe('planned')
})

it('attributes the default lifecycle and disregards caller-authored provenance', () => {
  const created = prepareHardwareConfig(
    JSON.stringify({ ...base, component: {}, provenance: { fake: { by: 'repo' } } }),
    'owner',
    null
  )
  expect(created.component?.lifecycle).toBe('planned')
  expect(created.provenance).toEqual({ 'component.lifecycle': { by: 'user' } })
})

it('collects only opaque shared references and omits provenance from the editor', () => {
  const ref = 'source:00000000-0000-4000-8000-000000000001'
  const config = { ...base, provenance: { component: { by: 'repo' as const, source: ref } } }
  expect(hardwareSourceRefs(config)).toEqual([ref])
  expect(hardwareSourceRefs(null)).toEqual([])
  expect(configDraft(config)).not.toContain('provenance')
})
