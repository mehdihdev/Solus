import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../../lib/api/client'
import type { Connection, Source } from '../../lib/api/resources'
import { AddDocumentsPane } from './AddDocumentsPane'
import { ServiceCatalog, type DocumentListing } from './serviceCatalog'
import type { useServiceAttachments } from './useServiceAttachments'

vi.mock('./ServiceDocumentTree', () => ({
  ServiceDocumentTree: () => <div data-testid="document-tree" />
}))

const account: Connection = {
  id: 'c1',
  provider: 'onshape',
  status: 'connected',
  account_login: 'builder',
  access: 'read',
  last_error: null,
  needs_reauth: null,
  health: 'healthy',
  projects: [],
  created_at: '',
  updated_at: ''
}
const source: Source = {
  id: 's1',
  project_id: 'p1',
  type: 'onshape',
  name: 'CAD',
  status: 'connected',
  config: { documents: ['d1'] },
  connection_id: 'c1',
  account_login: 'builder',
  last_error: null,
  last_synced_at: 't',
  created_at: '',
  updated_at: ''
}
const listing: DocumentListing = {
  status: 'ready',
  items: [
    { id: 'd1', name: 'Arm', subtitle: 'Part Studio', modified_at: '2026-10-24T00:00:00Z' },
    { id: 'd2', name: 'Gripper', subtitle: 'Assembly' }
  ],
  fetchedAt: 'now',
  error: null
}

function mount(picks: typeof listing.items = [], over: Partial<Connection> = {}) {
  const select = vi.fn()
  const onToggle = vi.fn()
  const project = {
    state: { busyId: null, sources: [source], error: null },
    session: { load: vi.fn(), select }
  } as unknown as ReturnType<typeof useServiceAttachments>
  render(
    <AddDocumentsPane
      account={{ ...account, ...over }}
      listing={listing}
      catalog={new ServiceCatalog(api)}
      project={project}
      picks={picks}
      onToggle={onToggle}
    />
  )
  return { select, onToggle }
}

describe('AddDocumentsPane', () => {
  it('names the connected login, lists documents, and marks the ones already in the graph', () => {
    const { select, onToggle } = mount()
    expect(screen.getByText('Connected as builder')).toBeInTheDocument()
    const arm = screen.getByRole('button', { name: 'Arm · In graph' })
    expect(arm).toHaveTextContent('In graph')
    expect(arm).toHaveTextContent('Part Studio')
    fireEvent.click(arm)
    expect(select).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }), listing.items[0])
    const gripper = screen.getByRole('button', { name: 'Gripper' })
    expect(gripper).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(gripper)
    expect(onToggle).toHaveBeenCalledWith(listing.items[1])
  })

  it('shows a pick as checked and filters by the search box', () => {
    mount([listing.items[1]])
    expect(screen.getByRole('button', { name: 'Gripper' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search documents' }), {
      target: { value: 'arm' }
    })
    expect(screen.queryByRole('button', { name: 'Gripper' })).toBeNull()
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search documents' }), {
      target: { value: 'zzz' }
    })
    expect(screen.getByText('No documents match “zzz”')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh documents' })).toBeInTheDocument()
  })

  it('hands tree-shaped providers to the document tree', () => {
    mount([], { document_tree: true })
    expect(screen.getByTestId('document-tree')).toBeInTheDocument()
    expect(screen.queryByRole('searchbox')).toBeNull()
  })
})
