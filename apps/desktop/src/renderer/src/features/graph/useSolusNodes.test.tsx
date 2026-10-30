import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as resources from '../../lib/api/resources'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useShellStore } from '../workspace/shellStore'
import { useFocusStore } from '../workspace/focusStore'
import { useSolChatStore } from '../sol/solChatStore'
import * as chat from '../sol/solChatStore'
import { useSolusNodes } from './useSolusNodes'
import { askSolMessage, sectionCountLabel, formatSize } from './solusActions'
import { SECTION_LABELS } from './useSolusConfig'
import { emptySections } from './useSolusConfig'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
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

vi.mock('../sol/solChatStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../sol/solChatStore')>()
  return { ...actual, startNewChat: vi.fn(), sendMessage: vi.fn() }
})

function entry(over: Partial<resources.SolusEntry>): resources.SolusEntry {
  return {
    id: 'e1',
    section: 'goals',
    subsection: null,
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

function config(goals: resources.SolusEntry[] = []): resources.SolusConfig {
  return { entity_id: 'solus-1', sections: { ...emptySections(), goals } }
}

/** One persisted subsection node, as the API's graph would carry it. */
const GUIDES: resources.Entity = {
  id: 'subsection-documentation-guides',
  name: 'Documentation › guides',
  type: 'solus_subsection',
  domain: 'project',
  source_key: '',
  properties: { section: 'documentation', subsection: 'guides' }
}

const graphChanged = vi.fn()
function SolusNodesHarness(): React.JSX.Element {
  const projectId = useWorkspaceStore((s) => s.project?.id ?? null)
  const nodes = useSolusNodes(projectId, graphChanged)
  const focusedId = useFocusStore((s) => s.focusedEntityId)
  const entities: resources.Entity[] = resources.SOLUS_SECTIONS.flatMap((section) => [
    {
      id: `section-${section}`,
      name: SECTION_LABELS[section],
      type: 'solus_section',
      domain: 'project',
      source_key: '',
      properties: { section }
    },
    ...(section === 'documentation' ? [GUIDES] : []),
    ...nodes.state.sections[section].map((item) => ({
      id: item.entity_id!,
      name: item.name ?? 'Note',
      type: item.kind === 'artifact' ? 'document' : 'solus_note',
      domain: 'project',
      source_key: ''
    }))
  ])
  return (
    <>
      {entities.map((entity) => (
        <article key={entity.id} onContextMenu={(event) => nodes.onContextMenu(event, entity)}>
          <h2>{entity.name}</h2>
          {nodes.renderContent(entity)}
        </article>
      ))}
      <aside>
        {entities
          .filter((entity) => entity.id === focusedId)
          .map((entity) => nodes.renderSidebar(entity))}
      </aside>
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
  useShellStore.getState().reset()
  useFocusStore.getState().reset()
  useSolChatStore.setState({ sessions: {} })
  vi.mocked(resources.getSolus).mockResolvedValue(config())
  vi.mocked(resources.getGraphNeighborhood).mockResolvedValue({
    entities: [],
    edges: [],
    truncated: false
  })
})

describe('pure helpers', () => {
  it('labels counts honestly and formats the SOL query', () => {
    expect(sectionCountLabel(0)).toBe('EMPTY')
    expect(sectionCountLabel(3)).toBe('3')
    expect(askSolMessage('Goals', '  fusing rules ')).toBe('Find for .solus › Goals: fusing rules')
    expect(formatSize(null)).toBe('')
    expect(formatSize(2748812)).toBe('2.6 MB')
  })
})

describe('SolusNodesHarness — rendering and writes', () => {
  it('shows seven EMPTY sections and no invented entries', async () => {
    link()
    render(<SolusNodesHarness />)
    for (const label of [
      'Goals',
      'Constraints',
      'Documentation',
      'Error logging',
      'Environment',
      'Members',
      'History'
    ]) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
    // Six empty sections (history renders the activity view, never EMPTY) plus the one
    // subsection node in the harness.
    expect(screen.getAllByText('EMPTY')).toHaveLength(7)
    expect(screen.getByText('AUTO + YOU')).toBeInTheDocument()
  })

  it('renders entries by kind', async () => {
    link()
    vi.mocked(resources.getSolus).mockResolvedValue(
      config([
        entry({}),
        entry({
          id: 'e2',
          kind: 'artifact',
          text: null,
          name: 'FSAE Rules 2027.pdf',
          artifact_id: 'a1',
          entity_id: 'd1',
          media_type: 'application/pdf',
          size_bytes: 1024
        }),
        entry({ id: 'e3', kind: 'sol', author: 'sol', text: 'SOL found: EV.7.2' })
      ])
    )
    render(<SolusNodesHarness />)
    expect(await screen.findByText('Spec: 48 V bus')).toBeInTheDocument()
    expect(screen.getByText('FSAE Rules 2027.pdf')).toBeInTheDocument()
    expect(screen.getByText('application/pdf · 1.0 KB')).toBeInTheDocument()
    expect(screen.getByText('SOL found: EV.7.2')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('offers the same three actions on every section', async () => {
    link()
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Environment'))
    expect(screen.getByText('ENVIRONMENT')).toBeInTheDocument()
    const items = screen.getAllByRole('menuitem').map((el) => el.textContent)
    expect(items).toEqual(['Import files…', 'Ask SOL to find…', 'Type it'])
  })

  it('a subsection node opens the same menu and files into its subsection', async () => {
    link()
    vi.mocked(resources.addSolusEntry).mockResolvedValue(
      entry({ section: 'documentation', subsection: 'guides' })
    )
    vi.mocked(resources.uploadArtifact).mockResolvedValue({
      artifact_id: 'a1',
      uri: '/x',
      media_type: 'application/pdf',
      storage: 'local',
      size_bytes: 12,
      summary: null
    })
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Documentation › guides'))
    expect(screen.getByText('DOCUMENTATION › GUIDES')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('menuitem', { name: 'Type it' }))
    expect(screen.getByRole('combobox', { name: 'Subsection' })).toHaveValue('guides')
    await userEvent.type(screen.getByPlaceholderText('Type it — plain text'), 'Crimp guide')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() =>
      expect(vi.mocked(resources.addSolusEntry)).toHaveBeenCalledWith('p1', 'documentation', {
        kind: 'text',
        text: 'Crimp guide',
        subsection: 'guides'
      })
    )
    fireEvent.contextMenu(await screen.findByText('Documentation › guides'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Import files…' }))
    await userEvent.upload(
      screen.getByLabelText('Import a file into .solus'),
      new File(['%PDF'], 'crimp.pdf', { type: 'application/pdf' })
    )
    await waitFor(() =>
      expect(vi.mocked(resources.addSolusEntry)).toHaveBeenLastCalledWith('p1', 'documentation', {
        kind: 'artifact',
        artifact_id: 'a1',
        name: 'crimp.pdf',
        subsection: 'guides'
      })
    )
  })

  it('offers a subsection picker on a fixed-list section, defaulting to its first value', async () => {
    link()
    vi.mocked(resources.addSolusEntry).mockResolvedValue(entry({ section: 'constraints' }))
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Constraints'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Type it' }))
    const picker = screen.getByRole('combobox', { name: 'Subsection' })
    expect(picker).toHaveValue('rules')
    await userEvent.selectOptions(picker, 'budgets')
    await userEvent.type(screen.getByPlaceholderText('Type it — plain text'), '40 A fuse max')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() =>
      expect(vi.mocked(resources.addSolusEntry)).toHaveBeenCalledWith('p1', 'constraints', {
        kind: 'text',
        text: '40 A fuse max',
        subsection: 'budgets'
      })
    )
  })
})

describe('SolusNodesHarness — type and import', () => {
  it('Type it posts a text entry and refetches', async () => {
    link()
    vi.mocked(resources.addSolusEntry).mockResolvedValue(entry({}))
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Goals'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Type it' }))
    const box = screen.getByPlaceholderText('Type it — plain text')
    await userEvent.type(box, 'Spec: 48 V bus')
    vi.mocked(resources.getSolus).mockResolvedValue(config([entry({})]))
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() =>
      expect(vi.mocked(resources.addSolusEntry)).toHaveBeenCalledWith('p1', 'goals', {
        kind: 'text',
        text: 'Spec: 48 V bus'
      })
    )
    expect(await screen.findByText('Spec: 48 V bus')).toBeInTheDocument()
    expect(vi.mocked(resources.getSolus)).toHaveBeenCalledTimes(2)
  })

  it('Import files uploads then files the artifact into the section', async () => {
    link()
    vi.mocked(resources.uploadArtifact).mockResolvedValue({
      artifact_id: 'a1',
      uri: '/x',
      media_type: 'application/pdf',
      storage: 'local',
      size_bytes: 12,
      summary: null
    })
    vi.mocked(resources.addSolusEntry).mockResolvedValue(entry({ kind: 'artifact' }))
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Goals'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Import files…' }))
    const input = screen.getByLabelText('Import a file into .solus') as HTMLInputElement
    const file = new File(['%PDF'], 'rules.pdf', { type: 'application/pdf' })
    await userEvent.upload(input, file)
    await waitFor(() =>
      expect(vi.mocked(resources.addSolusEntry)).toHaveBeenCalledWith('p1', 'goals', {
        kind: 'artifact',
        artifact_id: 'a1',
        name: 'rules.pdf'
      })
    )
    expect(vi.mocked(resources.uploadArtifact)).toHaveBeenCalledWith('p1', file)
  })

  it('Import files refuses an oversized file before uploading', async () => {
    link()
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Documentation'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Import files…' }))
    const input = screen.getByLabelText('Import a file into .solus') as HTMLInputElement
    const big = new File(['x'], 'huge.step', { type: 'model/step' })
    Object.defineProperty(big, 'size', { value: resources.ARTIFACT_MAX_BYTES + 1 })
    await userEvent.upload(input, big)
    await waitFor(() => expect(useShellStore.getState().toast?.title).toBe('File too large'))
    expect(vi.mocked(resources.uploadArtifact)).not.toHaveBeenCalled()
  })
})

