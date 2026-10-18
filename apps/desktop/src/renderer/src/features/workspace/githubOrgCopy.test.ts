// SOLUSDEV-216 T9: every string of the GitHub organization card, in both SOL modes.
import { describe, expect, it } from 'vitest'
import { GITHUB_COPY_KEYS, githubText, refusalCopyKey } from './githubOrgCopy'

describe('githubOrgCopy', () => {
  it.each(GITHUB_COPY_KEYS)('%s has non-empty Guide and Expert variants', (key) => {
    const guide = githubText(key, 'Guide', { n: 2 })
    const expert = githubText(key, 'Expert', { n: 2 })
    expect(guide.length).toBeGreaterThan(0)
    expect(expert.length).toBeGreaterThan(0)
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
