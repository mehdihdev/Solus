// SOLUSDEV-327 — `sol.sidebar_toggled` (sol-sidebar.md §7): enums only, consent-gated server-side.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reportSidebarToggled } from './sidebarEvents'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import * as ext from '../../../lib/api/resources.extensions'

const bypass = vi.hoisted(() => ({ active: false }))
vi.mock('../../../lib/supabase', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/supabase')>()),
  get devBypassActive() {
    return bypass.active
  }
}))
vi.mock('../../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  postDataEvents: vi.fn(async () => undefined)
}))

beforeEach(() => {
  vi.clearAllMocks()
  bypass.active = false
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.dev' } as never })
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover', teamId: 't1' } })
})

describe('reportSidebarToggled', () => {
  it('posts the action, screen and trigger', () => {
    reportSidebarToggled('open', 'workspace', 'shortcut')
    expect(ext.postDataEvents).toHaveBeenCalledWith([
      {
        event_type: 'sol.sidebar_toggled',
        project_id: 'p1',
        payload: { action: 'open', screen: 'workspace', via: 'shortcut' }
      }
    ])
  })

  it('omits the project id when no project is open', () => {
    useWorkspaceStore.setState({ project: null })
    reportSidebarToggled('close', 'home', 'button')
    expect(ext.postDataEvents).toHaveBeenCalledWith([
      {
        event_type: 'sol.sidebar_toggled',
        payload: { action: 'close', screen: 'home', via: 'button' }
      }
    ])
  })

  it('posts nothing when signed out or in dev bypass', () => {
    useAuthStore.setState({ status: 'unauthenticated' } as never)
    reportSidebarToggled('open', 'home', 'button')
    useAuthStore.setState({ status: 'authenticated' })
    bypass.active = true
    reportSidebarToggled('open', 'home', 'button')
    expect(ext.postDataEvents).not.toHaveBeenCalled()
  })

  it('swallows a failed post', async () => {
    vi.mocked(ext.postDataEvents).mockRejectedValueOnce(new Error('offline'))
    expect(() => reportSidebarToggled('expand', 'bench', 'header')).not.toThrow()
    await Promise.resolve()
  })
})
