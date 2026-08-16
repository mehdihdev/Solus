// The tile is a wizard LAUNCHER (SOLUSDEV-165): identity + live status only.
// Every in-flow input moved to ConnectWizardModal; its tests cover those.
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectTile } from './ConnectTile'
import { INTEGRATIONS } from './integrations.constants'

const github = INTEGRATIONS.find((i) => i.id === 'github')!

describe('ConnectTile', () => {
  it('is clickable and opens the wizard when idle', async () => {
    const onOpen = vi.fn()
    render(<ConnectTile integration={github} onOpen={onOpen} />)
    expect(screen.getByText('Not connected')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Connect'))
    expect(onOpen).toHaveBeenCalledTimes(1)
  })

  it('shows the live busy label from the real flow', () => {
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'busy', label: 'Linking your GitHub account…' }}
        onOpen={vi.fn()}
      />
    )
    expect(screen.getByText('Linking your GitHub account…')).toBeInTheDocument()
  })

  it('falls back to plain "Connecting…" while busy with no live label yet', () => {
    render(<ConnectTile integration={github} state={{ phase: 'busy' }} onOpen={vi.fn()} />)
    expect(screen.getByText('Connecting…')).toBeInTheDocument()
  })

  it('shows the real result string on done', () => {
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'done', sourceId: 's1', result: 'Connected — 214 entities indexed' }}
        onOpen={vi.fn()}
      />
    )
    expect(screen.getByText('Connected — 214 entities indexed')).toBeInTheDocument()
  })

  it('shows plain "Connected" when done carries no result copy — never fabricated stats', () => {
    render(<ConnectTile integration={github} state={{ phase: 'done' }} onOpen={vi.fn()} />)
    expect(screen.getByText('Connected')).toBeInTheDocument()
  })

  it('shows the honest error and reopens the wizard to retry', async () => {
    const onOpen = vi.fn()
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'error', error: 'GitHub sign-in was cancelled.' }}
        onOpen={onOpen}
      />
    )
    expect(screen.getByText('GitHub sign-in was cancelled.')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Retry'))
    expect(onOpen).toHaveBeenCalledTimes(1)
  })

  it('falls back to the letter mark when no logo asset is bundled', () => {
    render(<ConnectTile integration={github} onOpen={vi.fn()} />)
    expect(screen.getByText(github.mark)).toBeInTheDocument()
  })
})
