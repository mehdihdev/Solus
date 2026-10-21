import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reportPaletteOpened } from './paletteEvents'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as ext from '../../lib/api/resources.extensions'

const bypass = vi.hoisted(() => ({ active: false }))
vi.mock('../../lib/supabase', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/supabase')>()),
  get devBypassActive() {
    return bypass.active
  }
}))
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  postDataEvents: vi.fn(async () => undefined)
}))

beforeEach(() => {
  vi.clearAllMocks()
  bypass.active = false
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.dev' } as never })
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover', teamId: 't1' } })
})

describe('reportPaletteOpened', () => {
  it('posts kind, rank and query length — never the query or the label', () => {
    reportPaletteOpened('node', 3, 'imu driver')
    expect(ext.postDataEvents).toHaveBeenCalledWith([
      {
        event_type: 'search.palette_opened',
        project_id: 'p1',
        payload: { kind: 'node', rank: 3, query_length: 10 }
      }
    ])
  })

  it('omits the project id when no project is open', () => {
    useWorkspaceStore.setState({ project: null })
    reportPaletteOpened('page', 0, '')
    expect(ext.postDataEvents).toHaveBeenCalledWith([
      { event_type: 'search.palette_opened', payload: { kind: 'page', rank: 0, query_length: 0 } }
    ])
  })

  it('clamps an absurd query length to the schema bound', () => {
    reportPaletteOpened('team', 0, 'x'.repeat(500))
    const [[events]] = vi.mocked(ext.postDataEvents).mock.calls
    expect(events[0].payload).toMatchObject({ query_length: 200 })
  })

  it('stays silent for the dev bypass and signed-out sessions', () => {
    bypass.active = true
    reportPaletteOpened('page', 0, '')
    bypass.active = false
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    reportPaletteOpened('page', 0, '')
    expect(ext.postDataEvents).not.toHaveBeenCalled()
  })

  it('swallows a failed post', async () => {
    vi.mocked(ext.postDataEvents).mockRejectedValueOnce(new Error('offline'))
    expect(() => reportPaletteOpened('page', 0, '')).not.toThrow()
    await Promise.resolve()
  })
})
