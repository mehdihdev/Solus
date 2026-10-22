import { describe, it, expect, beforeEach } from 'vitest'
import { applyTheme, buildThemeVars } from './applyTheme'
import { SOLUS_THEMES, SOLUS_ACCENTS, dcol } from './tokens.constants'

describe('buildThemeVars', () => {
  it('maps a theme + accent to the full CSS var set', () => {
    const vars = buildThemeVars('dark', 'amber')
    expect(vars['--bg']).toBe(SOLUS_THEMES.dark.bg)
    expect(vars['--tx']).toBe(SOLUS_THEMES.dark.tx)
    expect(vars['--acc']).toBe(SOLUS_ACCENTS.amber.c)
    expect(vars['--acc-ink']).toBe(SOLUS_ACCENTS.amber.ink)
  })

  it('falls back to dark + amber for unknown ids', () => {
    // @ts-expect-error intentionally passing an invalid theme id
    const vars = buildThemeVars('does-not-exist', 'nope')
    expect(vars['--bg']).toBe(SOLUS_THEMES.dark.bg)
    expect(vars['--acc']).toBe(SOLUS_ACCENTS.amber.c)
  })

  it('produces distinct values per theme', () => {
    expect(buildThemeVars('light', 'blue')['--bg']).toBe(SOLUS_THEMES.light.bg)
    expect(buildThemeVars('monokai', 'teal')['--acc']).toBe(SOLUS_ACCENTS.teal.c)
  })
})

describe('applyTheme', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('style')
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.removeAttribute('data-density')
    document.body.removeAttribute('style')
  })

  it('writes every CSS var onto the document root', () => {
    applyTheme('dark', 'amber')
    const root = document.documentElement
    expect(root.style.getPropertyValue('--bg')).toBe(SOLUS_THEMES.dark.bg)
    expect(root.style.getPropertyValue('--acc')).toBe(SOLUS_ACCENTS.amber.c)
  })

  it('sets data-theme and no density attribute (SOLUSDEV-318)', () => {
    applyTheme('light', 'blue')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(document.documentElement.hasAttribute('data-density')).toBe(false)
  })

  it('sets the body background, varying per theme', () => {
    applyTheme('solarized', 'violet')
    const solarizedBg = document.body.style.background
    expect(solarizedBg).not.toBe('')
    applyTheme('light', 'amber')
    expect(document.body.style.background).not.toBe(solarizedBg)
  })
})

describe('dcol', () => {
  it('returns a CSS var reference for a domain', () => {
    expect(dcol('sw')).toBe('var(--sw)')
    expect(dcol('rt')).toBe('var(--rt)')
  })
})
