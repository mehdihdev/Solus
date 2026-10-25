import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useShellStore } from '../workspace/shellStore'
import { ArtifactsSection } from './ArtifactsSection'
import * as solApi from './solApi'
import type { ChatArtifact } from './solChatStore'

vi.mock('./solApi', () => ({ fetchArtifactBlob: vi.fn() }))

const artifact = (over: Partial<ChatArtifact> = {}): ChatArtifact => ({
  artifactId: 'a1',
  uri: 'artifact://a1',
  mediaType: 'text/markdown',
  title: 'board-shift-change-note.md',
  sourceTool: 'change_note',
  summary: null,
  filedTo: null,
  ...over
})

beforeEach(() => {
  vi.clearAllMocks()
  useShellStore.getState().reset()
})

describe('ArtifactsSection', () => {
  it('lists this session’s artifacts and files one to .solus from the right-click menu', () => {
    const onFile = vi.fn().mockResolvedValue(undefined)
    render(<ArtifactsSection artifacts={[artifact()]} projectId="p1" onFile={onFile} />)
    const row = screen.getByRole('listitem', { name: 'board-shift-change-note.md' })
    expect(row).toHaveTextContent('MD')
    expect(row).toHaveTextContent('change_note')
    fireEvent.contextMenu(row)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Save to .solus folder' }))
    expect(onFile).toHaveBeenCalledWith('a1', 'documentation')
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('shows the .solus pill once filed and disables saving again', () => {
    render(
      <ArtifactsSection
        artifacts={[artifact({ filedTo: 'documentation' })]}
        projectId="p1"
        onFile={vi.fn()}
      />
    )
    expect(screen.getByText('.solus')).toBeInTheDocument()
    fireEvent.contextMenu(screen.getByRole('listitem'))
    expect(screen.getByRole('menuitem', { name: /Save to .solus folder/ })).toHaveAttribute(
      'aria-disabled',
      'true'
    )
    expect(screen.getByText('Filed to Documentation')).toBeInTheDocument()
  })

  it('copies text artifacts to the clipboard and refuses binary ones', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    vi.mocked(solApi.fetchArtifactBlob).mockResolvedValue(
      new Blob(['# note'], { type: 'text/markdown' })
    )
    render(
      <ArtifactsSection
        artifacts={[
          artifact(),
          artifact({ artifactId: 'a2', title: 'shot.png', mediaType: 'image/png' })
        ]}
        projectId="p1"
        onFile={vi.fn()}
      />
    )
    fireEvent.contextMenu(screen.getByRole('listitem', { name: 'board-shift-change-note.md' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Copy contents' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('# note'))
    expect(useShellStore.getState().toast?.title).toBe('Copied')
    fireEvent.contextMenu(screen.getByRole('listitem', { name: 'shot.png' }))
    expect(screen.getByRole('menuitem', { name: /Copy contents/ })).toHaveAttribute(
      'aria-disabled',
      'true'
    )
  })

  it('is honest when nothing was produced this session', () => {
    render(<ArtifactsSection artifacts={[]} projectId="p1" onFile={vi.fn()} />)
    expect(screen.getByText(/this session only/)).toBeInTheDocument()
  })
})
