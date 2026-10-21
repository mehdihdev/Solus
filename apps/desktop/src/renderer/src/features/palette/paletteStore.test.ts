import { beforeEach, describe, expect, it } from 'vitest'
import { usePaletteStore } from './paletteStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'

beforeEach(() => {
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.dev' } as never })
  useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover', teamId: 't1' } })
  usePaletteStore.getState().reset()
})

describe('usePaletteStore', () => {
  it('opens, closes and toggles', () => {
    const s = usePaletteStore.getState()
    s.setOpen(true)
    expect(usePaletteStore.getState().open).toBe(true)
    usePaletteStore.getState().toggle()
    expect(usePaletteStore.getState().open).toBe(false)
  })

  it('keeps recents most-recent-first, de-duplicated and capped', () => {
    const { remember } = usePaletteStore.getState()
    for (const key of ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'b']) remember(key)
    expect(usePaletteStore.getState().recentKeys).toEqual(['b', 'i', 'h', 'g', 'f', 'e', 'd', 'c'])
  })

  it('issues numbered graph-jump requests and consumes only the matching one', () => {
    const { requestJump } = usePaletteStore.getState()
    requestJump('p1', 'e1')
    requestJump('p1', 'e2')
    const { jump } = usePaletteStore.getState()
    expect(jump).toMatchObject({ projectId: 'p1', entityId: 'e2', sequence: 2 })
    usePaletteStore.getState().consumeJump(1)
    expect(usePaletteStore.getState().jump).not.toBeNull()
    usePaletteStore.getState().consumeJump(2)
    expect(usePaletteStore.getState().jump).toBeNull()
  })

  it('drops node recents and a pending jump when the open project changes', () => {
    const s = usePaletteStore.getState()
    s.remember('page:home')
    s.remember('node:p1:e1')
    s.requestJump('p1', 'e1')
    useWorkspaceStore.setState({ project: { id: 'p2', name: 'Car', teamId: 't1' } })
    expect(usePaletteStore.getState().recentKeys).toEqual(['page:home'])
    expect(usePaletteStore.getState().jump).toBeNull()
  })

  it('forgets everything when the signed-in user changes', () => {
    const s = usePaletteStore.getState()
    s.remember('project:p1')
    s.setOpen(true)
    useAuthStore.setState({ status: 'unauthenticated', user: null })
    expect(usePaletteStore.getState()).toMatchObject({ open: false, recentKeys: [], jump: null })
  })
})
