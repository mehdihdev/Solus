// SOLUSDEV-317: the one-time token outlives the section that created it — only
// Done discards it (a team switch, a demotion or a suspension must not).
import { beforeEach, describe, expect, it } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useSettingsStore } from '../../store/settingsStore'
import { GitHubInviteTokenHost, useGithubInviteTokenStore } from './githubInviteTokenStore'

beforeEach(() => {
  useGithubInviteTokenStore.setState({ reveal: null })
  useSettingsStore.setState({ solMode: 'Guide' })
})

describe('GitHubInviteTokenHost', () => {
  it('shows nothing until a token is revealed, then only Done clears it', async () => {
    render(<GitHubInviteTokenHost />)
    expect(screen.queryByRole('dialog')).toBeNull()
    act(() => useGithubInviteTokenStore.getState().show({ login: 'octo', token: 'tok' }))
    expect(screen.getByTestId('invite-token')).toHaveTextContent('tok')
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(useGithubInviteTokenStore.getState().reveal).toBeNull()
  })
})
