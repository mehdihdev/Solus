import { describe, it, expect, beforeEach } from 'vitest'
import { migrateSettings, useSettingsStore } from './settingsStore'

describe('settingsStore', () => {
  beforeEach(() => {
    useSettingsStore.setState({
      theme: 'dark',
      accent: 'amber',
      solMode: 'Guide'
    })
  })

  it('defaults to dark / amber / Guide', () => {
    const s = useSettingsStore.getState()
    expect(s.theme).toBe('dark')
    expect(s.accent).toBe('amber')
    expect(s.solMode).toBe('Guide')
  })

  it('updates each field independently', () => {
    useSettingsStore.getState().setTheme('light')
    useSettingsStore.getState().setAccent('blue')
    const s = useSettingsStore.getState()
    expect(s.theme).toBe('light')
    expect(s.accent).toBe('blue')
  })

  it('has no density setting (SOLUSDEV-318: it never changed anything)', () => {
    expect('density' in useSettingsStore.getState()).toBe(false)
    expect('setDensity' in useSettingsStore.getState()).toBe(false)
  })

  it('switches SOL mode at any time (ADR-016)', () => {
    useSettingsStore.getState().setSolMode('Expert')
    expect(useSettingsStore.getState().solMode).toBe('Expert')
    useSettingsStore.getState().setSolMode('Guide')
    expect(useSettingsStore.getState().solMode).toBe('Guide')
  })
})

describe('migrateSettings', () => {
  it('drops a persisted density and keeps every other preference', () => {
    expect(
      migrateSettings({ theme: 'light', accent: 'teal', density: 'compact', solMode: 'Expert' })
    ).toEqual({ theme: 'light', accent: 'teal', solMode: 'Expert' })
  })

  it('keeps only known preference keys with valid values — never an action override', () => {
    expect(
      migrateSettings({ theme: 'light', setTheme: 1, solMode: 'Wizard', accent: 7, junk: true })
    ).toEqual({ theme: 'light' })
  })

  it('tolerates an empty or malformed persisted value', () => {
    expect(migrateSettings(undefined)).toEqual({})
    expect(migrateSettings('garbage')).toEqual({})
  })
})
