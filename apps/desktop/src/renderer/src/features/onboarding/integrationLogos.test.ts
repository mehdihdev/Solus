import { describe, it, expect } from 'vitest'
import { integrationLogo, logoMapFrom } from './integrationLogos'

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
})
