import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { markSafely, measureSafely } from './marks'

const fake = { mark: vi.fn(), measure: vi.fn() }

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('performance', fake)
})
afterEach(() => vi.unstubAllGlobals())

describe('marks', () => {
  it('marks and measures through the Performance API', () => {
    markSafely('hw:confirm_sent')
    measureSafely('hw:confirm_to_node', 'hw:confirm_sent', 'hw:node_visible')
    expect(fake.mark).toHaveBeenCalledWith('hw:confirm_sent')
    expect(fake.measure).toHaveBeenCalledWith(
      'hw:confirm_to_node',
      'hw:confirm_sent',
      'hw:node_visible'
    )
  })

  it('never throws — a missing start mark or a missing API is swallowed', () => {
    fake.measure.mockImplementation(() => {
      throw new SyntaxError('no such mark')
    })
    expect(() => measureSafely('m', 'a', 'b')).not.toThrow()
    vi.stubGlobal('performance', undefined)
    expect(() => markSafely('x')).not.toThrow()
    expect(() => measureSafely('m', 'a', 'b')).not.toThrow()
  })
})
