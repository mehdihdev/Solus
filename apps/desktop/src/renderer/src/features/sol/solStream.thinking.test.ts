// SOLUSDEV-326: the `thinking` frame — model text the server masked and bounded, bounded again.
import { describe, expect, it } from 'vitest'
import { createSolStreamParser } from './solStream'

const frame = (data: unknown): string => `event: thinking\ndata: ${JSON.stringify(data)}\n\n`

describe('solStream — thinking frames', () => {
  it('decodes a thought piece', () => {
    expect(createSolStreamParser().push(frame({ text: 'Check the I2C bus.' }))).toEqual([
      { type: 'thinking', text: 'Check the I2C bus.' }
    ])
  })

  it.each([
    ['a missing text', {}],
    ['a non-string text', { text: 42 }],
    ['an empty text', { text: '' }],
    ['a text past the server’s chunk cap', { text: 'x'.repeat(2_001) }]
  ])('drops %s', (_label, data) => {
    expect(createSolStreamParser().push(frame(data))).toEqual([])
  })
})
