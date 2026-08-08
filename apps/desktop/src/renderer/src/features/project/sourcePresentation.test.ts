// Pure presentation helpers for connected sources (SOLUSDEV-164), shared by the
// project overview and the Sources page.
import { describe, it, expect } from 'vitest'
import { sourceErrorText, sourceStatusColor, sourceTypeLabel } from './sourcePresentation'

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

describe('sourceErrorText', () => {
  it('returns the message of a structured API error', () => {
    expect(
      sourceErrorText({ code: 'export_format_unsupported', message: 'kicad: re-export as XML.' })
    ).toBe('kicad: re-export as XML.')
  })

  it('falls back to the code when the message is missing', () => {
    expect(sourceErrorText({ code: 'sync_failed', message: '' })).toBe('sync_failed')
  })

  it('returns null when there is no error', () => {
    expect(sourceErrorText(null)).toBeNull()
  })

  it('passes plain-string errors through unchanged', () => {
    expect(sourceErrorText('token expired' as never)).toBe('token expired')
  })

  it('never returns a non-string for malformed error payloads', () => {
    expect(sourceErrorText({} as never)).toBeNull()
  })

  it('never throws and never returns a non-string for adversarial shapes', () => {
    const adversarial = [[], [1, 2], { message: { nested: {} } }, { message: ['a'] }, 42, true]
    for (const payload of adversarial) {
      const result = sourceErrorText(payload as never)
      expect(result === null || typeof result === 'string').toBe(true)
    }
  })

  it('clamps oversized messages so a huge payload cannot degrade the UI', () => {
    const huge = sourceErrorText({ code: 'x', message: 'm'.repeat(1_000_000) })
    expect(huge).not.toBeNull()
    expect((huge as string).length).toBeLessThanOrEqual(500)
    expect(sourceErrorText('s'.repeat(10_000) as never)?.length).toBeLessThanOrEqual(500)
  })
})
