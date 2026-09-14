// Editing what a connected source tracks. The requirement this pins: the
// selection made at connect time stays changeable, and changing it re-syncs so
// the graph follows.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EditSelectionModal } from './EditSelectionModal'
import * as resources from '../../lib/api/resources'
import type { IntegrationSelection, SelectableItem } from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    listSelectable: vi.fn(),
    updateSource: vi.fn(),
    triggerSync: vi.fn()
  }
})

const DOCS: SelectableItem[] = [
  { id: 'docA', name: 'Rover chassis' },
  { id: 'docB', name: 'Arm' }
]
const MULTI: IntegrationSelection = { mode: 'multi', config_key: 'documents', label: 'document' }

function renderModal(current: string[] = [], onSaved = vi.fn(), onClose = vi.fn()): void {
  render(
    <EditSelectionModal
      projectId="p1"
      sourceId="s1"
      sourceName="Onshape"
      selection={MULTI}
      current={current}
      onClose={onClose}
      onSaved={onSaved}
    />
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(resources.listSelectable).mockResolvedValue(DOCS)
  vi.mocked(resources.updateSource).mockResolvedValue({} as never)
  vi.mocked(resources.triggerSync).mockResolvedValue({ job_id: 'j1', status: 'queued' })
})

describe('EditSelectionModal', () => {
  it('lists what the source can track and pre-ticks the current selection', async () => {
    renderModal(['docB'])

    await waitFor(() => expect(screen.getByLabelText('Arm')).toBeChecked())
    expect(screen.getByLabelText('Rover chassis')).not.toBeChecked()
  })

  it('saves the new selection under the connector’s config key and re-syncs', async () => {
    const onSaved = vi.fn()
    renderModal([], onSaved)
    await waitFor(() => expect(screen.getByLabelText('Rover chassis')).toBeInTheDocument())

    await userEvent.click(screen.getByLabelText('Rover chassis'))
    await userEvent.click(screen.getByRole('button', { name: /track 1/i }))

    await waitFor(() =>
      expect(resources.updateSource).toHaveBeenCalledWith('p1', 's1', {
        config: { documents: ['docA'] }
      })
    )
    // Re-sync so newly tracked items are ingested and dropped ones reconciled.
    expect(resources.triggerSync).toHaveBeenCalledWith('p1', 's1')
    expect(onSaved).toHaveBeenCalled()
  })

  it('can clear the selection entirely — connected, tracking nothing', async () => {
    renderModal(['docA', 'docB'])
    await waitFor(() => expect(screen.getByLabelText('Arm')).toBeChecked())

    await userEvent.click(screen.getByLabelText('Rover chassis'))
    await userEvent.click(screen.getByLabelText('Arm'))
    await userEvent.click(screen.getByRole('button', { name: /track none/i }))

    await waitFor(() =>
      expect(resources.updateSource).toHaveBeenCalledWith('p1', 's1', {
        config: { documents: [] }
      })
    )
  })

  it('reports an honest error when the account cannot be listed', async () => {
    vi.mocked(resources.listSelectable).mockRejectedValue(new Error('401'))
    renderModal()

    expect(await screen.findByText(/Couldn't reach Onshape/i)).toBeInTheDocument()
    expect(resources.updateSource).not.toHaveBeenCalled()
  })

  it('does not save when the save call fails', async () => {
    vi.mocked(resources.updateSource).mockRejectedValue(new Error('500'))
    const onSaved = vi.fn()
    renderModal([], onSaved)
    await waitFor(() => expect(screen.getByLabelText('Arm')).toBeInTheDocument())

    await userEvent.click(screen.getByLabelText('Arm'))
    await userEvent.click(screen.getByRole('button', { name: /track 1/i }))

    expect(await screen.findByText(/Could not save the selection/i)).toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
  })
})

it('explicitly refreshes the scoped source without saving or syncing', async () => {
  const fresh = { id: 'saved', name: 'FeatureScript MCP Workspace' }
  vi.mocked(resources.listSelectable)
    .mockResolvedValueOnce(DOCS)
    .mockResolvedValueOnce([...DOCS, fresh])
  renderModal(['docB'])
  await screen.findByLabelText('Arm')
  await userEvent.click(screen.getByRole('button', { name: /refresh/i }))
  expect(await screen.findByLabelText(fresh.name)).toBeInTheDocument()
  expect(resources.listSelectable).toHaveBeenLastCalledWith('p1', 's1', undefined, {
    refresh: true
  })
  expect(screen.getByLabelText('Arm')).toBeChecked()
  expect(resources.updateSource).not.toHaveBeenCalled()
  expect(resources.triggerSync).not.toHaveBeenCalled()
})
