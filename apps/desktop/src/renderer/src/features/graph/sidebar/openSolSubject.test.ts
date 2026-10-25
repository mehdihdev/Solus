import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useFocusStore } from '../../workspace/focusStore'
import { openSolSubject } from './openSolSubject'

const openSol = vi.hoisted(() => vi.fn())
vi.mock('../../../lib/desktopBridge', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/desktopBridge')>()),
  getDesktopSolBridge: () => ({ open: openSol })
}))

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
  useFocusStore.getState().reset()
})

describe('openSolSubject', () => {
  it('opens the SOL window only once the subject is focused and ready', async () => {
    const focus = vi.spyOn(useFocusStore.getState(), 'focus').mockImplementation(async (id) => {
      useFocusStore.setState({ focusedEntityId: id, status: 'ready' })
    })
    openSolSubject('e1')
    await vi.waitFor(() => expect(openSol).toHaveBeenCalledOnce())
    expect(focus).toHaveBeenCalledWith('e1')
  })

  it('stays quiet when the focus failed', async () => {
    vi.spyOn(useFocusStore.getState(), 'focus').mockImplementation(async (id) => {
      useFocusStore.setState({ focusedEntityId: id, status: 'error', error: 'missing' })
    })
    openSolSubject('e1')
    await vi.waitFor(() => expect(useFocusStore.getState().status).toBe('error'))
    expect(openSol).not.toHaveBeenCalled()
  })
})
