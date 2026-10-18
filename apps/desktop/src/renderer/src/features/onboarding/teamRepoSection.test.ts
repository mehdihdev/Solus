// SOLUSDEV-216: the pure model behind the GitHub wizard's two-section picker.
import { describe, it, expect } from 'vitest'
import {
  ACCOUNT_ENTRY_ID,
  SIGN_IN_ENTRY_ID,
  PICKER_COPY_KEYS,
  pickerText,
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
    expect(
      teamRepoSections({ installation: null, repos: REPOS, linkedLogin: 'maya-k', mode: 'Guide' })
    ).toBeNull()
  })

  it('lists the team repos under an natural-case team header (CSS uppercases it)', () => {
    const sections = teamRepoSections({
      installation: INSTALLATION,
      repos: REPOS,
      linkedLogin: null,
      mode: 'Guide'
    })
    expect(sections?.[0].header).toBe('From fsae-ev (team)')
    expect(sections?.[0].items).toEqual(REPOS)
    expect(sections?.[0].notice).toBeUndefined()
  })

  it('says so when an active installation shares no repositories', () => {
    const sections = teamRepoSections({
      installation: INSTALLATION,
      repos: [],
      linkedLogin: null,
      mode: 'Guide'
    })
    expect(sections?.[0].items).toEqual([])
    expect(sections?.[0].notice).toMatch(/no repositories/i)
  })

  it('shows a suspended notice and no items for a suspended installation', () => {
    const sections = teamRepoSections({
      installation: { ...INSTALLATION, status: 'suspended' },
      repos: REPOS,
      linkedLogin: 'maya-k',
      mode: 'Guide'
    })
    expect(sections?.[0].header).toBe('From fsae-ev (team)')
    expect(sections?.[0].notice).toBe(pickerText('suspended', 'Guide'))
    expect(sections?.[0].items).toEqual([])
  })

  it('offers the linked account as the second section', () => {
    const sections = teamRepoSections({
      installation: INSTALLATION,
      repos: REPOS,
      linkedLogin: 'maya-k',
      mode: 'Guide'
    })
    expect(sections).toHaveLength(2)
    expect(sections?.[1].header).toBe('Your account · maya-k')
    expect(sections?.[1].items.map((i) => i.id)).toEqual([ACCOUNT_ENTRY_ID])
  })

  it('offers "Use my own GitHub account" when no account is linked', () => {
    const sections = teamRepoSections({
      installation: INSTALLATION,
      repos: REPOS,
      linkedLogin: null,
      mode: 'Guide'
    })
    expect(sections?.[1].header).toBe('Your account')
    expect(sections?.[1].items).toEqual([
      expect.objectContaining({ id: SIGN_IN_ENTRY_ID, name: 'Use my own GitHub account' })
    ])
  })
})

describe('team picker copy (SOL modes)', () => {
  it.each(PICKER_COPY_KEYS)('%s has non-empty Guide and Expert variants', (key) => {
    expect(pickerText(key, 'Guide').length).toBeGreaterThan(0)
    expect(pickerText(key, 'Expert').length).toBeGreaterThan(0)
  })

  it.each(PICKER_COPY_KEYS.filter((k) => k !== 'use_own_account'))(
    '%s explains more in Guide than Expert',
    (key) => {
      expect(pickerText(key, 'Guide').length).toBeGreaterThan(pickerText(key, 'Expert').length)
    }
  )

  it('renders the notices and sign-in entry in the requested mode', () => {
    const expert = teamRepoSections({
      installation: { ...INSTALLATION, status: 'suspended' },
      repos: [],
      linkedLogin: null,
      mode: 'Expert'
    })
    expect(expert?.[0].notice).toBe(pickerText('suspended', 'Expert'))
    expect(expert?.[1].items[0].name).toBe(pickerText('use_own_account', 'Expert'))
    const empty = teamRepoSections({
      installation: INSTALLATION,
      repos: [],
      linkedLogin: null,
      mode: 'Expert'
    })
    expect(empty?.[0].notice).toBe(pickerText('no_team_repos', 'Expert'))
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

  it('does not treat inherited object keys as bind codes', () => {
    for (const key of ['constructor', 'toString', '__proto__', 'hasOwnProperty']) {
      expect(teamBindErrorMessage(key as never, 'Guide')).toBeNull()
    }
  })
})
