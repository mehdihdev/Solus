// SOLUSDEV-235 — the menu bar's data stays honest and safe.
import { describe, it, expect } from 'vitest'
import { MENUS } from './menuBar.constants'

describe('MENUS', () => {
  it('has unique menu ids and unique item labels within each menu', () => {
    expect(new Set(MENUS.map((m) => m.id)).size).toBe(MENUS.length)
    for (const m of MENUS) {
      const labels = m.items.filter((i) => i !== 'separator').map((i) => i.label)
      expect(new Set(labels).size).toBe(labels.length)
    }
  })

  it('only links to https destinations', () => {
    for (const m of MENUS)
      for (const i of m.items)
        if (i !== 'separator' && 'href' in i) expect(i.href).toMatch(/^https:\/\//)
  })

  it('gives every project-scoped menu a hint for the no-project state', () => {
    for (const m of MENUS) {
      const scoped = m.items.some((i) => i !== 'separator' && 'screen' in i && i.projectScoped)
      if (scoped) expect(m.projectHint).toBeTruthy()
    }
  })
})
