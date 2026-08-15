// SOLX-02: the detached always-on-top SOL window — registry, options, and
// teardown exercised against structural fakes (the orbOverlayWire.test.ts
// pattern); the real BrowserWindow shell is on the COWORK QA checklist.
import { describe, it, expect, vi } from 'vitest'
import type { IpcMainInvokeEvent } from 'electron'
import { readdirSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { SOL_WINDOW_CHANNELS } from './solWindow.constants'
import {
  createSolWindowManager,
  registerSolWindowHandlers,
  SOL_WINDOW_OPTIONS,
  SOL_WINDOW_WEB_PREFERENCES,
  type SolWindowHandle
} from './solWindow'

vi.mock('electron', () => ({ BrowserWindow: class {} }))
vi.mock('@electron-toolkit/utils', () => ({ is: { dev: false } }))

function fakeWindow(): {
  handle: SolWindowHandle
  focus: ReturnType<typeof vi.fn>
  close: () => void
} {
  const closedListeners = new Set<() => void>()
  let destroyed = false
  const focus = vi.fn()
  const close = (): void => {
    destroyed = true
    for (const listener of [...closedListeners]) listener()
  }
  return {
    focus,
    close,
    handle: {
      isDestroyed: () => destroyed,
      once: (_event, listener) => {
        closedListeners.add(listener)
      },
      focus,
      close
    }
  }
}

/** The handlers only ever read `sender` through the injected predicate, so a
 *  bare marker object is enough to stand in for the invoke event. */
const EVENT = {} as IpcMainInvokeEvent

function registerWith(isAllowedSender: (event: IpcMainInvokeEvent) => boolean): {
  handlers: Map<string, (event: IpcMainInvokeEvent) => unknown>
  factory: ReturnType<typeof vi.fn>
  w: ReturnType<typeof fakeWindow>
} {
  const handlers = new Map<string, (event: IpcMainInvokeEvent) => unknown>()
  const ipc = {
    handle: (channel: string, fn: (event: IpcMainInvokeEvent) => unknown) =>
      void handlers.set(channel, fn)
  }
  const w = fakeWindow()
  const factory = vi.fn(() => w.handle)
  registerSolWindowHandlers(ipc, factory, isAllowedSender)
  return { handlers, factory, w }
}

describe('SOL_WINDOW_OPTIONS', () => {
  it('is small, always-on-top, frameless', () => {
    expect(SOL_WINDOW_OPTIONS.alwaysOnTop).toBe(true)
    expect(SOL_WINDOW_OPTIONS.frame).toBe(false)
    expect(SOL_WINDOW_OPTIONS.width).toBeLessThanOrEqual(480)
  })
})

describe('window registry', () => {
  it('detach creates the second window once; a repeat focuses it', () => {
    const first = fakeWindow()
    const factory = vi.fn(() => first.handle)
    const manager = createSolWindowManager(factory)
    expect(manager.isDetached()).toBe(false)
    expect(manager.detach()).toEqual({ detached: true })
    expect(manager.isDetached()).toBe(true)
    expect(manager.detach()).toEqual({ detached: true })
    expect(factory).toHaveBeenCalledTimes(1)
    expect(first.focus).toHaveBeenCalledTimes(1)
  })

  it('the closed event clears the registry — a fresh detach creates a new window', () => {
    const windows = [fakeWindow(), fakeWindow()]
    let n = 0
    const manager = createSolWindowManager(() => windows[n++].handle)
    manager.detach()
    windows[0].close() // user closes the detached window directly
    expect(manager.isDetached()).toBe(false)
    manager.detach()
    expect(n).toBe(2)
    expect(manager.isDetached()).toBe(true)
  })

  it('attach closes the live window and is a safe no-op when none is open', () => {
    const w = fakeWindow()
    const manager = createSolWindowManager(() => w.handle)
    expect(manager.attach()).toEqual({ detached: false })
    manager.detach()
    expect(manager.attach()).toEqual({ detached: false })
    expect(w.handle.isDestroyed()).toBe(true)
    expect(manager.isDetached()).toBe(false)
  })
})

describe('IPC registration', () => {
  it('registers detach/attach invoke handlers on the shared channel constants', async () => {
    const { handlers, factory, w } = registerWith(() => true)
    expect([...handlers.keys()].sort()).toEqual(
      [SOL_WINDOW_CHANNELS.attach, SOL_WINDOW_CHANNELS.detach].sort()
    )
    expect(handlers.get(SOL_WINDOW_CHANNELS.detach)?.(EVENT)).toEqual({ detached: true })
    expect(factory).toHaveBeenCalledTimes(1)
    expect(handlers.get(SOL_WINDOW_CHANNELS.attach)?.(EVENT)).toEqual({ detached: false })
    expect(w.handle.isDestroyed()).toBe(true)
  })

  // SEC-M1: the detached orb is always-on-top and frameless, so a foreign
  // webContents that gained IPC reach must not be able to raise it over the
  // user's screen — nor dismiss one the user is using.
  it('ignores detach/attach from a sender that is not the app renderer', () => {
    const { handlers, factory } = registerWith(() => false)
    expect(handlers.get(SOL_WINDOW_CHANNELS.detach)?.(EVENT)).toEqual({ detached: false })
    expect(factory).not.toHaveBeenCalled()
  })

  it('a foreign sender cannot close a window the real renderer opened', () => {
    const allow = { yes: true }
    const { handlers, w } = registerWith(() => allow.yes)
    handlers.get(SOL_WINDOW_CHANNELS.detach)?.(EVENT)
    allow.yes = false
    expect(handlers.get(SOL_WINDOW_CHANNELS.attach)?.(EVENT)).toEqual({ detached: true })
    expect(w.handle.isDestroyed()).toBe(false)
  })
})

describe('channel-literal ratchet', () => {
  it('no sol-window channel literal appears outside the constants module', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const roots = [join(here, '..'), join(here, '..', '..', 'preload')]
    const sources = (dir: string): string[] =>
      readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) return sources(full)
        return entry.name.endsWith('.ts') &&
          !entry.name.endsWith('.test.ts') &&
          entry.name !== 'solWindow.constants.ts'
          ? [full]
          : []
      })
    const offenders = roots
      .flatMap(sources)
      .filter((file) => /["'`]sol-window:/.test(readFileSync(file, 'utf8')))
    expect(offenders).toEqual([])
  })
})

describe('window hardening (SOLX-02 Phase-4 security)', () => {
  it('pins the isolation posture explicitly — never an Electron default', () => {
    // SEC-H2: a template bump must not silently flip the always-on-top
    // window's isolation.
    expect(SOL_WINDOW_WEB_PREFERENCES).toEqual({
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false
    })
  })

  it('the options carry no webPreferences of their own (one source of truth)', () => {
    expect('webPreferences' in SOL_WINDOW_OPTIONS).toBe(false)
    expect(SOL_WINDOW_OPTIONS.alwaysOnTop).toBe(true)
  })
})
