import { describe, it, expect } from 'vitest'
import { LOGO_ALIASES, integrationLogo, logoMapFrom, logoClass } from './integrationLogos'

describe('logoMapFrom', () => {
  it('maps a bundled asset to its lowercase provider id', () => {
    const map = logoMapFrom({
      '../../assets/integrations/github.svg': '/assets/github-abc.svg',
      '../../assets/integrations/KiCad.png': '/assets/kicad-def.png'
    })
    expect(map.github).toBe('/assets/github-abc.svg')
    expect(map.kicad).toBe('/assets/kicad-def.png')
  })

  it('prefers an svg over a png for the same provider', () => {
    const map = logoMapFrom({
      '../../assets/integrations/altium.png': '/assets/altium.png',
      '../../assets/integrations/altium.svg': '/assets/altium.svg'
    })
    expect(map.altium).toBe('/assets/altium.svg')
  })

  it('ignores paths without a usable basename', () => {
    expect(logoMapFrom({ '../../assets/integrations/.svg': '/x.svg' })).toEqual({})
  })
})

describe('integrationLogo', () => {
  it('returns null for a provider without a bundled logo (letter-mark fallback)', () => {
    expect(integrationLogo('someFutureCad')).toBeNull()
  })

  it('resolves the bundled brand files, case-insensitively, for every row id', () => {
    // The five simulator/tool logos added on 2026-09-07 live under their brand
    // names (Fusion.svg, Mujoco.svg, …); rows ask by lowercase id.
    for (const id of ['github', 'kicad', 'onshape', 'fusion', 'mujoco', 'gazebo', 'isaac']) {
      // Vite inlines small svgs as data: urls and serves large ones by path.
      expect(integrationLogo(id), id).toMatch(/\.svg$|^data:image\/svg\+xml/)
    }
    expect(integrationLogo('Fusion')).toBe(integrationLogo('fusion'))
  })

  it('aliases the MCAP recording kind onto the MCAP logo', () => {
    expect(LOGO_ALIASES['mcap-replay']).toBe('mcap')
    expect(integrationLogo('mcap-replay')).toBe(integrationLogo('mcap'))
    expect(integrationLogo('mcap-replay')).toMatch(/\.svg$|^data:image\/svg\+xml/)
  })
})

// SOLUSDEV-317: a single-colour dark mark (GitHub's Invertocat) is unreadable on
// a dark theme, so it carries a class the stylesheet inverts there. Coloured
// marks keep their brand colours.
describe('logoClass', () => {
  it('marks monochrome logos, case-insensitively, and nothing else', () => {
    expect(logoClass('github')).toBe('logo-mono')
    expect(logoClass('GitHub')).toBe('logo-mono')
    expect(logoClass('kicad')).toBeUndefined()
    expect(logoClass('onshape')).toBeUndefined()
    expect(logoClass('unknown')).toBeUndefined()
  })
})
