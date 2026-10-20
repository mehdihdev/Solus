// SOLUSDEV-317 (from SOLUSDEV-216's roster modal): the one-time join token of a
// GitHub-id invite, shown once in a small modal that Escape / click-out never
// discard — only Done (asked twice while uncopied) closes it.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { githubText } from './githubOrgCopy'
import { GitHubInviteTokenModal } from './GitHubInviteTokenModal'

const show = (token: string | null, onDone = vi.fn()): typeof onDone => {
  render(<GitHubInviteTokenModal login="octo" token={token} onDone={onDone} />)
  return onDone
}

function denyClipboard(): void {
  const writeText = vi.fn(async () => {
    throw new Error('denied')
  })
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
}

beforeEach(() => {
  vi.resetAllMocks()
  useSettingsStore.setState({ solMode: 'Guide' })
})

describe('GitHubInviteTokenModal', () => {
  it('is a labelled dialog naming the login; the reveal is announced and focused', () => {
    show('one-time-token')
    expect(screen.getByRole('dialog', { name: /invite @octo/i })).toBeInTheDocument()
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('one-time-token')
    expect(status).toHaveFocus()
  })

  it('Escape and click-out never discard the token', async () => {
    const onDone = show('one-time-token')
    await userEvent.keyboard('{Escape}')
    expect(onDone).not.toHaveBeenCalled()
    expect(screen.getByTestId('invite-token')).toBeInTheDocument()
  })

  it('Done asks twice while the token is uncopied', async () => {
    const onDone = show('one-time-token')
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    expect(onDone).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(/won't see this token again/i)
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('Done closes at once after a copy', async () => {
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const onDone = show('one-time-token')
    await userEvent.click(screen.getByRole('button', { name: /copy token/i }))
    expect(writeText).toHaveBeenCalledWith('one-time-token')
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it.each<SolMode>(['Guide', 'Expert'])('%s: says the token was not returned', async (mode) => {
    useSettingsStore.setState({ solMode: mode })
    show(null)
    expect(screen.getByTestId('invite-token')).toHaveTextContent(
      githubText('roster_token_missing', mode)
    )
  })

  it('names a copy failure in Expert', async () => {
    useSettingsStore.setState({ solMode: 'Expert' })
    denyClipboard()
    show('one-time-token')
    await userEvent.click(screen.getByRole('button', { name: /copy token/i }))
    expect(await screen.findByText(githubText('roster_copy_failed', 'Expert'))).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^done$/i }))
    expect(screen.getByText(githubText('roster_wont_see_again', 'Expert'))).toBeInTheDocument()
  })

  it('renders a hostile login as text', () => {
    const { container } = render(
      <GitHubInviteTokenModal login="<img src=x onerror=alert(1)>" token="t" onDone={vi.fn()} />
    )
    expect(container.querySelector('img[onerror]')).toBeNull()
  })
})
