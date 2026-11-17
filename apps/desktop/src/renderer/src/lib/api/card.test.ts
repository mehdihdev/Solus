// SOLUSDEV-326: the card helpers the Hardware slot and the SOL thread share.
import { describe, expect, it } from 'vitest'
import { QUESTION_TOOL, fieldEdit, splitChips } from './card'

describe('splitChips', () => {
  it('puts the insides of backtick pairs at the odd places', () => {
    expect(splitChips('Run `ssh-copy-id pi` once, then `exit`.')).toEqual([
      'Run ',
      'ssh-copy-id pi',
      ' once, then ',
      'exit',
      '.'
    ])
  })

  it('leaves a lone backtick, and text with none, as one piece of text', () => {
    expect(splitChips('a ` b')).toEqual(['a ` b'])
    expect(splitChips('plain')).toEqual(['plain'])
  })
})

describe('fieldEdit', () => {
  const field = { label: 'Robot name', value: 'Rover arm' }

  it('is what the person typed over the field, trimmed', () => {
    expect(fieldEdit(field, '  Arm B ')).toBe('Arm B')
  })

  it('is null when the value stands, is emptied, or the card has no field', () => {
    expect(fieldEdit(field, ' Rover arm ')).toBeNull()
    expect(fieldEdit(field, '   ')).toBeNull()
    expect(fieldEdit(null, 'Arm B')).toBeNull()
  })
})

it('names the one tool whose row is a question', () => {
  expect(QUESTION_TOOL).toBe('ask_user')
})
