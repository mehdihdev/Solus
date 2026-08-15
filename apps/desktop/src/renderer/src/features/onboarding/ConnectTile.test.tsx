import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectTile } from './ConnectTile'
import { INTEGRATIONS } from './integrations.constants'
import type { SelectableItem } from '../../lib/api/resources'

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

  it('renders a single-select picker and reports the chosen item', async () => {
    const items: SelectableItem[] = [
      { id: 'a/one', name: 'a/one' },
      { id: 'a/two', name: 'a/two' }
    ]
    const onSelect = vi.fn()
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'busy', label: 'Choose…', selectable: items, selectionMode: 'single' }}
        onConnect={vi.fn()}
        onSelect={onSelect}
      />
    )
    await userEvent.selectOptions(screen.getByLabelText('Choose an item to track'), 'a/two')
    expect(onSelect).toHaveBeenCalledWith([items[1]])
  })

  // Multi-select is what account-level CAD connectors need. Nothing in the tile
  // knows the items are documents — the connector's selectionMode decides.
  it('renders a multi-select picker and reports every ticked item', async () => {
    const items: SelectableItem[] = [
      { id: 'docA', name: 'Rover chassis' },
      { id: 'docB', name: 'Arm' },
      { id: 'docC', name: 'Gripper' }
    ]
    const onSelect = vi.fn()
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'busy', selectable: items, selectionMode: 'multi' }}
        onConnect={vi.fn()}
        onSelect={onSelect}
      />
    )

    await userEvent.click(screen.getByLabelText('Rover chassis'))
    await userEvent.click(screen.getByLabelText('Gripper'))
    await userEvent.click(screen.getByRole('button', { name: /track 2/i }))

    expect(onSelect).toHaveBeenCalledWith([items[0], items[2]])
  })

  it('lets a multi-select picker submit an empty selection (connected but idle)', async () => {
    const onSelect = vi.fn()
    render(
      <ConnectTile
        integration={github}
        state={{
          phase: 'busy',
          selectable: [{ id: 'docA', name: 'Rover chassis' }],
          selectionMode: 'multi'
        }}
        onConnect={vi.fn()}
        onSelect={onSelect}
      />
    )

    await userEvent.click(screen.getByRole('button', { name: /track none/i }))

    expect(onSelect).toHaveBeenCalledWith([])
  })

  // The generic details form: fields come from the live registry, so a
  // connector this file has never heard of still renders a usable form.
  it('renders one input per live config field and submits the collected values', async () => {
    const onSubmitConfig = vi.fn()
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'busy', label: 'Enter…', configFields: ['document_id', 'element_id'] }}
        onConnect={vi.fn()}
        onSubmitConfig={onSubmitConfig}
      />
    )

    await userEvent.type(screen.getByLabelText('Document id'), 'd1')
    await userEvent.type(screen.getByLabelText('Element id'), 'e1')
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }))

    expect(onSubmitConfig).toHaveBeenCalledWith({ document_id: 'd1', element_id: 'e1' })
  })

  it('will not submit a partially filled details form', async () => {
    const onSubmitConfig = vi.fn()
    render(
      <ConnectTile
        integration={github}
        state={{ phase: 'busy', configFields: ['document_id', 'element_id'] }}
        onConnect={vi.fn()}
        onSubmitConfig={onSubmitConfig}
      />
    )

    await userEvent.type(screen.getByLabelText('Document id'), 'd1')
    await userEvent.click(screen.getByRole('button', { name: 'Connect' }))

    expect(onSubmitConfig).not.toHaveBeenCalled()
  })
  it('offers the connect-time grant choice with what each grant means', async () => {
    const onChooseAccess = vi.fn()
    render(
      <ConnectTile
        integration={github}
        state={{
          phase: 'busy',
          accessModes: {
            default: 'read',
            modes: [
              { id: 'read', label: 'Read only', description: 'Solus can read.', scopes: [] },
              { id: 'write', label: 'Read and edit', description: 'Solus can change.', scopes: [] }
            ]
          }
        }}
        onConnect={vi.fn()}
        onChooseAccess={onChooseAccess}
      />
    )

    expect(screen.getByText('Solus can change.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: /Read and edit/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(onChooseAccess).toHaveBeenCalledWith('write')
  })

  it('starts on the connector’s own default grant, not the widest', () => {
    render(
      <ConnectTile
        integration={github}
        state={{
          phase: 'busy',
          accessModes: {
            default: 'read',
            modes: [
              { id: 'read', label: 'Read only', description: 'Solus can read.', scopes: [] },
              { id: 'write', label: 'Read and edit', description: 'Solus can change.', scopes: [] }
            ]
          }
        }}
        onConnect={vi.fn()}
        onChooseAccess={vi.fn()}
      />
    )

    expect(screen.getByRole('radio', { name: /Read only/ })).toBeChecked()
  })
})
