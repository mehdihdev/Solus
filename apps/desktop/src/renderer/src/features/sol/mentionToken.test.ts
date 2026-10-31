import { describe, expect, it } from 'vitest'
import { activeMentionToken, replaceMentionToken } from './mentionToken'

describe('activeMentionToken', () => {
  it('finds the @token the caret is sitting in', () => {
    const text = 'will @cam clear the belt'
    expect(activeMentionToken(text, 9)).toEqual({ query: 'cam', start: 5, end: 9 })
  })

  it('treats a bare @ as an open token so the list can show something', () => {
    expect(activeMentionToken('@', 1)).toEqual({ query: '', start: 0, end: 1 })
  })

  it('ignores an @ inside a word, so an email address is not a mention', () => {
    expect(activeMentionToken('mail me@example.com', 19)).toBeNull()
  })

  it('closes the token once the user types a space', () => {
    // The mention was either picked or abandoned; either way the popup goes.
    expect(activeMentionToken('@cam bracket', 12)).toBeNull()
  })

  it('reads the token at the caret, not the last one in the text', () => {
    const text = '@first and @second'
    expect(activeMentionToken(text, 6)).toEqual({ query: 'first', start: 0, end: 6 })
  })

  it('ignores text after the caret', () => {
    expect(activeMentionToken('@cam clear', 4)).toEqual({ query: 'cam', start: 0, end: 4 })
  })

  it('gives up on an absurdly long token rather than searching on it', () => {
    const text = `@${'a'.repeat(200)}`
    expect(activeMentionToken(text, text.length)).toBeNull()
  })

  it('has no token when there is no @ at all', () => {
    expect(activeMentionToken('why is the IMU noisy', 20)).toBeNull()
  })
})

describe('replaceMentionToken', () => {
  it('swaps the token for the entity name and leaves a trailing space', () => {
    const text = 'will @cam clear the belt'
    const token = activeMentionToken(text, 9)!

    expect(replaceMentionToken(text, token, 'Camera Bracket')).toEqual({
      text: 'will @Camera Bracket clear the belt',
      caret: 20
    })
  })

  it('does not double a space that is already there', () => {
    const text = '@cam'
    const token = activeMentionToken(text, 4)!

    expect(replaceMentionToken(text, token, 'Camera')).toEqual({
      text: '@Camera ',
      caret: 8
    })
  })
})
