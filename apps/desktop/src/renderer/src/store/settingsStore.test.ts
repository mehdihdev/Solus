import { describe, it, expect, beforeEach } from 'vitest'
import { useSettingsStore } from './settingsStore'

describe('settingsStore', () => {
  beforeEach(() => {
    useSettingsStore.setState({
      theme: 'dark',
      accent: 'amber',
      density: 'regular',
      solMode: 'Guide'
    })
  })

  it('defaults to dark / amber / regular / Guide', () => {
    const s = useSettingsStore.getState()
    expect(s.theme).toBe('dark')
    expect(s.accent).toBe('amber')
    expect(s.density).toBe('regular')
    expect(s.solMode).toBe('Guide')
  })

  it('updates each field independently', () => {
    useSettingsStore.getState().setTheme('light')
    useSettingsStore.getState().setAccent('blue')
    useSettingsStore.getState().setDensity('compact')
    const s = useSettingsStore.getState()
    expect(s.theme).toBe('light')
    expect(s.accent).toBe('blue')
    expect(s.density).toBe('compact')
  })

  it('switches SOL mode at any time (ADR-016)', () => {
    useSettingsStore.getState().setSolMode('Expert')
    expect(useSettingsStore.getState().solMode).toBe('Expert')
    useSettingsStore.getState().setSolMode('Guide')
    expect(useSettingsStore.getState().solMode).toBe('Guide')
  })
})
