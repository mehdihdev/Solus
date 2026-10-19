// Home's motion (SOLUSDEV-317): transform/opacity fade-rises and short
// transitions, every one switched off under prefers-reduced-motion. Pinned by
// reading the stylesheet — jsdom runs no animations.
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { homeStagger, HOME_STAGGER_MS, HOME_STAGGER_CAP } from './homeMotion'

const css = fs.readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), 'home.css'),
  'utf8'
)
const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))

describe('home.css', () => {
  it('animates only transform and opacity', () => {
    const frames = css.slice(css.indexOf('@keyframes home-fade-rise'), css.indexOf('}\n}') + 3)
    expect(frames).toMatch(/opacity/)
    expect(frames).toMatch(/transform/)
    expect(frames).not.toMatch(/height|width|top|left|margin/)
  })

  it.each(['.home-pane-in', '.home-row-in', '.home-card', '.home-tab-indicator', '.home-segment'])(
    '%s is defined and switched off for reduced motion',
    (cls) => {
      expect(css).toContain(`${cls} {`)
      expect(reduced).toContain(cls)
    }
  )
})

describe('homeStagger', () => {
  it('delays each row a little more, capped so long lists never drag', () => {
    expect(homeStagger(0)).toEqual({ animationDelay: '0ms' })
    expect(homeStagger(2)).toEqual({ animationDelay: `${2 * HOME_STAGGER_MS}ms` })
    expect(homeStagger(50)).toEqual({ animationDelay: `${HOME_STAGGER_CAP * HOME_STAGGER_MS}ms` })
  })
})
