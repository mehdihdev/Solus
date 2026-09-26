import { describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './client'
import type { Entity } from './resources'
import {
  LIFECYCLE_STATES,
  ROBOT_CATEGORIES,
  ROBOT_CATEGORY_LABELS,
  acceptHardwareSuggestion,
  attachParts,
  confirmDetected,
  createHardwarePart,
  getHardwareConfig,
  getEntityHardwareConfig,
  putEntityHardwareConfig,
  getLibraryDefinition,
  importLibraryPart,
  importLibraryPlatform,
  listDetectedDevices,
  listHardwareSuggestions,
  listUnassignedParts,
  promotePartLifecycle,
  proposeDetected,
  putHardwareConfig,
  rejectHardwareSuggestion,
  searchLibrary,
  type ConfirmIn,
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

  registerDeviceConfirmationAndAssignmentTests()

  registerHardwareLibraryTests()
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
  it('reads and replaces the robot config through the documented routes', async () => {
    const api = client()
    const out = { entry_id: 'e1', robot_entity_id: 'r1', config }
    vi.mocked(api.request).mockResolvedValue(out)
    expect(await getHardwareConfig('p1', 'r1', api)).toEqual(out)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/robots/r1/config')
    expect(await putHardwareConfig('p1', 'r1', config, api)).toEqual(out)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/robots/r1/config', {
      method: 'PUT',
      body: { config }
    })
  })

  it('authors a part with the exact PartIn body', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue({ entity: part, config_entry_id: 'e1' })
    const input = {
      name: 'Pressure sensor',
      category: 'sensors' as const,
      specs: { interface: 'I2C', supply_v: 3.3 },
      lifecycle: 'planned' as const
    }
    expect(await createHardwarePart('p1', 'r1', input, api)).toEqual({
      entity: part,
      config_entry_id: 'e1'
    })
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/robots/r1/parts', {
      method: 'POST',
      body: input
    })
  })

  it('promotes a lifecycle state without touching the part identity', async () => {
    const api = client()
    const out = { part_id: 'part-1', config: { lifecycle: 'ordered' as const } }
    vi.mocked(api.request).mockResolvedValue(out)
    expect(await promotePartLifecycle('p1', 'r1', 'part-1', 'ordered', api)).toEqual(out)
    expect(api.request).toHaveBeenLastCalledWith(
      '/projects/p1/hardware/robots/r1/parts/part-1/lifecycle',
      { method: 'POST', body: { state: 'ordered' } }
    )
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

  it('exposes the seven categories with labels and the five lifecycle states in order', () => {
    expect(ROBOT_CATEGORIES).toEqual([
      'sensors',
      'actuators',
      'controllers',
      'end_effectors',
      'power',
      'structure',
      'wiring'
    ])
    expect(ROBOT_CATEGORIES.map((c) => ROBOT_CATEGORY_LABELS[c])).toEqual([
      'Sensors',
      'Actuators / motors',
      'Controllers',
      'End effectors',
      'Power',
      'Structure',
      'Wiring'
    ])
    expect(LIFECYCLE_STATES).toEqual(['planned', 'ordered', 'received', 'installed', 'live'])
  })

  it('lists detected devices through the documented route', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue([])
    expect(await listDetectedDevices('p1', api)).toEqual([])
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/detected')
  })
}

