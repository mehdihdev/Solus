import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { getDesktopSolBridge } from '../../lib/desktopBridge'
import { useSolWindowStore } from '../sol/solWindowStore'
import { SOL_STATE } from '../sol/solWindow.fixtures'
import { useNativeGuideHandoff } from './useNativeGuideHandoff'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { GuideDetail } from './guideApi'
vi.mock('../../lib/desktopBridge', () => ({
  getDesktopSolBridge: vi.fn(),
  getDesktopCompanionBridge: () => null
}))
const target = {
  tool: 'kicad' as const,
  windowTitle: 'Board',
  displayId: '1',
  bounds: { x: 0, y: 0, width: 800, height: 600 }
}
const guide: GuideDetail = {
  id: 'wire',
  tool: 'kicad',
  title: 'Wire',
  summary: '',
  steps: [
    {
      step_number: 1,
      control_id: 'wire',
      entry_id: null,
      note_guide: 'Draw a wire',
      note_expert: 'Wire',
      available: false,
      tentative: true,
      stale: false,
      label: null,
      description: null,
      shortcut: null,
      menu_path: null,
      surface: 'toolbar',
      confidence: null,
      locator: { x: 0.1, y: 0.1, w: 0.2, h: 0.2 }
    }
  ]
}
const send = vi.fn()
const lookup = vi.fn()
beforeEach(() => {
  useSolWindowStore.setState({ state: SOL_STATE })
  vi.mocked(getDesktopSolBridge).mockReturnValue({
    getGuideTarget: lookup
  } as unknown as NonNullable<ReturnType<typeof getDesktopSolBridge>>)
  lookup.mockReset().mockResolvedValue(target)
  send.mockClear()
  Object.defineProperty(window, 'solus', {
    configurable: true,
    value: { orbOverlay: { publishToOverlay: send, onOverlayToOrb: () => vi.fn() } }
  })
})
afterEach(() => {
  Reflect.deleteProperty(window, 'solus')
})
it('requires explicit handoff, suppresses uncertain pointers and dismisses on unmount', async () => {
  const hook = renderHook(() => useNativeGuideHandoff(guide, false))
  expect(lookup).not.toHaveBeenCalled()
  await act(() => hook.result.current.start())
  expect(send).toHaveBeenCalledWith(
    expect.objectContaining({
      type: 'spawn',
      target,
      step: expect.objectContaining({
        instruction: 'Draw a wire',
        control: expect.objectContaining({ locator: null })
      })
    })
  )
  hook.unmount()
  expect(send).toHaveBeenLastCalledWith(
    expect.objectContaining({ type: 'dismiss', reason: 'focus_changed' })
  )
})
it.each(['project', 'mode', 'account'])(
  'rejects a pending lookup after %s A B A changes',
  async (kind) => {
    let finish!: (value: typeof target) => void
    lookup.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve
      })
    )
    const hook = renderHook(() => useNativeGuideHandoff(guide, false))
    let pending!: Promise<void>
    act(() => {
      pending = hook.result.current.start()
    })
    act(() => {
      if (kind === 'mode') {
        useSolWindowStore.setState({ state: { ...SOL_STATE, actionMode: 'do' } })
        useSolWindowStore.setState({ state: SOL_STATE })
      } else if (kind === 'account') {
        useAuthStore.setState({ user: { email: 'other@example.test' } })
        useAuthStore.setState({ user: { email: 'original@example.test' } })
      } else {
        useWorkspaceStore.setState({ project: { id: 'b', name: 'B' } })
        useWorkspaceStore.setState({ project: { id: 'a', name: 'A' } })
      }
    })
    await act(async () => {
      finish(target)
      await pending
    })
    expect(send).not.toHaveBeenCalled()
  }
)
it('keeps the side panel on unsupported platforms', async () => {
  lookup.mockResolvedValue(null)
  const hook = renderHook(() => useNativeGuideHandoff(guide, false))
  await act(() => hook.result.current.start())
  expect(hook.result.current.message).toMatch(/unavailable/)
  expect(send).not.toHaveBeenCalled()
})
