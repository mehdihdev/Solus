// SOLUSDEV-252 S5: a tool's artifact in the transcript — bytes fetched WITH the
// bearer and shown from an object URL (an <img>, so nothing inside an SVG can
// run; the markup never touches the DOM), then "File this to…?" into .solus.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as solApi from './solApi'
import { ArtifactCard } from './ArtifactCard'
import type { ChatArtifact } from './solChatStore'

vi.mock('./solApi', () => ({ fetchArtifactBlob: vi.fn() }))
const fetchArtifactBlob = vi.mocked(solApi.fetchArtifactBlob)

const SVG: ChatArtifact = {
  artifactId: 'a1',
  uri: '/api/v1/projects/p1/artifacts/a1/content',
  mediaType: 'image/svg+xml',
  title: 'Power tree',
  sourceTool: 'solus.make_diagram',
  summary: 'Battery → regulators → loads',
  filedTo: null
}

// jsdom has neither; stubbed for the file (React's unmount cleanup runs after
// afterEach, so they must outlive each test).
const createObjectURL = vi.fn(() => 'blob:sol/a1')
const revokeObjectURL = vi.fn()
URL.createObjectURL = createObjectURL
URL.revokeObjectURL = revokeObjectURL

beforeEach(() => {
  vi.clearAllMocks()
  fetchArtifactBlob.mockResolvedValue(
    new Blob(['<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>'], {
      type: 'image/svg+xml'
    })
  )
})
describe('ArtifactCard', () => {
  it('fetches an image through the API client and shows it from an object URL', async () => {
    const { unmount } = render(<ArtifactCard projectId="p1" artifact={SVG} onFile={vi.fn()} />)
    const img = await screen.findByRole('img', { name: 'Power tree' })
    expect(img).toHaveAttribute('src', 'blob:sol/a1')
    expect(fetchArtifactBlob).toHaveBeenCalledWith('p1', 'a1')
    // The SVG text is a Blob, never markup in the document.
    expect(document.querySelector('svg')).toBeNull()
    expect(document.querySelector('script')).toBeNull()
    unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:sol/a1')
  })

  it('renders other media as a file chip without fetching the bytes', () => {
    render(
      <ArtifactCard
        projectId="p1"
        artifact={{ ...SVG, mediaType: 'application/zip', title: 'kicad-export.zip' }}
        onFile={vi.fn()}
      />
    )
    expect(screen.getByText('kicad-export.zip')).toBeInTheDocument()
    expect(screen.getByText('application/zip')).toBeInTheDocument()
    expect(fetchArtifactBlob).not.toHaveBeenCalled()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('says so when the bytes cannot be fetched — never a broken image', async () => {
    fetchArtifactBlob.mockRejectedValue(new Error('gone'))
    render(<ArtifactCard projectId="p1" artifact={SVG} onFile={vi.fn()} />)
    expect(await screen.findByText(/couldn’t load/i)).toBeInTheDocument()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('files to the chosen section and shows the filed label; the row cannot file twice', async () => {
    const onFile = vi.fn(async () => {})
    const { rerender } = render(<ArtifactCard projectId="p1" artifact={SVG} onFile={onFile} />)
    fireEvent.click(screen.getByRole('radio', { name: 'Documentation' }))
    fireEvent.click(screen.getByRole('button', { name: 'File' }))
    await waitFor(() => expect(onFile).toHaveBeenCalledWith('docs'))
    // The host marks the store item filed; the card renders that, not local state.
    rerender(<ArtifactCard projectId="p1" artifact={{ ...SVG, filedTo: 'docs' }} onFile={onFile} />)
    expect(screen.getByText('Filed to Documentation')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'File' })).toBeNull()
  })

  it('shows the API error inline and keeps the row live when filing fails', async () => {
    const onFile = vi.fn(async () => {
      throw new Error('That artifact has expired.')
    })
    render(<ArtifactCard projectId="p1" artifact={SVG} onFile={onFile} />)
    fireEvent.click(screen.getByRole('button', { name: 'File' }))
    expect(await screen.findByText('That artifact has expired.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'File' })).toBeEnabled()
  })

  it('"Keep in chat" hides the filing row and leaves the artifact', async () => {
    render(<ArtifactCard projectId="p1" artifact={SVG} onFile={vi.fn()} />)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Keep in chat' }))
    })
    expect(screen.queryByRole('button', { name: 'File' })).toBeNull()
    expect(screen.queryByRole('radiogroup')).toBeNull()
    expect(await screen.findByRole('img', { name: 'Power tree' })).toBeInTheDocument()
  })

  it('renders an untrusted title as text, never markup', () => {
    render(
      <ArtifactCard
        projectId="p1"
        artifact={{ ...SVG, mediaType: 'text/plain', title: '<b onclick=x>hi</b>' }}
        onFile={vi.fn()}
      />
    )
    expect(screen.getByText('<b onclick=x>hi</b>')).toBeInTheDocument()
    expect(document.querySelector('b')).toBeNull()
  })
})
