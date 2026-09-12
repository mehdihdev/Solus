// SOLUSDEV-252 S3: the OPTIONAL native key hook (docs/architecture/sol-window.md
// §5). `uiohook-napi` is an optionalDependency whose Linux arm64 "prebuild" is an
// x86-64 ELF and whose libuiohook is X11-only, so loading is a self-test:
// require in try/catch, start in try/catch, platform gate first. Any failure is
// `null` plus a plain-language CapabilityState — never a throw, never a crash.
// The hook only observes; nothing is ever swallowed or injected.
import { createRequire } from 'node:module'
import {
  staticCapabilities,
  type CapabilityState,
  type PlatformBasics
} from '../platform/capabilities'

export interface KeyHook {
  onCtrlDown(cb: () => void): void
  onCtrlUp(cb: () => void): void
  onOtherKeyDown(cb: () => void): void
  stop(): void
}

export interface KeyHookLoad {
  hook: KeyHook | null
  state: CapabilityState
}

interface KeyEvent {
  keycode: number
}

/** The slice of uiohook-napi we touch (dist/index.d.ts). */
interface UiohookModule {
  uIOhook: {
    on(event: 'keydown' | 'keyup', cb: (e: KeyEvent) => void): unknown
    start(): void
    stop(): void
  }
  UiohookKey: { Ctrl: number; CtrlRight: number }
}

// Non-literal so neither rollup (electron-vite bundles anything outside
// `dependencies`) nor a static scan ever inlines the native module.
const HOOK_MODULE = 'uiohook-napi'

const FALLBACK_HINT = 'use Ctrl+Shift+C circle mode and Ctrl+Shift+Space to open SOL.'

function isUiohookModule(m: unknown): m is UiohookModule {
  const mod = m as Partial<UiohookModule> | null
  return (
    typeof mod?.uIOhook?.on === 'function' &&
    typeof mod.uIOhook.start === 'function' &&
    typeof mod.uIOhook.stop === 'function' &&
    typeof mod.UiohookKey?.Ctrl === 'number' &&
    typeof mod.UiohookKey.CtrlRight === 'number'
  )
}

/** Error class/code only — never a path, never the raw message. */
function reason(err: unknown): string {
  const e = err as { code?: unknown; name?: unknown } | null
  return typeof e?.code === 'string'
    ? e.code
    : typeof e?.name === 'string'
      ? e.name
      : 'unknown error'
}

const unavailable = (why: string): KeyHookLoad => ({
  hook: null,
  state: { status: 'unavailable', message: `The native key hook ${why}; ${FALLBACK_HINT}` }
})

function wire(mod: UiohookModule): KeyHook {
  const { Ctrl, CtrlRight } = mod.UiohookKey
  const isCtrl = (k: number): boolean => k === Ctrl || k === CtrlRight
  const cbs = { down: () => {}, up: () => {}, other: () => {} }
  let ctrlHeld = false // X11 autorepeats keydown while held: dedupe to one edge
  mod.uIOhook.on('keydown', (e) => {
    if (isCtrl(e.keycode)) {
      if (ctrlHeld) return
      ctrlHeld = true
      cbs.down()
    } else if (ctrlHeld) cbs.other()
  })
  mod.uIOhook.on('keyup', (e) => {
    if (!isCtrl(e.keycode) || !ctrlHeld) return
    ctrlHeld = false
    cbs.up()
  })
  return {
    onCtrlDown: (cb) => (cbs.down = cb),
    onCtrlUp: (cb) => (cbs.up = cb),
    onOtherKeyDown: (cb) => (cbs.other = cb),
    stop: () => {
      try {
        mod.uIOhook.stop()
      } catch {
        // already stopped or the native side is gone: nothing left to release
      }
    }
  }
}

export function loadKeyHook(
  basics: PlatformBasics,
  opts: {
    require?: (id: string) => unknown
    /** darwin: `systemPreferences.isTrustedAccessibilityClient(false)`. */
    isTrustedAccessibilityClient?: () => boolean
  } = {}
): KeyHookLoad {
  const posture = staticCapabilities(basics).hook
  if (posture.status === 'unavailable') return { hook: null, state: posture }
  if (basics.platform === 'darwin' && opts.isTrustedAccessibilityClient?.() !== true) {
    return { hook: null, state: posture } // needs-permission + the Accessibility deep link
  }
  // resolved inside the try: a bundler context without __filename degrades like any other failure
  const load = opts.require ?? ((id: string): unknown => createRequire(__filename)(id))
  let mod: unknown
  try {
    mod = load(HOOK_MODULE)
  } catch (err) {
    return unavailable(`could not be loaded (${reason(err)})`)
  }
  if (!isUiohookModule(mod)) return unavailable('has an unexpected shape')
  try {
    mod.uIOhook.start()
  } catch (err) {
    return unavailable(`could not start (${reason(err)})`)
  }
  return { hook: wire(mod), state: { status: 'available', message: '' } }
}
