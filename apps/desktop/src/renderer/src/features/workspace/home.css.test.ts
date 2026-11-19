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

// SOLUSDEV-328: the overview ↔ project page morph (homeTransition.ts). Each named part is one
// element in either view, so the browser can move it between the two snapshots.
describe('home.css — the team ↔ project morph', () => {
  it.each([
    ['.home-vt-rail', 'home-rail'],
    ['.home-vt-projects', 'home-projects'],
    ['.home-vt-pane', 'home-pane']
  ])('%s names its part %s', (cls, name) => {
    const rule = css.slice(css.indexOf(`${cls} {`))
    expect(rule.slice(0, rule.indexOf('}'))).toContain(`view-transition-name: ${name}`)
  })

  it('slides the pane each way', () => {
    expect(css).toContain(":root[data-home-nav='in']::view-transition-new(home-pane)")
    expect(css).toContain(":root[data-home-nav='out']::view-transition-new(home-pane)")
    // No CSS switch for the pane fade: removing one when the morph ends would replay it.
    expect(css).not.toMatch(/data-home-nav\][^{]*\.home-pane-in/)
  })

  it('fades through: the old picture is all but gone before the new one rises, so layouts never stack', () => {
    const rule = (sel: string): string => {
      const at = css.lastIndexOf(sel)
      return css.slice(at, css.indexOf('}', at))
    }
    expect(rule('::view-transition-old(home-rail),')).toMatch(/animation: home-vt-fade-out 0\.12s/)
    expect(rule('::view-transition-new(home-rail),')).toMatch(
      /animation: home-vt-fade-in 0\.26s [^;]* 0\.08s both/
    )
  })

  it('switches every morph off for reduced motion', () => {
    expect(reduced).toContain('::view-transition-group(*)')
  })
})
