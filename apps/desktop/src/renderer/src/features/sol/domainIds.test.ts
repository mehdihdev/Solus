// The SOL page's token readers, moved out of domainDot.tsx (SOLUSDEV-321 P7 fix 1, M6) so that file
// exports components only: a graph domain and a citation connector onto the four colour tokens,
// and the surface a verified citation opens.
import { describe, expect, it } from 'vitest'
import { citationDomain, citationTarget, domainIdOf } from './domainIds'

describe('domainIds', () => {
  it('maps graph domains onto the four colour tokens, and nothing else', () => {
    expect(domainIdOf('code')).toBe('sw')
    expect(domainIdOf('electrical')).toBe('ee')
    expect(domainIdOf('mechanical')).toBe('me')
    expect(domainIdOf('runtime')).toBe('rt')
    expect(domainIdOf('simulation')).toBe('rt')
    expect(domainIdOf('project')).toBeNull()
    expect(domainIdOf('workspace')).toBeNull()
  })

  it('reads a citation connector into a domain only when it knows the connector', () => {
    expect(citationDomain('[kicad:U4]')).toBe('ee')
    expect(citationDomain('[GitHub:src/main.py]')).toBe('sw')
    expect(citationDomain('[onshape:Chassis v4]')).toBe('me')
    expect(citationDomain('[entity:0f9c2f2a]')).toBeNull()
    expect(citationDomain('[solus:documentation:e1]')).toBeNull()
    expect(citationDomain('plain text')).toBeNull()
  })

  it('names the surface a citation opens: an entity, a finding or a .solus entry, nothing else', () => {
    expect(citationTarget('[entity:0f9c2f2a-1111]')).toEqual({
      kind: 'entity',
      id: '0f9c2f2a-1111'
    })
    expect(citationTarget('[finding:f1]')).toEqual({ kind: 'finding', id: 'f1' })
    expect(citationTarget('[solus:documentation:e1]')).toEqual({
      kind: 'solus',
      section: 'documentation',
      id: 'e1'
    })
    // A .solus token names its section AND its entry; one without an entry opens nothing.
    expect(citationTarget('[solus:documentation]')).toBeNull()
    // Connectors are the server's own lower-case words; every other one is a plain chip.
    expect(citationTarget('[Finding:f1]')).toBeNull()
    expect(citationTarget('[kicad:U4]')).toBeNull()
    expect(citationTarget('entity:0f9c2f2a')).toBeNull()
    expect(citationTarget('nope')).toBeNull()
  })
})
