// The .solus sidebar (SOLUSDEV-250 P4): the W1 actions, the inline composer, the entry
// list and the two-step delete — the context menu's work, reachable without a modal.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as resources from '../../../lib/api/resources'
import { useAuthStore } from '../../../store/authStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useFocusStore } from '../../workspace/focusStore'
import { useSolChatStore, EMPTY_SESSION } from '../../sol/solChatStore'
import { useSolusNodes } from '../useSolusNodes'
import { SECTION_LABELS, emptySections } from '../useSolusConfig'

vi.mock('../../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/api/resources')>()
  return {
    ...actual,
    getSolus: vi.fn(),
    addSolusEntry: vi.fn(),
    updateSolusEntry: vi.fn(),
    deleteSolusEntry: vi.fn(),
    uploadArtifact: vi.fn(),
    getGraphNeighborhood: vi.fn()
  }
})

function entry(over: Partial<resources.SolusEntry>): resources.SolusEntry {
  return {
    id: 'e1',
    section: 'details',
    kind: 'text',
    author: 'user',
    text: 'Spec: 48 V bus',
    name: null,
    artifact_id: null,
    entity_id: `${over.id ?? 'e1'}-node`,
    media_type: null,
    size_bytes: null,
    created_by: 'u1',
    created_at: '',
    updated_at: '',
    ...over
  }
}
const FILE = entry({
  id: 'e2',
  kind: 'artifact',
  text: null,
  name: 'FSAE Rules 2027.pdf',
  artifact_id: 'a1',
  media_type: 'application/pdf',
  size_bytes: 1024
})
function config(details: resources.SolusEntry[] = []): resources.SolusConfig {
  return { entity_id: 'solus-1', sections: { ...emptySections(), details } }
}
const ROOT: resources.Entity = {
  id: 'solus-1',
  name: '.solus',
  type: 'solus_config',
  domain: 'project',
  source_key: ''
}
const DETAILS: resources.Entity = {
  id: 'section-details',
  name: 'Project details',
  type: 'solus_section',
  domain: 'project',
  source_key: '',
  properties: { section: 'details' }
}
const NOTE: resources.Entity = {
  id: 'e1-node',
  name: 'Note',
  type: 'solus_note',
  domain: 'project',
  source_key: ''
}
const DOC: resources.Entity = {
  ...NOTE,
  id: 'e2-node',
  name: 'FSAE Rules 2027.pdf',
  type: 'document'
}

const graphChanged = vi.fn()
function Harness({ entity }: { entity: resources.Entity }): React.JSX.Element {
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const nodes = useSolusNodes(projectId, graphChanged)
  return (
    <>
      <aside>{nodes.renderSidebar(entity)}</aside>
      {nodes.overlays}
    </>
  )
}
function link(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
  useSettingsStore.setState({ solMode: 'Guide' })
  useSolChatStore.setState({ sessions: {} })
  useAuthStore.setState({ status: 'authenticated', user: { email: 'solus@example.invalid' } })
  vi.mocked(resources.getSolus).mockResolvedValue(config([entry({}), FILE]))
  vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
    entities: [],
    edges: [],
    truncated: false
  })
})

describe('.solus root', () => {
  it('lists the five sections with honest counts and a mode-aware line', async () => {
    link()
    render(<Harness entity={ROOT} />)
    expect(await screen.findByText('2')).toBeInTheDocument()
    for (const label of Object.values(SECTION_LABELS))
      expect(screen.getByText(label)).toBeInTheDocument()
    expect(screen.getAllByText('EMPTY')).toHaveLength(4)
    expect(screen.getByText(/Zoom into a section/)).toBeInTheDocument()
    act(() => useSettingsStore.setState({ solMode: 'Expert' }))
    expect(screen.getByText('Project knowledge · zoom in to open sections.')).toBeInTheDocument()
    expect(screen.getByTestId('focused-name')).toBeInTheDocument()
  })
})

