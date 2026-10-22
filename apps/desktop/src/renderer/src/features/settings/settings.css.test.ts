// settings.css is the motion contract for Settings (SOLUSDEV-318): every
// animated class exists, and every one is switched off for reduced motion.
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const css = fs.readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), 'settings.css'),
  'utf8'
)
const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))

describe('settings.css', () => {
  it.each([
    '.settings-section-in',
    '.settings-row-in',
    '.settings-reveal',
    '.settings-nav-item',
    '.settings-tile'
  ])('%s is defined and switched off for reduced motion', (cls) => {
    expect(css).toContain(`${cls} {`)
    expect(reduced).toContain(cls)
  })

  it('collapses a leaving card on the same clock the code waits for', () => {
    expect(css).toMatch(/\.settings-reveal\[data-leaving\][^{]*\{[^}]*0\.22s/)
  })

  it('pins the sidebar only when it sits beside the page', () => {
    const query = css.slice(css.indexOf('@container settings'))
    expect(query).toMatch(/\.settings-sidebar \{[^}]*position: sticky/)
  })
})
