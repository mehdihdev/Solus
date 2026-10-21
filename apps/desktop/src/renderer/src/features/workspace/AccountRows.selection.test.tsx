// The source row's way back into the picker: "Edit documents" opens the edit
// modal on what the source tracks now, and a save is acknowledged on the row.
import { describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SourceItem } from './AccountRows'
import type { Source } from '../../lib/api/resources'
import type { CatalogEntry } from '../onboarding/integrationCatalog'

vi.mock('../project/EditSelectionModal', () => ({
  EditSelectionModal: (props: {
    current: readonly string[]
    onSaved: (change: { added: number; removed: number }) => void
    onClose: () => void
  }) => (
    <div>
      <span>tracked: {props.current.join(',')}</span>
      <button
        type="button"
        onClick={() => {
          props.onSaved({ added: 1, removed: 1 })
          props.onClose()
        }}
      >
        fake save
      </button>
    </div>
  )
}))

const SOURCE: Source = {
  id: 's1',
  project_id: 'p1',
  type: 'onshape',
  name: 'Onshape',
  status: 'connected',
  config: { documents: ['d1', 'd2'] },
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: ''
}

const ENTRY: CatalogEntry = {
  id: 'onshape',
  name: 'Onshape',
  kind: 'CAD',
  mark: 'O',
  mode: 'oauth',
  configFields: [],
  selection: { mode: 'multi', config_key: 'documents', label: 'document' },
  accessModes: null,
  hosted: null
}

function show(onChanged = vi.fn()): void {
  render(
    <SourceItem
      source={SOURCE}
      entry={ENTRY}
      projectId="p1"
      onSync={vi.fn()}
      onDisconnect={vi.fn(async () => true)}
      onChanged={onChanged}
    />
  )
}

describe('source row selection action', () => {
  it('says how many are tracked and opens the editor on them', async () => {
    show()
    const edit = screen.getByRole('button', { name: 'Edit documents for Onshape' })
    expect(edit).toHaveTextContent('Edit documents · 2')
    await userEvent.click(edit)
    expect(screen.getByText('tracked: d1,d2')).toBeInTheDocument()
  })

  it('acknowledges a save on the row and refreshes the source', async () => {
    const onChanged = vi.fn()
    show(onChanged)
    await userEvent.click(screen.getByRole('button', { name: 'Edit documents for Onshape' }))
    await userEvent.click(screen.getByRole('button', { name: 'fake save' }))
    expect(screen.getByRole('status')).toHaveTextContent(
      'Selection saved · added 1, removed 1 · syncing'
    )
    expect(onChanged).toHaveBeenCalled()
  })

  it('lets the saved notice go after a few seconds', async () => {
    show()
    await userEvent.click(screen.getByRole('button', { name: 'Edit documents for Onshape' }))
    vi.useFakeTimers()
    try {
      act(() => screen.getByRole('button', { name: 'fake save' }).click())
      expect(screen.getByRole('status')).toBeInTheDocument()
      act(() => vi.advanceTimersByTime(8000))
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})