describe('SolusNodesHarness — SOL and editing', () => {
  it('Ask SOL sends a turn through the chat store and reports what was filed', async () => {
    link()
    vi.mocked(chat.sendMessage).mockResolvedValue(true)
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Documentation'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Ask SOL to find…' }))
    await userEvent.type(
      screen.getByPlaceholderText("What should SOL find? e.g. 'FSAE EV rules on fusing'"),
      'fusing rules'
    )
    vi.mocked(resources.getSolus).mockResolvedValue({
      entity_id: 'solus-1',
      sections: {
        ...emptySections(),
        documentation: [
          entry({ id: 'e9', section: 'documentation', kind: 'sol', author: 'sol', text: 'EV.7.2' })
        ]
      }
    })
    // Documentation has fixed subsections, so the ask names the picked one (first by default)
    // and SOL files there with add_solus_entry.
    expect(screen.getByRole('combobox', { name: 'Subsection' })).toHaveValue('datasheets')
    await userEvent.click(screen.getByRole('button', { name: 'Ask SOL' }))
    await waitFor(() =>
      expect(vi.mocked(chat.sendMessage)).toHaveBeenCalledWith(
        'p1',
        'Find for .solus › Documentation › datasheets: fusing rules',
        'do'
      )
    )
    expect(vi.mocked(chat.startNewChat)).toHaveBeenCalledWith('p1')
    await waitFor(() =>
      expect(useShellStore.getState().toast?.title).toBe(
        'Filed to .solus › Documentation › datasheets'
      )
    )
  })

  it('Ask SOL says so when SOL filed nothing', async () => {
    link()
    vi.mocked(chat.sendMessage).mockResolvedValue(true)
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Documentation'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Ask SOL to find…' }))
    await userEvent.type(screen.getByPlaceholderText(/What should SOL find/), 'nothing')
    await userEvent.click(screen.getByRole('button', { name: 'Ask SOL' }))
    await waitFor(() =>
      expect(useShellStore.getState().toast?.title).toBe('SOL answered but filed nothing')
    )
  })

  it('disables Ask SOL while a turn is already streaming', async () => {
    link()
    useSolChatStore.setState({
      sessions: { p1: { ...chat.EMPTY_SESSION, streaming: true } }
    })
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Documentation'))
    expect(screen.getByRole('menuitem', { name: /Ask SOL to find/ })).toHaveAttribute(
      'aria-disabled',
      'true'
    )
  })
})

