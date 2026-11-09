// SOLUSDEV-323: the Project step's "worlds I'm hearing" heuristic and the
// domain each connector belongs to (docs/wireflows/onboarding.md §Steps 2, 5).
import { describe, it, expect } from 'vitest'
import {
  DOMAINS,
  domainForIntegration,
  hearDomains,
  heardCount,
  suggestedIntegrations
} from './domainHearing'

describe('hearDomains', () => {
  it('hears nothing in an empty description', () => {
    expect(hearDomains('')).toEqual({ sw: false, ee: false, me: false, rt: false })
  })

  it('hears every world in a full-stack robot sentence', () => {
    const heard = hearDomains(
      'A 12-DOF quadruped. STM32 firmware, custom BLDC drivers, Onshape chassis, ROS 2 on a Jetson.'
    )
    expect(heard).toEqual({ sw: true, ee: true, me: true, rt: true })
    expect(heardCount(heard)).toBe(4)
  })

  it('is case-insensitive and matches whole words only', () => {
    expect(hearDomains('KICAD board').ee).toBe(true)
    // "arm" inside "pharmacy" is not a mechanical arm.
    expect(hearDomains('a pharmacy kiosk').me).toBe(false)
  })

  it('hears a single domain without inventing others', () => {
    expect(hearDomains('A KiCad schematic for a battery board')).toEqual({
      sw: false,
      ee: true,
      me: false,
      rt: false
    })
  })
})

describe('domainForIntegration', () => {
  it('maps known connectors to their world', () => {
    expect(domainForIntegration('github')).toBe('sw')
    expect(domainForIntegration('gitlab')).toBe('sw')
    expect(domainForIntegration('kicad')).toBe('ee')
    expect(domainForIntegration('altium')).toBe('ee')
    expect(domainForIntegration('onshape')).toBe('me')
    expect(domainForIntegration('ros')).toBe('rt')
  })

  it('returns null for a connector it has no world for', () => {
    expect(domainForIntegration('mystery')).toBeNull()
  })
})

describe('suggestedIntegrations', () => {
  it('suggests the catalog entries whose world was heard, in catalog order', () => {
    const heard = hearDomains('firmware on a custom PCB')
    expect(suggestedIntegrations(['kicad', 'onshape', 'github', 'gitlab'], heard)).toEqual([
      'kicad',
      'github'
    ])
  })

  it('suggests one connector per world so the line stays short', () => {
    const heard = hearDomains('firmware')
    expect(suggestedIntegrations(['github', 'gitlab'], heard)).toEqual(['github'])
  })

  it('suggests nothing when nothing was heard', () => {
    expect(suggestedIntegrations(['github'], hearDomains(''))).toEqual([])
  })
})

it('lists the four worlds in the house order with their tokens', () => {
  expect(DOMAINS.map((d) => [d.key, d.color])).toEqual([
    ['sw', 'var(--sw)'],
    ['ee', 'var(--ee)'],
    ['me', 'var(--me)'],
    ['rt', 'var(--rt)']
  ])
})
