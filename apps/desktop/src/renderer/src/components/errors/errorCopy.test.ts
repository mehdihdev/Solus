// SOLUSDEV-311: the fallback's words follow the ADR-016 SOL mode. Guide
// explains what happened and what is safe, in plain language; Expert leads
// with the error. Neither claims more than is true (Empty beats invented).
import { describe, it, expect } from 'vitest'
import {
  detailsText,
  fallbackCopy,
  surfaceForHash,
  surfaceForRoute,
  SURFACE_LABELS
} from './errorCopy'

const ERR = { name: 'TypeError', message: "Cannot read properties of undefined (reading 'joints')" }

describe('fallbackCopy', () => {
  it('Guide, panel: names the panel, says the rest still works, and what each action does', () => {
    const copy = fallbackCopy({
      mode: 'Guide',
      scope: 'panel',
      surface: 'bench',
      error: ERR,
      logged: true
    })
    expect(copy.title).toBe('Live Bench hit a problem')
    expect(copy.body).toContain('the rest of Solus still works')
    expect(copy.body).toContain('Reload panel')
    expect(copy.body).toContain("saved to Solus's error log")
    expect(copy.detail).toBeUndefined()
  })

  it('Guide never claims the error was logged when it could not be', () => {
    const copy = fallbackCopy({
      mode: 'Guide',
      scope: 'panel',
      surface: 'bench',
      error: ERR,
      logged: false
    })
    expect(copy.body).not.toContain('log')
  })

  it('Guide, app: says projects and tools are unaffected and how to recover', () => {
    const copy = fallbackCopy({
      mode: 'Guide',
      scope: 'app',
      surface: 'root',
      error: ERR,
      logged: true
    })
    expect(copy.title).toBe('Solus hit a problem')
    expect(copy.body).toContain('Reload app')
    expect(copy.body).toContain('nothing in your projects or connected tools was changed')
  })

  it('Expert: terse title, the error itself as the detail line', () => {
    const panel = fallbackCopy({
      mode: 'Expert',
      scope: 'panel',
      surface: 'sol',
      error: ERR,
      logged: true
    })
    expect(panel.title).toBe('SOL crashed')
    expect(panel.detail).toBe(`TypeError: ${ERR.message}`)
    expect(panel.body.length).toBeLessThan(80)
    const app = fallbackCopy({
      mode: 'Expert',
      scope: 'app',
      surface: 'root',
      error: ERR,
      logged: true
    })
    expect(app.title).toBe('Renderer crashed')
  })
})

describe('detailsText', () => {
  it('is a plain-text report with where, when and the scrubbed error', () => {
    const text = detailsText({
      surface: 'bench',
      error: {
        name: 'TypeError',
        message: 'boom for ada@example.com',
        stack: 'TypeError\n    at /Users/ada/x.js:1:1'
      },
      componentStack: '\n    at BenchScreen',
      at: new Date('2026-09-26T10:00:00Z')
    })
    expect(text).toContain('Where: Live Bench (bench)')
    expect(text).toContain('When: 2026-09-26T10:00:00.000Z')
    expect(text).toContain('Error: TypeError: boom for [email]')
    expect(text).toContain('at ~/x.js:1:1')
    expect(text).toContain('at BenchScreen')
    expect(text).not.toContain('ada@example.com')
  })
})

describe('surfaces', () => {
  it.each([
    [{ name: 'home' }, 'home'],
    [{ name: 'bench' }, 'bench'],
    [{ name: 'settings' }, 'settings'],
    [{ name: 'alert', alertId: 'a' }, 'alert'],
    [{ name: 'ext-page', slug: 'bom' }, 'extension']
  ] as const)('route %o → %s', (route, surface) => {
    expect(surfaceForRoute(route)).toBe(surface)
  })

  it.each([
    ['#/', 'root'],
    ['#/sol-window', 'sol_window'],
    ['#/overlay', 'overlay'],
    ['#/ext-window/bom', 'ext_window'],
    ['', 'root']
  ])('hash %s → %s', (hash, surface) => {
    expect(surfaceForHash(hash)).toBe(surface)
  })

  it('has a human label for every surface', () => {
    expect(SURFACE_LABELS.bench).toBe('Live Bench')
    expect(SURFACE_LABELS.extension).toBe('this extension')
  })
})
