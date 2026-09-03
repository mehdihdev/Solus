// SOLUSDEV-235 / EXT-12 — focus.propose arbitration: host project, descend(), cross-project refusal.
import { describe, it, expect } from 'vitest'
import type { Focus } from '@solus/shared-types'
import { BridgeFault } from '../bridgeErrors'
import { arbitrateFocus } from './focus'

const current: Focus = {
  entity: { projectId: 'p1', entityId: 'motor' },
  domain: 'mechanical',
  label: 'drive_motor',
  path: []
}

describe('arbitrateFocus', () => {
  it('lands directly (empty path) when nothing is focused', () => {
    expect(arbitrateFocus(null, { entityId: 'e', domain: 'code', label: 'L' }, 'p1')).toEqual({
      entity: { projectId: 'p1', entityId: 'e' },
      domain: 'code',
      label: 'L',
      path: []
    })
  })

  it('always stamps the HOST project on the target', () => {
    const next = arbitrateFocus(null, { entityId: 'e', domain: 'code' }, 'host-project')
    expect(next.entity.projectId).toBe('host-project')
  })

  it('records the hop through descend() when a relation is given', () => {
    const next = arbitrateFocus(
      current,
      { entityId: 'driver', domain: 'electrical', relation: 'drives' },
      'p1'
    )
    expect(next.entity).toEqual({ projectId: 'p1', entityId: 'driver' })
    expect(next.path).toEqual([
      {
        entity: { projectId: 'p1', entityId: 'motor' },
        domain: 'mechanical',
        label: 'drive_motor',
        relation: 'drives'
      }
    ])
  })

  it('drops the trail without a relation (landed here directly)', () => {
    const next = arbitrateFocus(current, { entityId: 'driver', domain: 'electrical' }, 'p1')
    expect(next.path).toEqual([])
  })

  it('refuses when the current focus belongs to another project (stale host)', () => {
    const foreign = { ...current, entity: { projectId: 'p2', entityId: 'x' } }
    expect(() =>
      arbitrateFocus(foreign, { entityId: 'e', domain: 'code', relation: 'r' }, 'p1')
    ).toThrow(BridgeFault)
    expect(() => arbitrateFocus(foreign, { entityId: 'e', domain: 'code' }, 'p1')).toThrowError(
      expect.objectContaining({ code: 'invalid_params' })
    )
  })
})