function registerDeviceConfirmationAndAssignmentTests(): void {
  it('proposes with the device ref URL-encoded and no body unless given', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue({ device_ref: 'usb_serial:5B42', rows: [] })
    await proposeDetected('p1', 'usb_serial:5B42/1', undefined, api)
    expect(api.request).toHaveBeenLastCalledWith(
      '/projects/p1/hardware/detected/usb_serial%3A5B42%2F1/propose',
      { method: 'POST', body: undefined }
    )
    await proposeDetected('p1', 'usb_serial:5B42', { budget_s: 1 }, api)
    expect(api.request).toHaveBeenLastCalledWith(
      '/projects/p1/hardware/detected/usb_serial%3A5B42/propose',
      { method: 'POST', body: { budget_s: 1 } }
    )
  })

  it('confirms with the exact ConfirmIn body', async () => {
    const api = client()
    const body: ConfirmIn = {
      target: { kind: 'existing', robot_id: 'r1' },
      accepted: [{ row_id: 'usb_serial:5B42/1', function_name: 'elbow', category: 'actuators' }],
      start_session: true,
      connection_only: false,
      window_seconds: 1
    }
    const out = {
      robot: part,
      part_ids: ['x'],
      config_entry_id: 'e1',
      session_id: null,
      session_error: null
    }
    vi.mocked(api.request).mockResolvedValue(out)
    expect(await confirmDetected('p1', 'usb_serial:5B42', body, api)).toEqual(out)
    expect(api.request).toHaveBeenLastCalledWith(
      '/projects/p1/hardware/detected/usb_serial%3A5B42/confirm',
      { method: 'POST', body }
    )
  })

  it('pages unassigned parts with the cursor when given', async () => {
    const api = client()
    const page = { data: [part], meta: { has_next: true, next_cursor: 'c2' } }
    vi.mocked(api.requestPage).mockResolvedValue(page)
    expect(await listUnassignedParts('p1', null, api)).toEqual(page)
    expect(api.requestPage).toHaveBeenLastCalledWith('/projects/p1/hardware/unassigned?limit=24')
    await listUnassignedParts('p1', 'c2', api)
    expect(api.requestPage).toHaveBeenLastCalledWith(
      '/projects/p1/hardware/unassigned?limit=24&cursor=c2'
    )
  })

  it('attaches parts under a category with the exact AttachIn body', async () => {
    const api = client()
    const out = { attached: ['part-1'], skipped: [], config_entry_id: 'e1' }
    vi.mocked(api.request).mockResolvedValue(out)
    const input = { entity_ids: ['part-1'], category: 'structure' as const }
    expect(await attachParts('p1', 'r1', input, api)).toEqual(out)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/robots/r1/parts/attach', {
      method: 'POST',
      body: input
    })
  })
}

function registerHardwareLibraryTests(): void {
  it('searches the library with the query and previews one definition by kind', async () => {
    const api = client()
    vi.mocked(api.request).mockResolvedValue([])
    expect(await searchLibrary('p1', '', api)).toEqual([])
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/library?q=')
    await searchLibrary('p1', 'bus servo', api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/library?q=bus+servo')
    await getLibraryDefinition('p1', 'platform', 'demo-arm', api)
    expect(api.request).toHaveBeenLastCalledWith('/projects/p1/hardware/library/platform/demo-arm')
  })

  it('imports a platform with the optional name and a part with the exact body', async () => {
    const api = client()
    const out = { robot: part, part_ids: ['a'], config_entry_id: 'e1', suggestion_ids: [] }
    vi.mocked(api.request).mockResolvedValue(out)
    expect(await importLibraryPlatform('p1', 'demo-arm', undefined, api)).toEqual(out)
    expect(api.request).toHaveBeenLastCalledWith(
      '/projects/p1/hardware/library/platforms/demo-arm/import',
      { method: 'POST', body: { name: null } }
    )
    await importLibraryPlatform('p1', 'demo-arm', 'Left arm', api)
    expect(api.request).toHaveBeenLastCalledWith(
      '/projects/p1/hardware/library/platforms/demo-arm/import',
      { method: 'POST', body: { name: 'Left arm' } }
    )
    const input = { robot_id: 'r1', category: 'actuators' as const }
    await importLibraryPart('p1', 'demo-servo', input, api)
    expect(api.request).toHaveBeenLastCalledWith(
      '/projects/p1/hardware/library/parts/demo-servo/import',
      { method: 'POST', body: input }
    )
  })
}
