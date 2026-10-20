// SOLUSDEV-317 (design A): filters, search, member management and the solo
// setup state of the one-roster Team & invites view.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as gh from '../../lib/api/resources.teamGithub'
import { resetLiveRevisions } from '../../store/liveRevisionStore'
import { useSettingsStore } from '../../store/settingsStore'
import { githubText } from '../workspace/githubOrgCopy'
import * as hook from '../workspace/useTeamGithub'
import { useGithubInviteTokenStore } from '../workspace/githubInviteTokenStore'
import { ADA, ASSIGNED, FREE, NOOR, SAM, VERIFIED } from '../workspace/githubOrgRoster.fixtures'
import { EMAIL_INVITE, ORG, TEAM, github, homeTeam, renderView } from './teamInvites.testkit'
import { teamText } from './teamInvitesCopy'

vi.mock('../workspace/useTeamGithub', () => ({ useTeamGithub: vi.fn() }))
vi.mock('../../lib/api/resources.teamGithub', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources.teamGithub')>()),
  listTeamGithubMembers: vi.fn()
}))

const TEAM3 = [ADA, NOOR, SAM]
const names = (): string[] =>
  screen
    .getAllByRole('rowheader')
    .flatMap((h) => h.querySelector('[data-person]')?.textContent ?? [])

beforeEach(() => {
  vi.resetAllMocks()
  resetLiveRevisions()
  useSettingsStore.setState({ solMode: 'Guide' })
  useGithubInviteTokenStore.setState({ reveal: null })
  vi.mocked(hook.useTeamGithub).mockReturnValue(github(ORG))
  vi.mocked(gh.listTeamGithubMembers).mockResolvedValue({
    items: [FREE, ASSIGNED, VERIFIED],
    total: 3,
    cursor: null
  })
})

describe('TeamInvitesView — filters and search', () => {
  it.each([
    ['Team', ['Ada', 'Noor', 'Sam']],
    ['Invites', ['dev@team.dev']],
    ['Not on Solus', ['@octo']],
    ['No GitHub', ['Ada']]
  ])('%s', async (filter, expected) => {
    renderView({ homeTeam: homeTeam(TEAM3, [EMAIL_INVITE]) })
    await userEvent.click(await screen.findByRole('radio', { name: filter }))
    expect(names()).toEqual(expected)
  })

  it('searches names, emails and logins', async () => {
    renderView({ homeTeam: homeTeam(TEAM3, [EMAIL_INVITE]) })
    await screen.findByRole('radio', { name: 'Not on Solus' })
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search people' }), 'noor-a')
    expect(names()).toEqual(['Noor'])
  })
})

