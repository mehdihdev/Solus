// SOLUSDEV-216 T9: every string of the GitHub organization card, in both SOL modes.
import { describe, expect, it } from 'vitest'
import { GITHUB_COPY_KEYS, githubText, refusalCopyKey } from './githubOrgCopy'

describe('githubOrgCopy', () => {
  it.each(GITHUB_COPY_KEYS)('%s has non-empty Guide and Expert variants', (key) => {
    const vars = {
      n: 2,
      m: 1,
      team: 'T',
      login: 'l',
      name: 'N',
      other: 'o',
      by: 'B',
      when: 'w',
      scope: 's'
    }
    const guide = githubText(key, 'Guide', vars)
    const expert = githubText(key, 'Expert', vars)
    expect(guide.length).toBeGreaterThan(0)
    expect(expert.length).toBeGreaterThan(0)
    expect(guide).not.toMatch(/\{\w+\}/)
    expect(expert).not.toMatch(/\{\w+\}/)
  })

  it('Guide explains more than Expert for the unlinked admin state', () => {
    expect(githubText('unlinked_admin', 'Guide').length).toBeGreaterThan(
      githubText('unlinked_admin', 'Expert').length
    )
  })

  it('fills the disconnected-source count into the unlink result', () => {
    expect(githubText('unlink_done', 'Expert', { n: 3 })).toContain('3 sources')
    expect(githubText('unlink_done', 'Guide', { n: 1 })).toContain('1 project')
  })

  it.each([
    'roster_token_missing',
    'roster_copy_failed',
    'roster_wont_see_again',
    'offline_note'
  ] as const)('%s reads differently in Guide and Expert', (key) => {
    expect(githubText(key, 'Guide')).not.toBe(githubText(key, 'Expert'))
    expect(githubText(key, 'Guide').length).toBeGreaterThan(githubText(key, 'Expert').length)
  })

  it('fills the linked-by line in both modes', () => {
    const vars = { by: 'Maya K', when: '2d ago', scope: 'all repos' }
    const guide = githubText('linked_by', 'Guide', vars)
    const expert = githubText('linked_by', 'Expert', vars)
    expect(expert).toBe('Linked by Maya K · 2d ago · all repos')
    expect(guide).toContain('Maya K')
    expect(guide).toContain('all repos')
    expect(guide).not.toBe(expert)
    expect(guide).not.toMatch(/[{}]/)
  })

  it('never re-expands a placeholder that arrives inside a value', () => {
    const out = githubText('linked_by', 'Expert', { by: '{when}', when: 'now', scope: 's' })
    expect(out).toBe('Linked by {when} · now · s')
  })

  it('leaves unknown placeholders alone and ignores unused vars', () => {
    expect(githubText('unlink_done', 'Expert', { n: 2, extra: 'x' })).toContain('2 sources')
  })

  it('names the organization-linked-elsewhere refusal', () => {
    expect(githubText('installation_linked_elsewhere', 'Expert')).toMatch(/another Solus team/)
  })

  it('maps every documented install refusal to a copy key and unknown codes to null', () => {
    for (const code of [
      'plan_limit_reached',
      'already_linked',
      'installation_linked_elsewhere',
      'installation_not_accessible',
      'install_state_invalid'
    ] as const) {
      expect(refusalCopyKey(code)).toBe(code)
    }
    expect(refusalCopyKey('credential_conflict')).toBeNull()
  })
})

describe('githubOrgCopy — member assignment', () => {
  it('names the other login on the assignment refusals', () => {
    const vars = { name: 'Noor', other: 'noor-a' }
    expect(githubText('member_has_verified_github', 'Expert', vars)).toBe(
      'Noor already linked @noor-a.'
    )
    expect(githubText('member_already_assigned', 'Guide', vars)).toContain('@noor-a')
  })

  it('says an assignment grants no access, in both modes', () => {
    expect(githubText('assign_intro', 'Guide')).toMatch(/never gives anyone Solus access/)
    expect(githubText('assign_intro', 'Expert')).toMatch(/no access/)
  })
})
