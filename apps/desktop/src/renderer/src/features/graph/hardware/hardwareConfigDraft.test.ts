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

// SOLUSDEV-326: a stored config lists its brains; the single-identity shape is gone.
it.each([
  JSON.stringify({ ...base, protocol: { driver_id: 'left', params: {} } }),
  JSON.stringify({ ...base, identity: { kind: 'usb_serial', binding: 'AAA' } })
])('refuses the single-identity shape a config no longer has', (raw) => {
  expect(() => prepareHardwareConfig(raw, 'owner', base)).toThrow()
})

it('accepts several brains and attributes a changed brain field to the user', () => {
  const brains: EntityHardwareConfig = {
    ...base,
    identity: [
      {
        kind: 'mcu',
        binding: { kind: 'usb_serial', binding: 'AAA' },
        protocol: { driver_id: 'left', params: {} }
      },
      {
        kind: 'mcu',
        binding: { kind: 'usb_serial', binding: 'BBB' },
        via: 'usb:AAA',
        protocol: { driver_id: 'right', params: {} }
      }
    ],
    bus_map: [{ protocol: 'right', address: '1', brain: 'usb:BBB' }],
    provenance: { ...base.provenance, identity: { by: 'detected' }, bus_map: { by: 'detected' } }
  }
  const draft = JSON.parse(configDraft(brains)) as EntityHardwareConfig
  draft.identity![1].protocol!.driver_id = 'other'
  const saved = prepareHardwareConfig(JSON.stringify(draft), 'owner', brains)
  expect(saved.identity).toHaveLength(2)
  expect(saved.provenance?.['identity.1.protocol.driver_id']).toEqual({ by: 'user' })
  expect(saved.provenance?.['identity.0.binding.binding']).toBeUndefined()
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