describe('SolusNodesHarness — deletion', () => {
  it('edits and deletes entries from the entry menu', async () => {
    link()
    vi.mocked(resources.getSolus).mockResolvedValue(config([entry({})]))
    vi.mocked(resources.updateSolusEntry).mockResolvedValue(entry({ text: 'new' }))
    vi.mocked(resources.deleteSolusEntry).mockResolvedValue(undefined)
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Spec: 48 V bus'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Edit' }))
    const box = screen.getByDisplayValue('Spec: 48 V bus')
    await userEvent.clear(box)
    await userEvent.type(box, 'new')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(vi.mocked(resources.updateSolusEntry)).toHaveBeenCalledWith('p1', 'e1', 'new')
    )
    fireEvent.contextMenu(await screen.findByText('Spec: 48 V bus'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    // The menu's Delete focuses the entry and arms the sidebar's confirm step — no modal.
    expect(useFocusStore.getState().focusedEntityId).toBe('e1-node')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(resources.deleteSolusEntry).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Delete note' }))
    await waitFor(() =>
      expect(vi.mocked(resources.deleteSolusEntry)).toHaveBeenCalledWith('p1', 'e1')
    )
  })

  it('confirms before deleting an imported file', async () => {
    link()
    vi.mocked(resources.getSolus).mockResolvedValue(
      config([
        entry({
          id: 'e2',
          kind: 'artifact',
          text: null,
          name: 'rules.pdf',
          artifact_id: 'a1',
          entity_id: 'd1',
          media_type: 'application/pdf',
          size_bytes: 5
        })
      ])
    )
    vi.mocked(resources.deleteSolusEntry).mockResolvedValue(undefined)
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('rules.pdf'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(vi.mocked(resources.deleteSolusEntry)).not.toHaveBeenCalled()
    expect(screen.getByText(/stored bytes go with it/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete file' }))
    await waitFor(() =>
      expect(vi.mocked(resources.deleteSolusEntry)).toHaveBeenCalledWith('p1', 'e2')
    )
  })

  it('is honest when offline: no mutations offered', () => {
    render(<SolusNodesHarness />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    fireEvent.contextMenu(screen.getByText('Goals'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})

describe('canvas mutation regressions', () => {
  it('refreshes the graph after adding and removing text nodes', async () => {
    link()
    vi.mocked(resources.addSolusEntry).mockResolvedValue(entry({}))
    vi.mocked(resources.deleteSolusEntry).mockResolvedValue(undefined)
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Goals'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Type it' }))
    await userEvent.type(screen.getByRole('textbox'), 'Spec: 48 V bus')
    vi.mocked(resources.getSolus).mockResolvedValue(config([entry({})]))
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(graphChanged).toHaveBeenCalledTimes(1))
    fireEvent.contextMenu(await screen.findByText('Spec: 48 V bus'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(resources.deleteSolusEntry).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Delete note' }))
    await waitFor(() => expect(graphChanged).toHaveBeenCalledTimes(2))
  })

  it('keeps a failed edit open with its draft', async () => {
    link()
    vi.mocked(resources.getSolus).mockResolvedValue(config([entry({})]))
    vi.mocked(resources.updateSolusEntry).mockRejectedValue(new Error('Try again'))
    render(<SolusNodesHarness />)
    fireEvent.contextMenu(await screen.findByText('Spec: 48 V bus'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Edit' }))
    await userEvent.clear(screen.getByRole('textbox'))
    await userEvent.type(screen.getByRole('textbox'), 'Keep my draft')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(useShellStore.getState().toast?.title).toBe("That didn't work"))
    expect(screen.getByRole('textbox')).toHaveValue('Keep my draft')
    expect(graphChanged).not.toHaveBeenCalled()
  })
})

describe('pending file import scope', () => {
  it.each(['project', 'account'])(
    'does not file a delayed upload after changing %s',
    async (boundary) => {
      link()
      const previousAuth = useAuthStore.getState()
      let finish!: (value: Awaited<ReturnType<typeof resources.uploadArtifact>>) => void
      vi.mocked(resources.uploadArtifact).mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve
        })
      )
      const { unmount } = render(<SolusNodesHarness />)
      // Online: the section cards show their counts, not the offline dash.
      await screen.findByText('Documentation')
      await waitFor(() => expect(screen.queryAllByText('—')).toHaveLength(0))
      fireEvent.contextMenu(screen.getByText('Documentation'))
      await userEvent.click(screen.getByRole('menuitem', { name: 'Import files…' }))
      await userEvent.upload(
        screen.getByLabelText('Import a file into .solus'),
        new File(['%PDF'], 'private.pdf', { type: 'application/pdf' })
      )
      await waitFor(() => expect(resources.uploadArtifact).toHaveBeenCalledTimes(1))
      await act(async () => {
        if (boundary === 'project')
          useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } })
        else useAuthStore.setState({ user: { email: 'new-account@example.invalid' } })
        finish({
          artifact_id: 'old-artifact',
          uri: '/x',
          media_type: 'application/pdf',
          storage: 'local',
          size_bytes: 4,
          summary: null
        })
      })
      expect(resources.addSolusEntry).not.toHaveBeenCalled()
      expect(graphChanged).not.toHaveBeenCalled()
      unmount()
      useAuthStore.setState(previousAuth)
    }
  )
})

it('offers deletion of a software config record without a text editor or environment removal', async () => {
  link()
  const environment = entry({
    section: 'environment',
    subsection: 'software',
    kind: 'config',
    text: 'perception',
    payload: {
      type: 'venv',
      name: 'perception',
      packages: [],
      provenance: 'detected',
      detected_on: null
    }
  })
  vi.mocked(resources.getSolus).mockResolvedValue({
    entity_id: 'solus-1',
    sections: { ...emptySections(), environment: [environment] }
  })
  render(<SolusNodesHarness />)
  fireEvent.contextMenu(await screen.findByText('perception'))
  expect(screen.queryByText('Edit')).not.toBeInTheDocument()
  fireEvent.click(screen.getByText('Delete'))
  expect(screen.getByText(/The environment remains on your computer/)).toBeInTheDocument()
})
