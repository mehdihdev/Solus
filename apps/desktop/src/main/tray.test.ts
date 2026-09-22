// SOLUSDEV-252 S3: the tray (wireflow §E) against injected Tray/Menu slices —
// menu reflects mode/setting, clicks call back, a missing host → null.
import { describe, it, expect, vi } from 'vitest'
import { createTray, paintDot, trayTooltip, type TrayDeps, type TrayMenuItem } from './tray'
import type { SolState } from './sol-window/solWindow'

const STATE: SolState = {
  actionMode: 'guide',
  screenIntelligence: false,
  hotkeysEnabled: true,
  alwaysOnTop: false,
  capture: { mode: 'available', message: '' },
  hotkeys: null,
  lastRegionRefused: false
}

function harness(over: Partial<TrayDeps> = {}): {
  deps: TrayDeps
  tooltips: string[]
  menus: TrayMenuItem[][]
  images: string[]
  clicks: string[]
  trayClick: () => void
  destroyed: () => boolean
} {
  const tooltips: string[] = []
  const menus: TrayMenuItem[][] = []
  const images: string[] = []
  const clicks: string[] = []
  let onTrayClick = (): void => {}
  let destroyed = false
  const deps: TrayDeps = {
    basics: { platform: 'linux', arch: 'arm64', session: 'x11' },
    env: { DISPLAY: ':1', XDG_CURRENT_DESKTOP: 'ubuntu:GNOME' },
    icons: { off: 'off', on: 'on' },
    createTray: (image) => {
      images.push(image as string)
      return {
        setToolTip: (t) => void tooltips.push(t),
        setContextMenu: (m) => void menus.push(m as TrayMenuItem[]),
        setImage: (i) => void images.push(i as string),
        on: (_e, cb) => {
          onTrayClick = cb
        },
        destroy: () => {
          destroyed = true
        }
      }
    },
    buildMenu: (template) => template,
    onOpen: () => void clicks.push('open'),
    onSetMode: (m) => void clicks.push(`mode:${m}`),
    onSetScreenIntelligence: (b) => void clicks.push(`si:${b}`),
    onSetHotkeys: (b) => void clicks.push(`hk:${b}`),
    onQuit: () => void clicks.push('quit'),
    warn: vi.fn(),
    ...over
  }
  return {
    deps,
    tooltips,
    menus,
    images,
    clicks,
    trayClick: () => onTrayClick(),
    destroyed: () => destroyed
  }
}

const byLabel = (menu: TrayMenuItem[], label: string): TrayMenuItem => {
  const item = menu.find((i) => i.label === label)
  if (!item) throw new Error(`no item ${label}`)
  return item
}

describe('createTray', () => {
  registerTrayRenderingTests()
  registerTrayActionsAndFallbacksTests()
})

describe('paintDot', () => {
  it('paints a green dot in the bottom-right corner, leaving the rest untouched', () => {
    const w = 22
    const rgba = Buffer.alloc(w * w * 4, 0)
    const out = paintDot(rgba, w, w)
    expect(out).not.toBe(rgba)
    const px = (x: number, y: number): number[] => [
      ...out.subarray((y * w + x) * 4, (y * w + x) * 4 + 4)
    ]
    expect(px(19, 19)[3]).toBe(255) // dot centre opaque
    expect(px(19, 19)[1]).toBeGreaterThan(150) // green channel in both BGRA and RGBA
    expect(px(2, 2)).toEqual([0, 0, 0, 0])
    expect(rgba.every((b) => b === 0)).toBe(true) // input not mutated
  })
})

function registerTrayRenderingTests(): void {
  it('builds tooltip + menu from the state and rebuilds on update', () => {
    const h = harness()
    const tray = createTray(h.deps)
    expect(tray).not.toBeNull()
    tray?.update(STATE)
    expect(h.tooltips.at(-1)).toBe('SOL · Guide')
    const menu = h.menus.at(-1) ?? []
    expect(menu.map((i) => i.label ?? i.type)).toEqual([
      'Open SOL',
      'separator',
      'Guide',
      'Build',
      'SOL sees your screen',
      'Hold-Ctrl gestures',
      'separator',
      'Ctrl+Shift+Space — open SOL · Ctrl+Space — mode · Ctrl+Shift+C — circle mode',
      'separator',
      'Quit'
    ])
    expect(byLabel(menu, 'Guide')).toMatchObject({ type: 'radio', checked: true })
    expect(byLabel(menu, 'Build')).toMatchObject({ type: 'radio', checked: false })
    expect(byLabel(menu, 'SOL sees your screen')).toMatchObject({
      type: 'checkbox',
      checked: false
    })
    expect(byLabel(menu, 'Hold-Ctrl gestures')).toMatchObject({ type: 'checkbox', checked: true })
    expect(menu[7].enabled).toBe(false)
    expect(h.images.at(-1)).toBe('off')

    tray?.update({
      ...STATE,
      actionMode: 'do',
      screenIntelligence: true,
      hotkeys: {
        hook: { status: 'unavailable', message: '' },
        shortcuts: {},
        mode: 'fallback',
        circleModeActive: false,
        summary: 'Ctrl+Shift+Space — open · Ctrl+Space — mode · Ctrl+Shift+C — circle mode'
      }
    })
    expect(h.tooltips.at(-1)).toBe('SOL · Build · sees your screen')
    const next = h.menus.at(-1) ?? []
    expect(byLabel(next, 'Build').checked).toBe(true)
    expect(byLabel(next, 'SOL sees your screen').checked).toBe(true)
    expect(next[7].label).toMatch(/Ctrl\+Shift\+Space/)
    expect(h.images.at(-1)).toBe('on')
  })
}

function registerTrayActionsAndFallbacksTests(): void {
  it('menu clicks call the callbacks; the checkbox toggles the current value', () => {
    const h = harness()
    const tray = createTray(h.deps)
    tray?.update(STATE)
    const menu = h.menus.at(-1) ?? []
    byLabel(menu, 'Open SOL').click?.()
    byLabel(menu, 'Build').click?.()
    byLabel(menu, 'SOL sees your screen').click?.()
    byLabel(menu, 'Hold-Ctrl gestures').click?.()
    byLabel(menu, 'Quit').click?.()
    h.trayClick()
    expect(h.clicks).toEqual(['open', 'mode:do', 'si:true', 'hk:false', 'quit', 'open'])
    tray?.destroy()
    expect(h.destroyed()).toBe(true)
  })

  it('circle mode shows in the tooltip', () => {
    expect(
      trayTooltip({
        ...STATE,
        hotkeys: {
          hook: { status: 'unavailable', message: '' },
          shortcuts: {},
          mode: 'fallback',
          circleModeActive: true,
          summary: ''
        }
      })
    ).toBe('SOL · Circle mode — draw a loop')
  })

  it('Linux with no graphical session, or a Tray constructor that throws → null + warning', () => {
    const headless = harness({ env: {} })
    expect(createTray(headless.deps)).toBeNull()
    const boom = harness({
      createTray: () => {
        throw new Error('no indicator host')
      }
    })
    expect(createTray(boom.deps)).toBeNull()
    expect(boom.deps.warn).toHaveBeenCalledTimes(1)
  })
}
