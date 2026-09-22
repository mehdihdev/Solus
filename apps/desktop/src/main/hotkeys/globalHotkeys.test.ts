import { describe, expect, it, vi } from 'vitest'
import { ACCELERATORS, enableShortcutPortal, registerGlobalHotkeys } from './globalHotkeys'

function fakeShortcuts(taken: string[] = []): {
  api: {
    register: ReturnType<typeof vi.fn>
    unregister: ReturnType<typeof vi.fn>
    unregisterAll: ReturnType<typeof vi.fn>
  }
  registered(): string[]
  fire(acc: string): void
} {
  const cbs = new Map<string, () => void>()
  const api = {
    register: vi.fn((acc: string, cb: () => void) => {
      if (taken.includes(acc)) return false
      cbs.set(acc, cb)
      return true
    }),
    unregister: vi.fn(),
    unregisterAll: vi.fn(() => cbs.clear())
  }
  return { api, registered: () => [...cbs.keys()], fire: (acc) => cbs.get(acc)?.() }
}

const handlers = (): {
  onToggleMode: ReturnType<typeof vi.fn>
  onSummon: ReturnType<typeof vi.fn>
  onCircleMode: ReturnType<typeof vi.fn>
} => ({
  onToggleMode: vi.fn(),
  onSummon: vi.fn(),
  onCircleMode: vi.fn()
})

describe('registerGlobalHotkeys (docs/architecture/sol-window.md §2-§3)', () => {
  registerShortcutRegistrationTests()
  registerShortcutFailureFallbacksTests()
})

it('enables the Wayland portal without replacing other Chromium features', () => {
  const commandLine = { getSwitchValue: vi.fn(() => 'ExistingFeature'), appendSwitch: vi.fn() }
  enableShortcutPortal(commandLine, { platform: 'linux', arch: 'arm64', session: 'wayland' })
  expect(commandLine.appendSwitch).toHaveBeenCalledWith(
    'enable-features',
    'ExistingFeature,GlobalShortcutsPortal'
  )
  commandLine.appendSwitch.mockClear()
  enableShortcutPortal(commandLine, { platform: 'darwin', arch: 'arm64', session: 'macos' })
  expect(commandLine.appendSwitch).not.toHaveBeenCalled()
})

function registerShortcutRegistrationTests(): void {
  it('registers the portable summon chord even with a working native hook', () => {
    const s = fakeShortcuts()
    const h = handlers()
    const reg = registerGlobalHotkeys(s.api, { available: true, hookAvailable: true, ...h })
    expect(ACCELERATORS.summonFallback).toBe('CommandOrControl+Shift+Space')
    expect(s.registered()).toEqual([
      ACCELERATORS.toggleMode,
      ACCELERATORS.summonFallback,
      ACCELERATORS.circleMode
    ])
    expect(reg.shortcuts).toEqual({ ctrlSpace: true, spawnFallback: true, circleMode: true })
    expect(reg.messages).toEqual([])
    s.fire(ACCELERATORS.summonFallback)
    expect(h.onSummon).toHaveBeenCalledTimes(1)
    s.fire(ACCELERATORS.toggleMode)
    s.fire(ACCELERATORS.circleMode)
    expect(h.onToggleMode).toHaveBeenCalledTimes(1)
    expect(h.onCircleMode).toHaveBeenCalledTimes(1)
    reg.stop()
    expect(s.api.unregister.mock.calls.map((c) => c[0])).toEqual([
      ACCELERATORS.toggleMode,
      ACCELERATORS.summonFallback,
      ACCELERATORS.circleMode
    ])
    expect(s.api.unregisterAll).not.toHaveBeenCalled()
  })

  it('hook unavailable: adds the Ctrl+Shift+Space spawn fallback', () => {
    const s = fakeShortcuts()
    const h = handlers()
    const reg = registerGlobalHotkeys(s.api, { available: true, hookAvailable: false, ...h })
    expect(reg.shortcuts).toEqual({ ctrlSpace: true, spawnFallback: true, circleMode: true })
    s.fire(ACCELERATORS.summonFallback)
    expect(h.onSummon).toHaveBeenCalledTimes(1)
  })

  it('a false from register() is a message, not a throw', () => {
    const s = fakeShortcuts([ACCELERATORS.toggleMode])
    const reg = registerGlobalHotkeys(s.api, {
      available: true,
      hookAvailable: true,
      ...handlers()
    })
    expect(reg.shortcuts.ctrlSpace).toBe(false)
    expect(reg.messages).toEqual(['Ctrl+Space is unavailable; use Open SOL window'])
    reg.stop() // never touches a chord another app owns
    expect(s.api.unregister.mock.calls.map((c) => c[0])).toEqual([
      ACCELERATORS.summonFallback,
      ACCELERATORS.circleMode
    ])
  })
}

function registerShortcutFailureFallbacksTests(): void {
  it('a register() that throws is also a message', () => {
    const s = fakeShortcuts()
    s.api.register.mockImplementation(() => {
      throw new Error('boom')
    })
    const reg = registerGlobalHotkeys(s.api, {
      available: true,
      hookAvailable: false,
      ...handlers()
    })
    expect(reg.shortcuts).toEqual({ ctrlSpace: false, spawnFallback: false, circleMode: false })
    expect(reg.messages).toHaveLength(3)
  })

  it('Wayland: registers nothing', () => {
    const s = fakeShortcuts()
    const reg = registerGlobalHotkeys(s.api, {
      available: false,
      hookAvailable: false,
      ...handlers()
    })
    expect(s.api.register).not.toHaveBeenCalled()
    expect(reg.shortcuts).toEqual({ ctrlSpace: false, spawnFallback: false, circleMode: false })
    reg.stop()
    expect(s.api.unregister).not.toHaveBeenCalled()
    expect(s.api.unregisterAll).not.toHaveBeenCalled()
  })
}
