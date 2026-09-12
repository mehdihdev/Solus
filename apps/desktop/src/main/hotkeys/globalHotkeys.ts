import type { PlatformBasics } from '../platform/capabilities'

// SOLUSDEV-252 S3: `globalShortcut` chords (docs/architecture/sol-window.md §2-§3).
// Ctrl+Space toggles the mode; Ctrl+Shift+C enters circle mode (useful on a
// trackpad even with the hook); CommandOrControl+Shift+Space always summons. A failed registration is a message, never a throw.
export const ACCELERATORS = {
  toggleMode: 'Control+Space',
  summonFallback: 'CommandOrControl+Shift+Space',
  circleMode: 'Control+Shift+C'
} as const

export interface GlobalShortcutApi {
  register(accelerator: string, cb: () => void): boolean
  unregister(accelerator: string): void
  unregisterAll(): void
}

export interface ShortcutStatus {
  ctrlSpace: boolean
  spawnFallback: boolean
  circleMode: boolean
}

export interface GlobalHotkeysOpts {
  /** False only when the platform cannot attempt shortcut registration. */
  available: boolean
  hookAvailable: boolean
  platform?: PlatformBasics['platform']
  onToggleMode(): void
  onSummon(): void
  onCircleMode(): void
}

export interface GlobalHotkeys {
  shortcuts: ShortcutStatus
  /** One line per chord another app already owns. */
  messages: string[]
  stop(): void
}

export const summonShortcutLabel = (platform: string): string =>
  `${platform === 'darwin' ? 'Cmd' : 'Ctrl'}+Shift+Space`

export function enableShortcutPortal(
  commandLine: {
    getSwitchValue(name: string): string
    appendSwitch(name: string, value: string): void
  },
  basics: PlatformBasics
): void {
  if (basics.session !== 'wayland') return
  const features = new Set(commandLine.getSwitchValue('enable-features').split(',').filter(Boolean))
  features.add('GlobalShortcutsPortal')
  commandLine.appendSwitch('enable-features', [...features].join(','))
}

const label = (acc: string, platform: string): string =>
  acc.replace('CommandOrControl', platform === 'darwin' ? 'Cmd' : 'Ctrl').replace('Control', 'Ctrl')

export function registerGlobalHotkeys(
  api: GlobalShortcutApi,
  opts: GlobalHotkeysOpts
): GlobalHotkeys {
  const messages: string[] = []
  // Only what WE registered is ours to release: unregisterAll would also drop
  // chords another module registered (and stop() runs on every settings restart).
  const registered: string[] = []
  const tryRegister = (acc: string, cb: () => void): boolean => {
    let ok = false
    try {
      ok = api.register(acc, cb)
    } catch {
      ok = false
    }
    if (ok) registered.push(acc)
    else
      messages.push(`${label(acc, opts.platform ?? 'linux')} is unavailable; use Open SOL window`)
    return ok
  }
  if (!opts.available) {
    return {
      shortcuts: { ctrlSpace: false, spawnFallback: false, circleMode: false },
      messages,
      stop: () => {}
    }
  }
  const shortcuts: ShortcutStatus = {
    ctrlSpace: tryRegister(ACCELERATORS.toggleMode, opts.onToggleMode),
    spawnFallback: tryRegister(ACCELERATORS.summonFallback, opts.onSummon),
    circleMode: tryRegister(ACCELERATORS.circleMode, opts.onCircleMode)
  }
  return { shortcuts, messages, stop: () => registered.forEach((acc) => api.unregister(acc)) }
}