describe('TeamInvitesView — managing members', () => {
  it('changes a role and names a refusal', async () => {
    const team = homeTeam(TEAM3)
    vi.mocked(team.actions.changeRole).mockResolvedValue({ ok: false, reason: 'forbidden' })
    renderView({ homeTeam: team })
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Role for sam@team.dev' }),
      'admin'
    )
    expect(team.actions.changeRole).toHaveBeenCalledWith('u3', 'admin')
    expect(await screen.findByRole('alert')).toHaveTextContent(/permission/i)
  })

  it('removes a member and revokes an invite only after a named confirm', async () => {
    const team = homeTeam(TEAM3, [EMAIL_INVITE])
    renderView({ homeTeam: team })
    await userEvent.click(screen.getByRole('button', { name: 'Remove sam@team.dev' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(team.actions.remove).toHaveBeenCalledWith('u3')
    await userEvent.click(screen.getByRole('button', { name: 'Revoke invite for dev@team.dev' }))
    await userEvent.click(screen.getByRole('button', { name: 'Revoke' }))
    expect(team.actions.revoke).toHaveBeenCalledWith('inv1')
  })

  it('cancelling a removal calls nothing; a refused removal stays open with the reason', async () => {
    const team = homeTeam(TEAM3)
    vi.mocked(team.actions.remove).mockResolvedValue({ ok: false, reason: 'last_owner' })
    renderView({ homeTeam: team })
    await userEvent.click(screen.getByRole('button', { name: 'Remove sam@team.dev' }))
    expect(screen.getByText('sam@team.dev', { selector: 'strong' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(team.actions.remove).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Remove sam@team.dev' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(await screen.findByText(/at least one owner/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  })

  it('the owner row has no role or remove control', () => {
    renderView({ homeTeam: homeTeam(TEAM3) })
    expect(screen.queryByRole('combobox', { name: 'Role for ada@team.dev' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Remove ada@team.dev' })).toBeNull()
  })

  it('after a confirmed removal, focus lands on the People heading', async () => {
    renderView({ homeTeam: homeTeam(TEAM3) })
    await userEvent.click(screen.getByRole('button', { name: 'Remove sam@team.dev' }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(screen.getByRole('heading', { name: /^People, / })).toHaveFocus()
  })

  it('owners are never editable; viewers get the view-access note', () => {
    renderView({ homeTeam: homeTeam(TEAM3, [], { myRole: 'viewer' }), canManage: false })
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.queryByRole('button', { name: /^remove/i })).toBeNull()
    expect(screen.getByText(teamText('viewer_note', 'Guide'))).toBeInTheDocument()
  })

  it('the Invite button opens the email invite dialog', async () => {
    const { props } = renderView({ homeTeam: homeTeam(TEAM3) })
    await userEvent.click(screen.getByRole('button', { name: /invite teammate/i }))
    expect(props.onInvite).toHaveBeenCalled()
  })
})

describe('TeamInvitesView — solo team', () => {
  it('shows the two setup steps instead of the strip while nothing is linked', () => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(null))
    renderView({ homeTeam: homeTeam([ADA]) })
    expect(screen.getByText(teamText('setup_intro', 'Guide'))).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Invite a teammate' })).toBeInTheDocument()
    const card = screen.getByTestId('github-org-card')
    expect(card).toHaveAttribute('data-variant', 'step')
    expect(
      within(card).getByRole('heading', { name: /link a github organization to strider/i })
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /invite teammate/i })).toBeNull()
  })

  it('sends an email invite inline and shows the token once', async () => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(null))
    const team = homeTeam([ADA])
    renderView({ homeTeam: team })
    await userEvent.type(screen.getByRole('textbox', { name: 'Teammate email' }), 'new@team.dev')
    await userEvent.click(screen.getByRole('button', { name: 'Send invite' }))
    expect(team.actions.invite).toHaveBeenCalledWith('new@team.dev')
    const dialog = await screen.findByRole('dialog', { name: 'Invite new@team.dev' })
    expect(within(dialog).getByRole('status')).toHaveTextContent(
      githubText('invite_shown_email', 'Guide')
    )
  })

  it('rejects a bad email and names a plan limit with Upgrade', async () => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(null))
    const team = homeTeam([ADA])
    vi.mocked(team.actions.invite).mockResolvedValue({
      ok: false,
      reason: 'plan_limit',
      limit: { message: 'Plan full.' } as never
    })
    const { props } = renderView({ homeTeam: team })
    await userEvent.type(screen.getByRole('textbox', { name: 'Teammate email' }), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Send invite' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/valid email/i)
    await userEvent.type(screen.getByRole('textbox', { name: 'Teammate email' }), '@x.dev')
    await userEvent.click(screen.getByRole('button', { name: 'Send invite' }))
    await userEvent.click(await screen.findByRole('button', { name: /upgrade/i }))
    expect(props.onUpgrade).toHaveBeenCalled()
  })

  it('shows neither strip nor step 2 until the GitHub state has loaded (no flicker)', () => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(null, { status: 'loading' }))
    renderView({ homeTeam: homeTeam([ADA]) })
    expect(screen.queryByTestId('github-org-card')).toBeNull()
  })

  it('a linked solo team keeps step 1 and shows the strip', () => {
    renderView({ homeTeam: homeTeam([ADA]) })
    expect(screen.getByRole('heading', { name: 'Invite a teammate' })).toBeInTheDocument()
    expect(screen.getByTestId('github-org-card')).toHaveAttribute('data-variant', 'strip')
  })

  it('the personal team has no steps and no GitHub strip', () => {
    vi.mocked(hook.useTeamGithub).mockReturnValue(github(null, { status: 'idle' }))
    renderView({ homeTeam: homeTeam([ADA]), team: { ...TEAM, is_personal: true } })
    expect(hook.useTeamGithub).toHaveBeenCalledWith(null)
    expect(screen.queryByTestId('github-org-card')).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Invite a teammate' })).toBeNull()
  })
})
