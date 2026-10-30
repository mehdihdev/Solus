import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { citationDomain, citationEntityId, DomainDot, domainIdOf } from './domainDot'

describe('domainDot', () => {
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

  it('exposes the entity id only for entity citations', () => {
    expect(citationEntityId('[entity:0f9c2f2a-1111]')).toBe('0f9c2f2a-1111')
    expect(citationEntityId('[kicad:U4]')).toBeNull()
    expect(citationEntityId('nope')).toBeNull()
  })

  it('renders no dot without a domain', () => {
    const { container, rerender } = render(<DomainDot d={null} />)
    expect(container.firstChild).toBeNull()
    rerender(<DomainDot d="ee" />)
    expect(container.firstElementChild).toHaveStyle({ background: 'var(--ee)' })
  })
})
