// SOLUSDEV-317: every Team & invites sentence has both SOL-mode variants.
import { describe, expect, it } from 'vitest'
import { TEAM_INVITES_COPY_KEYS, teamText } from './teamInvitesCopy'

describe('teamInvitesCopy', () => {
  it.each(TEAM_INVITES_COPY_KEYS)('%s: Guide explains more than Expert', (key) => {
    expect(teamText(key, 'Expert').length).toBeGreaterThan(0)
    expect(teamText(key, 'Guide').length).toBeGreaterThan(teamText(key, 'Expert').length)
  })
})
