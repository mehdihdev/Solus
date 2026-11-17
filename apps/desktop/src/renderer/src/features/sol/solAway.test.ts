// Who is watching the SOL thread: the SOL page, or the SOL sidebar open on the current screen.
import { beforeEach, describe, expect, it } from 'vitest'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useShellStore, type MainScreen } from '../workspace/shellStore'
import { useSolSidebarStore } from './sidebar/solSidebarStore'
import { userIsWatching } from './solAway'

function on(screen: MainScreen, sidebarOpen: boolean): boolean {
  useShellStore.setState({ lastMain: screen })
  useSolSidebarStore.getState().setOpen(sidebarOpen)
  return userIsWatching('p1')
}

beforeEach(() => {
  useSolSidebarStore.getState().reset()
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
})

describe('userIsWatching', () => {
  it('is true on the SOL page, whatever the sidebar’s flag says', () => {
    expect(on('sol', false)).toBe(true)
  })

  it('is true with the sidebar open on the current screen', () => {
    expect(on('hardware', true)).toBe(true)
    expect(on('home', true)).toBe(true)
  })

  it('is false on Hardware with the sidebar closed', () => {
    expect(on('hardware', false)).toBe(false)
  })

  it('is false for another project’s thread', () => {
    useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } })
    expect(on('sol', true)).toBe(false)
  })
})
