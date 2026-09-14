import { describe, expect, it, vi } from 'vitest'
import { loadKeyHook } from './keyHook'
import type { PlatformBasics } from '../platform/capabilities'

const X11_X64: PlatformBasics = { platform: 'linux', arch: 'x64', session: 'x11' }
const CTRL = 29
const CTRL_RIGHT = 3613

function fakeUiohook(opts: { startThrows?: boolean } = {}): {
  mod: unknown
  emit(event: 'keydown' | 'keyup', keycode: number): void
  stop: ReturnType<typeof vi.fn>
} {
  const listeners = new Map<string, (e: { keycode: number }) => void>()
  const stop = vi.fn()
  const uIOhook = {
    on: (event: string, cb: (e: { keycode: number }) => void) => void listeners.set(event, cb),
    start: () => {
      if (opts.startThrows) throw new Error('X11 record extension missing')
    },
    stop
  }
  return {
    mod: { uIOhook, UiohookKey: { Ctrl: CTRL, CtrlRight: CTRL_RIGHT } },
    emit: (event, keycode) => listeners.get(event)?.({ keycode }),
    stop
  }
}

describe('loadKeyHook (docs/architecture/sol-window.md §5)', () => {
  registerKeyHookEventsAndFailuresTests()
  registerKeyHookPlatformSupportTests()
})

function registerKeyHookEventsAndFailuresTests(): void {
  it('maps uiohook key events to ctrlDown / ctrlUp / otherKeyDown, deduping autorepeat', () => {
    const fake = fakeUiohook()
    const { hook, state } = loadKeyHook(X11_X64, { require: () => fake.mod })
    expect(state.status).toBe('available')
    expect(hook).not.toBeNull()
    const down = vi.fn()
    const up = vi.fn()
    const other = vi.fn()
    hook!.onCtrlDown(down)
    hook!.onCtrlUp(up)
    hook!.onOtherKeyDown(other)
    fake.emit('keydown', 46) // a bare C: not a chord
    fake.emit('keydown', CTRL)
    fake.emit('keydown', CTRL) // autorepeat
    fake.emit('keydown', 46) // Ctrl+C
    fake.emit('keyup', CTRL)
    fake.emit('keyup', CTRL)
    fake.emit('keydown', CTRL_RIGHT)
    fake.emit('keyup', CTRL_RIGHT)
    expect(down).toHaveBeenCalledTimes(2)
    expect(up).toHaveBeenCalledTimes(2)
    expect(other).toHaveBeenCalledTimes(1)
    hook!.stop()
    expect(fake.stop).toHaveBeenCalledTimes(1)
  })

  it('a require that throws → null + a message without paths', () => {
    const err = Object.assign(
      new Error('/home/x/node_modules/uiohook-napi/prebuilds/a.node: bad'),
      {
        code: 'ERR_DLOPEN_FAILED'
      }
    )
    const { hook, state } = loadKeyHook(X11_X64, {
      require: () => {
        throw err
      }
    })
    expect(hook).toBeNull()
    expect(state.status).toBe('unavailable')
    expect(state.message).toContain('ERR_DLOPEN_FAILED')
    expect(state.message).not.toContain('/home/')
    expect(state.message).toMatch(/Ctrl\+Shift\+C/)
  })

  it('a start() that throws → null, never a throw', () => {
    const fake = fakeUiohook({ startThrows: true })
    const { hook, state } = loadKeyHook(X11_X64, { require: () => fake.mod })
    expect(hook).toBeNull()
    expect(state.status).toBe('unavailable')
  })

  it('a module with the wrong shape → null', () => {
    expect(loadKeyHook(X11_X64, { require: () => ({}) }).hook).toBeNull()
  })
}

function registerKeyHookPlatformSupportTests(): void {
  it('Linux arm64 → null from the static table without loading', () => {
    const req = vi.fn()
    const { hook, state } = loadKeyHook(
      { platform: 'linux', arch: 'arm64', session: 'x11' },
      { require: req }
    )
    expect(hook).toBeNull()
    expect(req).not.toHaveBeenCalled()
    expect(state.message).toMatch(/arm64/)
  })

  it('Wayland → null without loading', () => {
    const req = vi.fn()
    expect(
      loadKeyHook({ platform: 'linux', arch: 'x64', session: 'wayland' }, { require: req }).hook
    ).toBeNull()
    expect(req).not.toHaveBeenCalled()
  })

  it('macOS needs the Accessibility permission', () => {
    const mac: PlatformBasics = { platform: 'darwin', arch: 'arm64', session: 'macos' }
    const fake = fakeUiohook()
    const denied = loadKeyHook(mac, {
      require: () => fake.mod,
      isTrustedAccessibilityClient: () => false
    })
    expect(denied.hook).toBeNull()
    expect(denied.state.status).toBe('needs-permission')
    expect(denied.state.settingsUrl).toMatch(/Privacy_Accessibility/)
    const granted = loadKeyHook(mac, {
      require: () => fake.mod,
      isTrustedAccessibilityClient: () => true
    })
    expect(granted.hook).not.toBeNull()
    // no probe wired → cannot verify → degrade, never assume
    expect(loadKeyHook(mac, { require: () => fake.mod }).hook).toBeNull()
  })
}
