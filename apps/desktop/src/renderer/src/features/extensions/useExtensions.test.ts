// SOLUSDEV-235 — catalog × install state × connected sources → views.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useExtensions } from './useExtensions'
import { useExtensionsStore } from './extensionsStore'
import * as sourcesHook from '../project/useProjectSources'
import type { Source } from '../../lib/api/resources'

vi.mock('../project/useProjectSources', () => ({ useProjectSources: vi.fn() }))

function source(type: string): Source {
  return {
    id: `s-${type}`,
    project_id: 'p1',
    type,
    name: type,
    status: 'connected',
    config: {},
    account_login: null,
    last_synced_at: null,
    last_error: null,
    created_at: '',
    updated_at: ''
  } as Source
}

function mockSources(status: sourcesHook.ProjectSourcesStatus, sources: Source[]): void {
  vi.mocked(sourcesHook.useProjectSources).mockReturnValue({
    status,
    sources,
    actions: { refresh: vi.fn(), syncNow: vi.fn(), disconnect: vi.fn() }
  })
}

beforeEach(() => {
  useExtensionsStore.getState().reset()
  mockSources('ready', [])
})

describe('useExtensions', () => {
  it('returns one view per catalog entry, bundled ones installed', () => {
    const { result } = renderHook(() => useExtensions('p1'))
    const byId = new Map(result.current.views.map((v) => [v.manifest.id, v]))
    expect(byId.get('experiments')?.availability).toBe('installed')
    expect(byId.get('bom')?.availability).toBe('needs_source')
    expect(byId.get('bom')?.missing).toEqual([['eda']])
  })

  it('unblocks an extension once a satisfying source is connected', () => {
    mockSources('ready', [source('kicad')])
    const { result } = renderHook(() => useExtensions('p1'))
    const bom = result.current.views.find((v) => v.manifest.id === 'bom')
    expect(bom?.availability).toBe('available')
  })

  it('passes the sources status through so the screen can explain an offline gap', () => {
    mockSources('offline', [])
    const { result } = renderHook(() => useExtensions('p1'))
    expect(result.current.sourcesStatus).toBe('offline')
  })

  it('actions write to the store for this project and ignore unknown ids', () => {
    const { result } = renderHook(() => useExtensions('p1'))
    act(() => {
      result.current.actions.install('bom')
      result.current.actions.setRunFrequency('bom', 'daily')
      result.current.actions.setEnabled('experiments', false)
      result.current.actions.uninstall('scene')
      result.current.actions.install('not-a-real-extension')
    })
    const byId = new Map(result.current.views.map((v) => [v.manifest.id, v]))
    expect(byId.get('bom')?.state).toEqual({
      installed: true,
      enabled: true,
      runFrequency: 'daily'
    })
    expect(byId.get('experiments')?.state.enabled).toBe(false)
    expect(byId.get('scene')?.state.installed).toBe(false)
    expect(useExtensionsStore.getState().byProject.p1['not-a-real-extension']).toBeUndefined()
  })
})
