// The `.solus` panel (SOLUSDEV-240): five honest sections, one right-click menu
// with the same three actions everywhere, and the three flows behind it.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as resources from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useShellStore } from '../workspace/shellStore'
import { useSolChatStore } from '../sol/solChatStore'
import * as chat from '../sol/solChatStore'
import { SolusPanel, askSolMessage, sectionCountLabel, formatSize } from './SolusPanel'
import { emptySections } from './useSolusConfig'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getSolus: vi.fn(),
    addSolusEntry: vi.fn(),
    updateSolusEntry: vi.fn(),
    deleteSolusEntry: vi.fn(),
    uploadArtifact: vi.fn()
  }
})

vi.mock('../sol/solChatStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../sol/solChatStore')>()
  return { ...actual, startNewChat: vi.fn(), sendMessage: vi.fn() }
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
    entity_id: null,
    media_type: null,
    size_bytes: null,
    created_by: 'u1',
    created_at: '',
    updated_at: '',
    ...over
  }
}

function config(details: resources.SolusEntry[] = []): resources.SolusConfig {
  return { entity_id: 'solus-1', sections: { ...emptySections(), details } }
}

function link(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
}

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useShellStore.getState().reset()
  useSolChatStore.setState({ sessions: {} })
  vi.mocked(resources.getSolus).mockResolvedValue(config())
})

describe('pure helpers', () => {
  it('labels counts honestly and formats the SOL query', () => {
    expect(sectionCountLabel(0)).toBe('EMPTY')
    expect(sectionCountLabel(3)).toBe('3')
    expect(askSolMessage('Project details', '  fusing rules ')).toBe(
      'Find for .solus › Project details: fusing rules'
    )
    expect(formatSize(null)).toBe('')
    expect(formatSize(2748812)).toBe('2.6 MB')
  })
})

describe('SolusPanel', () => {
  it('shows five EMPTY sections and no invented entries', async () => {
    link()
    render(<SolusPanel />)
    for (const label of [
      'Hardware configs',
      'Project details',
      'Error logging',
      'Documentation',
      'Code environment'
    ]) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
    expect(screen.getAllByText('EMPTY')).toHaveLength(5)
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
    render(<SolusPanel />)
    expect(await screen.findByText('Spec: 48 V bus')).toBeInTheDocument()
    expect(screen.getByText('FSAE Rules 2027.pdf')).toBeInTheDocument()
    expect(screen.getByText('application/pdf · 1.0 KB')).toBeInTheDocument()
    expect(screen.getByText('SOL found: EV.7.2')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('offers the same three actions on every section', async () => {
    link()
    render(<SolusPanel />)
    fireEvent.contextMenu(await screen.findByText('Code environment'))
    expect(screen.getByText('CODE ENVIRONMENT')).toBeInTheDocument()
    const items = screen.getAllByRole('menuitem').map((el) => el.textContent)
    expect(items).toEqual(['Import files…', 'Ask SOL to find…', 'Type it'])
  })

  it('Type it posts a text entry and refetches', async () => {
    link()
    vi.mocked(resources.addSolusEntry).mockResolvedValue(entry({}))
    render(<SolusPanel />)
    fireEvent.contextMenu(await screen.findByText('Project details'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Type it' }))
    const box = screen.getByPlaceholderText('Type it — plain text')
    await userEvent.type(box, 'Spec: 48 V bus')
    vi.mocked(resources.getSolus).mockResolvedValue(config([entry({})]))
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() =>
      expect(vi.mocked(resources.addSolusEntry)).toHaveBeenCalledWith('p1', 'details', {
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
    render(<SolusPanel />)
    fireEvent.contextMenu(await screen.findByText('Project details'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Import files…' }))
    const input = screen.getByLabelText('Import a file into .solus') as HTMLInputElement
    const file = new File(['%PDF'], 'rules.pdf', { type: 'application/pdf' })
    await userEvent.upload(input, file)
    await waitFor(() =>
      expect(vi.mocked(resources.addSolusEntry)).toHaveBeenCalledWith('p1', 'details', {
        kind: 'artifact',
        artifact_id: 'a1',
        name: 'rules.pdf'
      })
    )
    expect(vi.mocked(resources.uploadArtifact)).toHaveBeenCalledWith('p1', file)
  })

  it('Import files refuses an oversized file before uploading', async () => {
    link()
    render(<SolusPanel />)
    fireEvent.contextMenu(await screen.findByText('Documentation'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Import files…' }))
    const input = screen.getByLabelText('Import a file into .solus') as HTMLInputElement
    const big = new File(['x'], 'huge.step', { type: 'model/step' })
    Object.defineProperty(big, 'size', { value: resources.ARTIFACT_MAX_BYTES + 1 })
    await userEvent.upload(input, big)
    await waitFor(() => expect(useShellStore.getState().toast?.title).toBe('File too large'))
    expect(vi.mocked(resources.uploadArtifact)).not.toHaveBeenCalled()
  })

  it('Ask SOL sends a turn through the chat store and reports what was filed', async () => {
    link()
    vi.mocked(chat.sendMessage).mockResolvedValue(undefined)
    render(<SolusPanel />)
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
        docs: [entry({ id: 'e9', section: 'docs', kind: 'sol', author: 'sol', text: 'EV.7.2' })]
      }
    })
    await userEvent.click(screen.getByRole('button', { name: 'Ask SOL' }))
    await waitFor(() =>
      expect(vi.mocked(chat.sendMessage)).toHaveBeenCalledWith(
        'p1',
        'Find for .solus › Documentation: fusing rules',
        'do'
      )
    )
    expect(vi.mocked(chat.startNewChat)).toHaveBeenCalledWith('p1')
    await waitFor(() =>
      expect(useShellStore.getState().toast?.title).toBe('Filed to .solus › Documentation')
    )
  })

  it('Ask SOL says so when SOL filed nothing', async () => {
    link()
    vi.mocked(chat.sendMessage).mockResolvedValue(undefined)
    render(<SolusPanel />)
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
    render(<SolusPanel />)
    fireEvent.contextMenu(await screen.findByText('Documentation'))
    expect(screen.getByRole('menuitem', { name: /Ask SOL to find/ })).toHaveAttribute(
      'aria-disabled',
      'true'
    )
  })

  it('edits and deletes entries from the entry menu', async () => {
    link()
    vi.mocked(resources.getSolus).mockResolvedValue(config([entry({})]))
    vi.mocked(resources.updateSolusEntry).mockResolvedValue(entry({ text: 'new' }))
    vi.mocked(resources.deleteSolusEntry).mockResolvedValue(undefined)
    render(<SolusPanel />)
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
    render(<SolusPanel />)
    fireEvent.contextMenu(await screen.findByText('rules.pdf'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(vi.mocked(resources.deleteSolusEntry)).not.toHaveBeenCalled()
    expect(screen.getByText(/Permanently delete/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Delete file/ }))
    await waitFor(() =>
      expect(vi.mocked(resources.deleteSolusEntry)).toHaveBeenCalledWith('p1', 'e2')
    )
  })

  it('is honest when offline: no mutations offered', () => {
    render(<SolusPanel />)
    expect(screen.getByText(/Sign in and open a project/)).toBeInTheDocument()
    fireEvent.contextMenu(screen.getByText('Project details'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})
