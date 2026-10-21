// SOLUSDEV-317 (design A): the one-roster Team & invites view, end to end over
// the real roster hook with the GitHub API mocked.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as gh from '../../lib/api/resources.teamGithub'
import { resetLiveRevisions } from '../../store/liveRevisionStore'
import { useSettingsStore } from '../../store/settingsStore'
import * as hook from '../workspace/useTeamGithub'
import { useGithubInviteTokenStore } from '../workspace/githubInviteTokenStore'
import {
  ADA,
  ASSIGNED,
  FREE,
  NOOR,
  SAM,
  SERVER_ASSIGNMENT,
  VERIFIED
} from '../workspace/githubOrgRoster.fixtures'
import { EMAIL_INVITE, ORG, TEAM, github, homeTeam, renderView } from './teamInvites.testkit'
import { TeamInvitesView } from './TeamInvitesView'

vi.mock('../workspace/useTeamGithub', () => ({ useTeamGithub: vi.fn() }))
vi.mock('../../lib/api/resources.teamGithub', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources.teamGithub')>()),
  listTeamGithubMembers: vi.fn(),
  assignGithubMember: vi.fn(),
  unassignGithubMember: vi.fn()
}))

const mocked = {
  list: vi.mocked(gh.listTeamGithubMembers),
  assign: vi.mocked(gh.assignGithubMember),
  unassign: vi.mocked(gh.unassignGithubMember),
  github: vi.mocked(hook.useTeamGithub)
}

const TEAM3 = [ADA, NOOR, SAM]
const row = (name: string): HTMLElement =>
  screen.getByRole('rowheader', { name: new RegExp(`^${name}`) }).closest('tr') as HTMLElement

beforeEach(() => {
  vi.resetAllMocks()
  resetLiveRevisions()
  useSettingsStore.setState({ solMode: 'Guide' })
  useGithubInviteTokenStore.setState({ reveal: null })
  mocked.github.mockReturnValue(github(ORG))
  mocked.list.mockResolvedValue({ items: [FREE, ASSIGNED, VERIFIED], total: 3, cursor: null })
})

