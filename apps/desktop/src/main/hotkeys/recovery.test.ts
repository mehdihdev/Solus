import { describe, expect, it, vi } from 'vitest'
import { HOTKEY_RECOVERY_POLL_MS, watchHotkeyRecovery, type HotkeyRecoveryDeps } from './recovery'

function harness(over: Partial<HotkeyRecoveryDeps> = {}) {
  let tick: (() => void) | null = null
  const resumes: (() => void)[] = []
  const deps: HotkeyRecoveryDeps = {
    platform: 'darwin',
    isTrusted: vi.fn(() => false),
    hookMissingPermission: vi.fn(() => true),
    restart: vi.fn(),
    refresh: vi.fn(),
    onWake: (cb) => void resumes.push(cb),
    setInterval: vi.fn((cb: () => void) => {
      tick = cb
      return 1
    }),
    clearInterval: vi.fn(),
    ...over
  }
  const handle = watchHotkeyRecovery(deps)
  return { deps, handle, tick: () => tick?.(), wake: () => resumes.forEach((cb) => cb()) }
}

describe('watchHotkeyRecovery', () => {
  it('starts the hook once Accessibility is granted, without an app restart', () => {
    const h = harness()
    h.tick()
    expect(h.deps.restart).not.toHaveBeenCalled()
    vi.mocked(h.deps.isTrusted).mockReturnValue(true)
    h.tick()
    expect(h.deps.restart).toHaveBeenCalledTimes(1)
    expect(h.deps.setInterval).toHaveBeenCalledWith(expect.any(Function), HOTKEY_RECOVERY_POLL_MS)
  })

  it('never restarts a running hook on a poll tick', () => {
    const h = harness({ isTrusted: () => true, hookMissingPermission: () => false })
    h.tick()
    expect(h.deps.restart).not.toHaveBeenCalled()
  })

  it('refreshes the permission status line on every tick', () => {
    const h = harness()
    h.tick()
    h.tick()
    expect(h.deps.refresh).toHaveBeenCalledTimes(2)
  })

  it('restarts the hook on wake, since macOS can disable the event tap during sleep', () => {
    const h = harness({ hookMissingPermission: () => false })
    h.wake()
    expect(h.deps.restart).toHaveBeenCalledTimes(1)
  })

  it('does not poll Accessibility off macOS but still recovers on wake', () => {
    const h = harness({ platform: 'linux' })
    expect(h.deps.setInterval).not.toHaveBeenCalled()
    h.wake()
    expect(h.deps.restart).toHaveBeenCalledTimes(1)
  })

  it('stop clears the poll and ignores later wakes', () => {
    const h = harness()
    h.handle.stop()
    h.wake()
    expect(h.deps.clearInterval).toHaveBeenCalledWith(1)
    expect(h.deps.restart).not.toHaveBeenCalled()
  })
})
