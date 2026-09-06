// SOLUSDEV-246 / STORE ST3 — the in-context suggestion fires once, only on a
// genuinely new source kind, lands on the Store detail, and is recorded.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import * as ext from '../../lib/api/resources.extensions'
import type { Source } from '../../lib/api/resources'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useShellStore } from '../workspace/shellStore'
import { catalogItem } from './testing/fixtures'
import { useSourceSuggestions } from './useSourceSuggestions'

vi.mock('../../lib/supabase', () => ({ devBypassActive: false }))
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  postDataEvents: vi.fn(async () => undefined)
}))

const source = (type: string): Source => ({ id: type, type }) as Source
const catalog = { data: [catalogItem({ slug: 'bom', name: 'BOM', requires: [['eda']] })], meta: {} }
const noInstalls = { data: [], meta: {} }
const deps = {
  loadCatalog: vi.fn(async () => catalog as never),
  loadInstalls: vi.fn(async () => noInstalls as never)
}

beforeEach(() => {
  vi.clearAllMocks()
  useShellStore.getState().reset()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
  useAuthStore.setState({ status: 'authenticated' })
})

describe('useSourceSuggestions', () => {
  it('toasts the unlocked widget when a new source kind connects, and records it', async () => {
    const { rerender } = renderHook(
      ({ sources }: { sources: Source[] }) => useSourceSuggestions('p1', sources, 'ready', deps),
      { initialProps: { sources: [source('github')] } }
    )
    expect(deps.loadCatalog).not.toHaveBeenCalled()
    rerender({ sources: [source('github'), source('kicad')] })
    await waitFor(() => expect(useShellStore.getState().toast?.title).toBe('BOM is now available'))
    expect(useShellStore.getState().toast).toMatchObject({
      screen: 'store',
      extensionSlug: 'bom',
      action: 'View'
    })
    expect(ext.postDataEvents).toHaveBeenCalledWith([
      {
        event_type: 'store.suggested',
        project_id: 'p1',
        payload: { slug: 'bom', unlocked_by: ['eda'], candidates: 1 }
      }
    ])
  })

  it('treats the first known list as a baseline and a same-kind addition as nothing new', async () => {
    type Status = 'loading' | 'ready'
    const { rerender } = renderHook(
      ({ sources, status }: { sources: Source[]; status: Status }) =>
        useSourceSuggestions('p1', sources, status, deps),
      { initialProps: { sources: [] as Source[], status: 'loading' as Status } }
    )
    rerender({ sources: [source('kicad')], status: 'ready' })
    rerender({ sources: [source('kicad'), source('altium')], status: 'ready' })
    await new Promise((r) => setTimeout(r, 20))
    expect(deps.loadCatalog).not.toHaveBeenCalled()
    expect(useShellStore.getState().toast).toBeNull()
  })

  it('a project switch resets the baseline instead of comparing across projects', async () => {
    const { rerender } = renderHook(
      ({ projectId, sources }: { projectId: string; sources: Source[] }) =>
        useSourceSuggestions(projectId, sources, 'ready', deps),
      { initialProps: { projectId: 'p1', sources: [] as Source[] } }
    )
    rerender({ projectId: 'p2', sources: [source('kicad')] })
    await new Promise((r) => setTimeout(r, 20))
    expect(deps.loadCatalog).not.toHaveBeenCalled()
  })

  it('stays silent when the catalog cannot be read', async () => {
    const failing = { ...deps, loadCatalog: vi.fn(async () => Promise.reject(new Error('down'))) }
    const { rerender } = renderHook(
      ({ sources }: { sources: Source[] }) => useSourceSuggestions('p1', sources, 'ready', failing),
      { initialProps: { sources: [] as Source[] } }
    )
    rerender({ sources: [source('kicad')] })
    await waitFor(() => expect(failing.loadCatalog).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 20))
    expect(useShellStore.getState().toast).toBeNull()
  })
})