describe('TeamInvitesView — header and table', () => {
  it('names the team, counts people, and lists everyone in one table', async () => {
    renderView({ homeTeam: homeTeam(TEAM3, [EMAIL_INVITE]) })
    expect(screen.getByRole('heading', { name: 'Strider' })).toBeInTheDocument()
    expect(
      await screen.findByText('3 members · 1 pending invite · 1 more person in strider-robotics')
    ).toBeVisible()
    expect(screen.getByRole('heading', { name: 'People, 5' })).toBeInTheDocument()
    expect(screen.getByText('dev@team.dev')).toBeInTheDocument()
    expect(screen.getByText('IN STRIDER-ROBOTICS, NOT ON THIS TEAM · 1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /invite teammate/i })).toBeInTheDocument()
  })

  it('shows each teammate’s GitHub link with its tag', async () => {
    renderView({ homeTeam: homeTeam(TEAM3) })
    await screen.findByText('IN STRIDER-ROBOTICS, NOT ON THIS TEAM · 1')
    expect(within(row('Noor')).getByText('@noor-a')).toBeInTheDocument()
    expect(within(row('Noor')).getByText('ASSIGNED')).toBeInTheDocument()
    expect(within(row('Noor')).getByText(/assigned by Ada/)).toBeInTheDocument()
    expect(within(row('Sam')).getByText('VERIFIED')).toBeInTheDocument()
    expect(within(row('Sam')).queryByRole('button', { name: /unlink/i })).toBeNull()
    expect(within(row('Ada')).getByText('No GitHub linked')).toBeInTheDocument()
  })

  it('a teammate with no name shows the email once', async () => {
    renderView({ homeTeam: homeTeam([{ ...ADA, name: null }]) })
    expect(await screen.findAllByText('ada@team.dev')).toHaveLength(1)
  })

  it('renders hostile names as text', () => {
    const { container } = renderView({
      homeTeam: homeTeam([{ ...ADA, name: '<img src=x onerror=alert(1)>' }])
    })
    expect(container.querySelector('img[onerror]')).toBeNull()
  })
})

describe('TeamInvitesView — GitHub links', () => {
  it('links a teammate from their row', async () => {
    mocked.assign.mockResolvedValue({ ...SERVER_ASSIGNMENT, user_id: 'u1', name: 'Ada' })
    renderView({ homeTeam: homeTeam(TEAM3) })
    await screen.findByText('IN STRIDER-ROBOTICS, NOT ON THIS TEAM · 1')
    await userEvent.click(within(row('Ada')).getByRole('button', { name: 'Link GitHub…' }))
    await userEvent.click(screen.getByRole('option', { name: /@octo/ }))
    expect(mocked.assign).toHaveBeenCalledWith('t1', 7, 'u1')
    await waitFor(() => expect(within(row('Ada')).getByText('@octo')).toBeInTheDocument())
  })

  it('unlinks an admin label after an inline confirm', async () => {
    mocked.unassign.mockResolvedValue(undefined)
    renderView({ homeTeam: homeTeam(TEAM3) })
    await screen.findByText('IN STRIDER-ROBOTICS, NOT ON THIS TEAM · 1')
    await userEvent.click(within(row('Noor')).getByRole('button', { name: 'Unlink @noor-a' }))
    expect(within(row('Noor')).getByRole('button', { name: 'Confirm unlink' })).toHaveFocus()
    await userEvent.click(within(row('Noor')).getByRole('button', { name: 'Confirm unlink' }))
    expect(mocked.unassign).toHaveBeenCalledWith('t1', 8)
  })

  it('links an org member to a teammate from the org row, and invites with the token once', async () => {
    const g = github(ORG)
    mocked.github.mockReturnValue(g)
    renderView({ homeTeam: homeTeam(TEAM3) })
    const octo = (await screen.findByRole('rowheader', { name: '@octo' })).closest(
      'tr'
    ) as HTMLElement
    expect(within(octo).getByText('NOT ON SOLUS')).toBeInTheDocument()
    await userEvent.click(within(octo).getByRole('button', { name: 'Invite @octo' }))
    expect(g.actions.inviteMember).toHaveBeenCalledWith(FREE)
    const dialog = await screen.findByRole('dialog', { name: 'Invite @octo' })
    expect(within(dialog).getByTestId('invite-token')).toHaveTextContent('one-time-token')
  })

  it('non-managers see links read-only and never fetch the org roster', () => {
    renderView({ homeTeam: homeTeam(TEAM3, [], { myRole: 'member' }), canManage: false })
    expect(mocked.list).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Link GitHub…' })).toBeNull()
    expect(screen.queryByRole('radio', { name: 'Not on Solus' })).toBeNull()
    expect(within(row('Noor')).getByText('@noor-a')).toBeInTheDocument()
  })

  it.each([
    ['no link', null],
    ['a suspended link', { ...ORG, status: 'suspended' as const }],
    ['a User link', { ...ORG, account_type: 'User' as const }]
  ])('no org rows for %s', (_, installation) => {
    mocked.github.mockReturnValue(github(installation))
    renderView({ homeTeam: homeTeam(TEAM3) })
    expect(mocked.list).not.toHaveBeenCalled()
  })

  it('offers no link controls until the org roster has loaded', async () => {
    mocked.list.mockImplementation(() => new Promise(() => undefined))
    renderView({ homeTeam: homeTeam(TEAM3) })
    expect(within(row('Ada')).queryByRole('button', { name: 'Link GitHub…' })).toBeNull()
    expect(within(row('Noor')).queryByRole('button', { name: /unlink/i })).toBeNull()
  })

  it('says the org count is partial while more pages exist', async () => {
    mocked.list.mockResolvedValue({ items: [FREE, ASSIGNED, VERIFIED], total: 120, cursor: 'c2' })
    renderView({ homeTeam: homeTeam(TEAM3) })
    expect(await screen.findByText('3 members · 1+ more people in strider-robotics')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'People, 4+' })).toBeInTheDocument()
  })

  it('focus moves to the People heading after this admin links the org', async () => {
    const before = github(null)
    mocked.github.mockReturnValue(before)
    const { rerender } = renderView({ homeTeam: homeTeam(TEAM3) })
    await userEvent.click(screen.getByRole('button', { name: /link organization/i }))
    mocked.github.mockReturnValue(github(ORG))
    rerender(
      <TeamInvitesView team={TEAM} homeTeam={homeTeam(TEAM3)} canManage onInvite={vi.fn()} />
    )
    await waitFor(() => expect(screen.getByRole('heading', { name: /^People, / })).toHaveFocus())
  })
})
