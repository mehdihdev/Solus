// SOLUSDEV-319 — the team unit and fixed axis range from the shared bench view.
import { describe, expect, it } from 'vitest'
import { limitedDomain, sharedUnit } from './signalUnits'

describe('sharedUnit', () => {
  it('uses the team unit when the packet unit converts to it', () => {
    expect(sharedUnit('rad', 'deg')).toBe('deg')
  })
  it('falls back to the packet unit otherwise', () => {
    expect(sharedUnit('rad', 'mA')).toBe('rad')
    expect(sharedUnit('rad', null)).toBe('rad')
    expect(sharedUnit(null, 'deg')).toBeNull()
  })
})

describe('limitedDomain', () => {
  it('uses fixed limits instead of autoscale', () => {
    expect(limitedDomain([0, 100], 'deg', { min: -1.6, max: 1.6 })).toEqual({
      vMin: -1.6,
      vMax: 1.6
    })
  })
  it('autoscales without limits', () => {
    expect(limitedDomain([-40, 50], 'deg', null)).toEqual({ vMin: -40, vMax: 50 })
  })
})
