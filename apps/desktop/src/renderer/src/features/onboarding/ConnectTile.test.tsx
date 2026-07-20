import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectTile } from './ConnectTile'
import { INTEGRATIONS } from './integrations.constants'
import type { GithubRepo } from '../../lib/api/resources'

const github = INTEGRATIONS.find((i) => i.id === 'github')!

describe('ConnectTile', () => {
  it('is clickable and calls onConnect when idle', async () => {
    const onConnect = vi.fn()
    render(<ConnectTile integration={github} onConnect={onConnect} />)
    expect(screen.getByText('Not connected')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Connect'))
    expect(onConnect).toHaveBeenCalledTimes(1)
  })

  it('shows the live busy label from the real flow', () => {
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'busy', label: 'Linking your GitHub account…' }}
        onConnect={vi.fn()}
      />
    )
    expect(screen.getByText('Linking your GitHub account…')).toBeInTheDocument()
  })

  it('falls back to plain "Connecting…" while busy with no live label yet', () => {
    render(<ConnectTile integration={github} state={{ phase: 'busy' }} onConnect={vi.fn()} />)
    expect(screen.getByText('Connecting…')).toBeInTheDocument()
  })

  it('shows the real result string on done', () => {
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'done', sourceId: 's1', result: 'Connected — 214 entities indexed' }}
        onConnect={vi.fn()}
      />
    )
    expect(screen.getByText('Connected — 214 entities indexed')).toBeInTheDocument()
  })

  it('shows plain "Connected" when done carries no result copy — never fabricated stats', () => {
    render(<ConnectTile integration={github} state={{ phase: 'done' }} onConnect={vi.fn()} />)
    expect(screen.getByText('Connected')).toBeInTheDocument()
  })

  it('shows the error and offers a retry that calls onRetry', async () => {
    const onRetry = vi.fn()
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'error', error: 'GitHub sign-in was cancelled.' }}
        onConnect={vi.fn()}
        onRetry={onRetry}
      />
    )
    expect(screen.getByText('GitHub sign-in was cancelled.')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Retry'))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('renders a repo picker and calls onChooseRepo with the chosen repo', async () => {
    const repos: GithubRepo[] = [
      { full_name: 'a/one', default_branch: 'main', private: false },
      { full_name: 'a/two', default_branch: 'dev', private: true }
    ]
    const onChooseRepo = vi.fn()
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'busy', label: 'Choose…', repos }}
        onConnect={vi.fn()}
        onChooseRepo={onChooseRepo}
      />
    )
    await userEvent.selectOptions(screen.getByLabelText('Choose a repository'), 'a/two')
    expect(onChooseRepo).toHaveBeenCalledWith(repos[1])
  })
})
