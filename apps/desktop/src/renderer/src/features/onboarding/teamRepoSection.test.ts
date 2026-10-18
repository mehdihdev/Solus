// SOLUSDEV-216: the pure model behind the GitHub wizard's two-section picker.
import { describe, it, expect } from 'vitest'
import {
  ACCOUNT_ENTRY_ID,
  SIGN_IN_ENTRY_ID,
  teamBindErrorMessage,
  teamRepoSections
} from './teamRepoSection'
import type { TeamInstallation } from '../../lib/api/resources.teamGithub'
import type { SelectableItem } from '../../lib/api/resources'

const INSTALLATION: TeamInstallation = {
  id: 'i1',
  provider: 'github',
  account_login: 'fsae-ev',
  account_type: 'Organization',
  account_avatar_url: null,
  repository_selection: 'all',
  status: 'active',
  linked_by: null,
  linked_at: '',
  html_url: 'https://github.com/fsae-ev',
  manage_url: 'https://github.com/organizations/fsae-ev/settings/installations/1'
}

const REPOS: SelectableItem[] = [
  { id: 'fsae-ev/vcu', name: 'fsae-ev/vcu', subtitle: 'private', config: { repo: 'fsae-ev/vcu' } },
  { id: 'fsae-ev/bms', name: 'fsae-ev/bms', subtitle: 'private' }
]

describe('teamRepoSections', () => {
  it('returns null with no installation so the legacy single-section wizard is kept', () => {
    expect(teamRepoSections({ installation: null, repos: REPOS, linkedLogin: 'maya-k' })).toBeNull()
  })

  it('lists the team repos under an upper-cased TEAM header', () => {
    const sections = teamRepoSections({
      installation: INSTALLATION,
      repos: REPOS,
      linkedLogin: null
    })
    expect(sections?.[0].header).toBe('FROM FSAE-EV (TEAM)')
    expect(sections?.[0].items).toEqual(REPOS)
    expect(sections?.[0].notice).toBeUndefined()
  })

  it('says so when an active installation shares no repositories', () => {
    const sections = teamRepoSections({ installation: INSTALLATION, repos: [], linkedLogin: null })
    expect(sections?.[0].items).toEqual([])
    expect(sections?.[0].notice).toMatch(/no repositories/i)
  })

  it('shows a suspended notice and no items for a suspended installation', () => {
    const sections = teamRepoSections({
      installation: { ...INSTALLATION, status: 'suspended' },
      repos: REPOS,
      linkedLogin: 'maya-k'
    })
    expect(sections?.[0].header).toBe('FROM FSAE-EV (TEAM)')
    expect(sections?.[0].notice).toBe('Suspended on GitHub')
    expect(sections?.[0].items).toEqual([])
  })

  it('offers the linked account as the second section', () => {
    const sections = teamRepoSections({
      installation: INSTALLATION,
      repos: REPOS,
      linkedLogin: 'maya-k'
    })
    expect(sections).toHaveLength(2)
    expect(sections?.[1].header).toBe('YOUR ACCOUNT · maya-k')
    expect(sections?.[1].items.map((i) => i.id)).toEqual([ACCOUNT_ENTRY_ID])
  })

  it('offers "Use my own GitHub account" when no account is linked', () => {
    const sections = teamRepoSections({
      installation: INSTALLATION,
      repos: REPOS,
      linkedLogin: null
    })
    expect(sections?.[1].header).toBe('YOUR ACCOUNT')
    expect(sections?.[1].items).toEqual([
      expect.objectContaining({ id: SIGN_IN_ENTRY_ID, name: 'Use my own GitHub account' })
    ])
  })
})

describe('teamBindErrorMessage', () => {
  const CODES = [
    'installation_missing',
    'installation_suspended',
    'repo_not_in_installation',
    'credential_conflict'
  ] as const

  it.each(CODES)('has distinct Guide and Expert copy for %s', (code) => {
    const guide = teamBindErrorMessage(code, 'Guide')
    const expert = teamBindErrorMessage(code, 'Expert')
    expect(guide).toBeTruthy()
    expect(expert).toBeTruthy()
    expect(guide).not.toBe(expert)
    expect(guide?.length).toBeGreaterThan(expert?.length ?? 0)
  })

  it('names each failure differently', () => {
    const messages = CODES.map((c) => teamBindErrorMessage(c, 'Expert'))
    expect(new Set(messages).size).toBe(CODES.length)
  })

  it('returns null for codes this bind does not own', () => {
    expect(teamBindErrorMessage('already_linked', 'Guide')).toBeNull()
  })
})
