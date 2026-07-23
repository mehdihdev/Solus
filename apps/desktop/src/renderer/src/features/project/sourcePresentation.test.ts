// Pure presentation helpers for connected sources (SOLUSDEV-164), shared by the
// project overview and the Sources page.
import { describe, it, expect } from 'vitest'
import { sourceStatusColor, sourceTypeLabel } from './sourcePresentation'

describe('sourceStatusColor', () => {
  it('maps healthy states to the ok token and errors to the error token', () => {
    expect(sourceStatusColor('connected')).toContain('--ok')
    expect(sourceStatusColor('error')).toContain('--err')
    expect(sourceStatusColor('syncing')).toContain('--acc')
    expect(sourceStatusColor('disconnected')).toContain('--mut')
  })
})

describe('sourceTypeLabel', () => {
  it('labels known connector types', () => {
    expect(sourceTypeLabel('github')).toMatch(/GitHub/)
    expect(sourceTypeLabel('kicad')).toMatch(/KiCad/)
  })

  it('capitalizes unknown types as a fallback', () => {
    expect(sourceTypeLabel('onshape')).toMatch(/Onshape/)
  })
})
