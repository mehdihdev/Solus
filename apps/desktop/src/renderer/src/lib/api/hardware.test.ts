import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import type { Entity } from './resources'
import {
  ROBOT_CATEGORY_LABELS,
  acceptHardwareSuggestion,
  clearDeviceDismissals,
  getHardwareConfig,
  getEntityHardwareConfig,
  putEntityHardwareConfig,
  listDetectedDevices,
  listExpectedParts,
  listHardwareParts,
  listHardwareSuggestions,
  rejectHardwareSuggestion,
  setInGraph,
  type HardwareConfig,
  type HardwareSuggestion
} from './hardware'

const client = (): ApiClient => ({ request: vi.fn(), requestPage: vi.fn() })
const config: HardwareConfig = { schema_version: 1, robot_entity_id: 'r1' }
const part: Entity = {
  id: 'part-1',
  project_id: 'p1',
  name: 'Pressure sensor',
  type: 'part',
  domain: 'project',
  source_key: '',
  origin: 'manual'
}
const suggestion: HardwareSuggestion = {
  id: 'sg1',
  subject_ref: 'usb:5B42134331',
  subject_kind: 'device',
  candidate_robot_id: 'r1',
  confidence: 0.9,
  tier: 'high',
  evidence: [],
  reason: null,
  status: 'pending',
  created_at: '',
  decided_at: null
}

describe('hardware API client', () => {
  registerHardwareConfigurationTests()

  registerSuggestionsAndDetectionTests()
})

function registerHardwareConfigurationTests(): void {
  it('keeps absent v2 configs nullable and sends the exact expected version', async () => {
    const api = client()
    const absent = { entry_id: null, entity_id: 'r1', version: 0, config: null }
    vi.mocked(api.request).mockResolvedValue(absent)
    expect(await getEntityHardwareConfig('p1', 'r1', api)).toEqual(absent)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/entities/r1/config')
    const document = { schema_version: 2 as const, entity_id: 'r1', provenance: {} }
    await putEntityHardwareConfig('p1', 'r1', document, 0, api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/entities/r1/config', {
      method: 'PUT',
      body: { config: document },
      ifMatch: 0
    })
  })
  it('reads the robot config through the documented route', async () => {
    const api = client()
    const out = { entry_id: 'e1', robot_entity_id: 'r1', config }
    vi.mocked(api.request).mockResolvedValue(out)
    expect(await getHardwareConfig('p1', 'r1', api)).toEqual(out)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/robots/r1/config')
  })
}

function registerSuggestionsAndDetectionTests(): void {
  it('lists suggestions by status, defaulting to pending', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue([suggestion])
    expect(await listHardwareSuggestions('p1', undefined, api)).toEqual([suggestion])
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/suggestions?status=pending')
    await listHardwareSuggestions('p1', 'rejected', api)
    expect(api.request).toHaveBeenLastCalledWith(
      '/projects/p1/hardware/suggestions?status=rejected'
    )
  })

  it('accepts and rejects a suggestion, sending the optional reason as null when absent', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue({ ...suggestion, status: 'accepted' })
    await acceptHardwareSuggestion('p1', 'sg1', api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/suggestions/sg1/accept', {
      method: 'POST'
    })
    await rejectHardwareSuggestion('p1', 'sg1', undefined, api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/suggestions/sg1/reject', {
      method: 'POST',
      body: { reason: null }
    })
    await rejectHardwareSuggestion('p1', 'sg1', 'wrong arm', api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/suggestions/sg1/reject', {
      method: 'POST',
      body: { reason: 'wrong arm' }
    })
  })

  it('labels the seven library categories', () => {
    expect(Object.values(ROBOT_CATEGORY_LABELS)).toEqual([
      'Sensors',
      'Actuators / motors',
      'Controllers',
      'End effectors',
      'Power',
      'Structure',
      'Wiring'
    ])
  })

  it('lists detected devices through the documented route', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue([])
    expect(await listDetectedDevices('p1', api)).toEqual([])
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/detected')
  })
}

describe('the Hardware page reads and its one write (SOLUSDEV-326 P3)', () => {
  it('walks every page of the parts list, with each part’s robot', async () => {
    const c = client()
    vi.mocked(c.requestPage)
      .mockResolvedValueOnce({
        data: [{ ...part, parent_id: 'r1' }],
        meta: { has_next: true, next_cursor: 'c2' }
      })
      .mockResolvedValueOnce({ data: [{ ...part, id: 'part-2', parent_id: null }], meta: {} })
    const rows = await listHardwareParts('p1', c)
    expect(rows.map((row) => [row.id, row.parent_id])).toEqual([
      ['part-1', 'r1'],
      ['part-2', null]
    ])
    expect(vi.mocked(c.requestPage).mock.calls.map(([path]) => path)).toEqual([
      '/projects/p1/hardware/parts?ownership=all&limit=100',
      '/projects/p1/hardware/parts?ownership=all&limit=100&cursor=c2'
    ])
  })

  it('reads what the workspace describes and nothing has answered', async () => {
    const c = client()
    const body = { expected: [], sources: [], more: 0 }
    vi.mocked(c.request).mockResolvedValue(body)
    await expect(listExpectedParts('p1', c)).resolves.toBe(body)
    expect(c.request).toHaveBeenCalledWith('/projects/p1/hardware/expected')
  })

  it('puts hardware in the graph with a decision-only body', async () => {
    const c = client()
    vi.mocked(c.request).mockResolvedValue({ entity: part, in_graph: true, updated: 1 })
    await setInGraph('p1', 'part-1', true, c)
    expect(c.request).toHaveBeenCalledWith('/projects/p1/hardware/entities/part-1/graph', {
      method: 'PUT',
      body: { in_graph: true }
    })
  })

  it('clears the caller’s "Not now" list with a bodiless DELETE', async () => {
    const c = client()
    await clearDeviceDismissals('p1', c)
    expect(c.request).toHaveBeenCalledExactlyOnceWith('/projects/p1/hardware/devices/dismissals', {
      method: 'DELETE'
    })
  })
})
