// SOLUSDEV-252 S3: the tray (wireflow §E) — icon (dot overlay while SOL sees
// the screen), tooltip, menu with Open / Guide|Build radio / sees-your-screen
// checkbox / shortcuts line / Quit. Electron's Tray, Menu and nativeImage are
// injected as structural slices; `createTray` never throws: no host → null and
// the window header carries the same state.
import { summonShortcutLabel } from './hotkeys/globalHotkeys'
import type { PlatformBasics } from './platform/capabilities'
import type { SolActionMode } from './solSettings'
import type { SolState } from './sol-window/solWindow'

/** Structural slice of Electron's MenuItemConstructorOptions. */
export interface TrayMenuItem {
  label?: string
  type?: 'normal' | 'separator' | 'radio' | 'checkbox'
  checked?: boolean
  enabled?: boolean
  click?: () => void
}

/** Structural slice of Electron's Tray. */
export interface TrayHandle {
  setToolTip(tooltip: string): void
  setContextMenu(menu: unknown): void
  setImage(image: unknown): void
  on(event: 'click', listener: () => void): void
  destroy(): void
}

export interface TrayDeps {
  basics: PlatformBasics
  env: NodeJS.ProcessEnv
  /** nativeImage handles: the mark, and the mark with the sees-screen dot. */
  icons: { off: unknown; on: unknown }
  createTray(image: unknown): TrayHandle
  buildMenu(template: TrayMenuItem[]): unknown
  onOpen(): void
  onSetMode(mode: SolActionMode): void
  onSetScreenIntelligence(on: boolean): void
  /** The hold-Ctrl gestures (native key hook) consent toggle (§7). */
  onSetHotkeys(on: boolean): void
  onQuit(): void
  warn(message: string): void
}

export interface SolTray {
  update(state: SolState): void
  destroy(): void
}

const MODE_LABEL: Record<SolActionMode, string> = { guide: 'Guide', do: 'Build' }

export function trayTooltip(state: SolState): string {
  if (state.hotkeys?.circleModeActive) return 'SOL · Circle mode — draw a loop'
  return `SOL · ${MODE_LABEL[state.actionMode]}${state.screenIntelligence ? ' · sees your screen' : ''}`
}

export function trayMenu(state: SolState, deps: TrayDeps): TrayMenuItem[] {
  return [
    { label: 'Open SOL', click: deps.onOpen },
    { type: 'separator' },
    ...(['guide', 'do'] as const).map(
      (mode): TrayMenuItem => ({
        label: MODE_LABEL[mode],
        type: 'radio',
        checked: state.actionMode === mode,
        click: () => deps.onSetMode(mode)
      })
    ),
    {
      label: 'SOL sees your screen',
      type: 'checkbox',
      checked: state.screenIntelligence,
      click: () => deps.onSetScreenIntelligence(!state.screenIntelligence)
    },
    {
      label: 'Hold-Ctrl gestures',
      type: 'checkbox',
      checked: state.hotkeysEnabled,
      click: () => deps.onSetHotkeys(!state.hotkeysEnabled)
    },
    { type: 'separator' },
    {
      label:
        state.hotkeys?.summary ||
        `${summonShortcutLabel(deps.basics.platform)} — open SOL · Ctrl+Space — mode · Ctrl+Shift+C — circle mode`,
      enabled: false
    },
    { type: 'separator' },
    { label: 'Quit', click: deps.onQuit }
  ]
}

export function createTray(deps: TrayDeps): SolTray | null {
  // ponytail: Electron cannot tell whether GNOME has an indicator host (the
  // AppIndicator extension) — without one the icon silently never shows. We
  // skip only a session with no display at all, try otherwise, and the
  // window header carries the same state either way.
  if (deps.basics.platform === 'linux' && !deps.env.DISPLAY && !deps.env.WAYLAND_DISPLAY) {
    return null
  }
  let tray: TrayHandle
  try {
    tray = deps.createTray(deps.icons.off)
    tray.on('click', deps.onOpen)
  } catch (error) {
    deps.warn(`[tray] unavailable: ${error instanceof Error ? error.message : 'unknown'}`)
    return null
  }
  return {
    update(state) {
      tray.setImage(state.screenIntelligence ? deps.icons.on : deps.icons.off)
      tray.setToolTip(trayTooltip(state))
      tray.setContextMenu(deps.buildMenu(trayMenu(state, deps)))
    },
    destroy: () => tray.destroy()
  }
}

/** A fresh RGBA/BGRA bitmap with a green dot in the bottom-right corner
 *  (channel 1 is green in both byte orders, so this needs no format probe). */
export function paintDot(bitmap: Buffer, width: number, height: number): Buffer {
  const out = Buffer.from(bitmap)
  const r = Math.max(2, Math.round(width / 6))
  const cx = width - r - 1
  const cy = height - r - 1
  for (let y = cy - r; y <= cy + r; y++) {
    for (let x = cx - r; x <= cx + r; x++) {
      if (x < 0 || y < 0 || x >= width || y >= height) continue
      if ((x - cx) ** 2 + (y - cy) ** 2 > r * r) continue
      out.set([60, 200, 90, 255], (y * width + x) * 4)
    }
  }
  return out
}