describe('a section', () => {
  it('offers the three W1 actions in order and lists selectable entries', async () => {
    link()
    render(<Harness entity={DETAILS} />)
    expect(await screen.findByRole('heading', { name: 'Project details' })).toBeInTheDocument()
    const actions = screen.getByRole('group', { name: 'Section actions' })
    expect(
      Array.from(actions.querySelectorAll('button')).map((button) => button.textContent)
    ).toEqual(['Import files…', 'Ask SOL to find…', 'Type it'])
    await userEvent.click(screen.getByRole('button', { name: 'FSAE Rules 2027.pdf' }))
    expect(useFocusStore.getState().focusedEntityId).toBe('e2-node')
  })

  it('disables Ask SOL while a turn is streaming, with the hint', async () => {
    link()
    useSolChatStore.setState({ sessions: { p1: { ...EMPTY_SESSION, streaming: true } } })
    render(<Harness entity={DETAILS} />)
    const ask = await screen.findByRole('button', { name: /Ask SOL to find/ })
    expect(ask).toBeDisabled()
    expect(screen.getByText('SOL is busy with another turn')).toBeInTheDocument()
  })

  it('Type it opens the inline composer and posts to this section', async () => {
    link()
    vi.mocked(resources.addSolusEntry).mockResolvedValue(entry({ id: 'e3' }))
    render(<Harness entity={DETAILS} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Type it' }))
    await userEvent.type(screen.getByPlaceholderText('Type it — plain text'), 'Bus is 48 V')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() =>
      expect(resources.addSolusEntry).toHaveBeenCalledWith('p1', 'details', {
        kind: 'text',
        text: 'Bus is 48 V'
      })
    )
    await waitFor(() => expect(screen.queryByRole('textbox')).not.toBeInTheDocument())
  })

  it('Import files… opens the hidden file input for this section', async () => {
    link()
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {})
    render(<Harness entity={DETAILS} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Import files…' }))
    expect(click).toHaveBeenCalledOnce()
    click.mockRestore()
  })

  it('says so when a section is empty and offers nothing offline', async () => {
    link()
    vi.mocked(resources.getSolus).mockResolvedValue(config([]))
    const view = render(<Harness entity={DETAILS} />)
    expect(await screen.findByText(/Nothing filed here yet/)).toBeInTheDocument()
    view.unmount()
    useWorkspaceStore.getState().reset()
    render(<Harness entity={DETAILS} />)
    expect(screen.queryByRole('group', { name: 'Section actions' })).not.toBeInTheDocument()
  })
})

describe('an entry', () => {
  it('shows the note, edits inline, and saves', async () => {
    link()
    vi.mocked(resources.updateSolusEntry).mockResolvedValue(entry({ text: 'new' }))
    render(<Harness entity={NOTE} />)
    expect(await screen.findByText('Spec: 48 V bus')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Edit note' }))
    const box = screen.getByDisplayValue('Spec: 48 V bus')
    await userEvent.clear(box)
    await userEvent.type(box, 'new')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(resources.updateSolusEntry).toHaveBeenCalledWith('p1', 'e1', 'new'))
  })

  it('deletes a note in two steps with the concrete line; Keep cancels', async () => {
    link()
    vi.mocked(resources.deleteSolusEntry).mockResolvedValue(undefined)
    render(<Harness entity={NOTE} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Delete note…' }))
    expect(
      screen.getByText('Delete "Spec: 48 V bus" from .solus? Its graph node and links go with it.')
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }))
    expect(screen.queryByRole('button', { name: 'Delete note' })).not.toBeInTheDocument()
    expect(resources.deleteSolusEntry).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Delete note…' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete note' }))
    await waitFor(() => expect(resources.deleteSolusEntry).toHaveBeenCalledWith('p1', 'e1'))
    await waitFor(() => expect(graphChanged).toHaveBeenCalledOnce())
  })

  it('names the stored bytes when deleting an imported file', async () => {
    link()
    vi.mocked(resources.deleteSolusEntry).mockResolvedValue(undefined)
    render(<Harness entity={DOC} />)
    expect(await screen.findByText('application/pdf · 1.0 KB')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Edit/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete file…' }))
    expect(
      screen.getByText(
        'Delete "FSAE Rules 2027.pdf" from .solus? Its graph node and stored bytes go with it.'
      )
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete file' }))
    await waitFor(() => expect(resources.deleteSolusEntry).toHaveBeenCalledWith('p1', 'e2'))
  })

  it('keeps the confirm step open when the delete fails', async () => {
    link()
    vi.mocked(resources.deleteSolusEntry).mockRejectedValue(new Error('Nope'))
    render(<Harness entity={NOTE} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Delete note…' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete note' }))
    await waitFor(() => expect(resources.deleteSolusEntry).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: 'Delete note' })).toBeEnabled()
    expect(graphChanged).not.toHaveBeenCalled()
  })
})
