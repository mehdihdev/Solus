// onboarding.css is the motion contract for onboarding (SOLUSDEV-323,
// docs/wireflows/onboarding.md §Motion): every animated class exists, motion is
// transform/opacity/filter keyframes only, colours are tokens, and reduced
// motion switches it all off.
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const css = fs.readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), 'onboarding.css'),
  'utf8'
)
const reducedAt = css.indexOf('@media (prefers-reduced-motion: reduce)')
const reduced = css.slice(reducedAt)

const keyframes = (): Array<{ name: string; body: string }> =>
  [...css.matchAll(/@keyframes ([\w-]+)\s*\{([\s\S]*?)\n\}/g)].map((m) => ({
    name: m[1],
    body: m[2]
  }))

describe('onboarding.css', () => {
  it.each([
    '.ob-rise',
    '.ob-orb',
    '.ob-chip',
    '.ob-wire',
    '.ob-node',
    '.ob-edge',
    '.ob-key',
    '.ob-sheen',
    '.ob-tile',
    '.ob-choice'
  ])('%s is defined', (cls) => {
    expect(css).toContain(`${cls}`)
  })

  it('has a reduced-motion block that stills every animation and transition', () => {
    expect(reducedAt).toBeGreaterThan(-1)
    expect(reduced).toMatch(/animation:\s*none/)
    expect(reduced).toMatch(/transition:\s*none/)
  })

  it('animates only transform, opacity, filter, stroke and background offsets', () => {
    const allowed = new Set([
      'transform',
      'opacity',
      'filter',
      'stroke-dashoffset',
      'background-position'
    ])
    expect(keyframes().length).toBeGreaterThan(0)
    for (const { name, body } of keyframes()) {
      for (const m of body.matchAll(/([a-z-]+)\s*:/g)) {
        expect([name, allowed.has(m[1])]).toEqual([name, true])
      }
    }
  })

  it('uses tokens, never raw hex colours', () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })

  it('uses the wireflow easings', () => {
    expect(css).toContain('cubic-bezier(0.2, 0.8, 0.2, 1)')
    expect(css).toContain('cubic-bezier(0.34, 1.56, 0.64, 1)')
  })
})
