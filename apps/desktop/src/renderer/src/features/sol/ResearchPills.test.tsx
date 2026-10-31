// SOLUSDEV-321 P1-T5: the sources of a turn's web research, as pills. A URL is untrusted text from
// the open web, so it is shown as TEXT — never an anchor, never markup — opened only over https
// through the window-open handler the main window guards (externalOpenHandler), and filed, title
// and URL as plain text, into `.solus/documentation/datasheets` on the person's say-so.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import * as resources from '../../lib/api/resources'
import { ResearchPills } from './ResearchPills'
import type { ResearchSource, ResearchSources } from './researchSources'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof resources>()),
  addSolusEntry: vi.fn()
}))
const addSolusEntry = vi.mocked(resources.addSolusEntry)

const HTTPS = 'https://docs.example.com/ov9281'
const DATASHEET: ResearchSource = { url: HTTPS, title: 'OV9281 datasheet', fetched: true }
const HOSTILE: readonly ResearchSource[] = [
  DATASHEET,
  { url: 'javascript:alert(1)', title: '<img src=x onerror=alert(1)>', fetched: false },
  { url: 'http://plain.example.com/a', title: '', fetched: false },
  { url: 'file:///etc/passwd', title: 'local file', fetched: false }
]

function research(sources: readonly ResearchSource[], cached = false): ResearchSources {
  return {
    callId: 'c1',
    question: 'OV9281 supply',
    cached,
    searches: cached ? 0 : 1,
    pages: cached ? 0 : 2,
    sources
  }
}

let open: MockInstance<Window['open']>
beforeEach(() => {
  vi.clearAllMocks()
  open = vi.spyOn(window, 'open').mockReturnValue(null)
})
afterEach(() => open.mockRestore())

describe('ResearchPills', () => {
  it('urls are inert', () => {
    const { container } = render(<ResearchPills research={research(HOSTILE)} projectId="p1" />)

    // Nothing a click, a hover or a parser could follow: no anchor, no href, no markup from a title.
    expect(container.querySelector('a')).toBeNull()
    expect(container.querySelector('[href]')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    // The title and the URL are text nodes the person reads before choosing to open anything.
    expect(screen.getByText('OV9281 datasheet')).toBeInTheDocument()
    expect(screen.getByText(HTTPS)).toBeInTheDocument()
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(screen.getByText('javascript:alert(1)')).toBeInTheDocument()
    // Rendering alone opens nothing.
    expect(open).not.toHaveBeenCalled()
  })

  it('opens an https url through the guarded window-open handler, and nothing else', () => {
    render(<ResearchPills research={research(HOSTILE)} projectId="p1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Open OV9281 datasheet' }))
    expect(open).toHaveBeenCalledTimes(1)
    expect(open).toHaveBeenCalledWith(HTTPS, '_blank', 'noopener,noreferrer')

    // A title-less source is labelled by its host; every non-https scheme is disabled outright.
    for (const name of [
      'Open <img src=x onerror=alert(1)>',
      'Open plain.example.com',
      'Open local file'
    ]) {
      const button = screen.getByRole('button', { name })
      expect(button).toBeDisabled()
      fireEvent.click(button)
    }
    expect(open).toHaveBeenCalledTimes(1)
  })
})

describe('ResearchPills filing', () => {
  it('files a pill under documentation/datasheets as plain text, once', async () => {
    addSolusEntry.mockResolvedValue({} as Awaited<ReturnType<typeof resources.addSolusEntry>>)
    render(<ResearchPills research={research([DATASHEET])} projectId="p1" />)

    const file = screen.getByRole('button', { name: 'File OV9281 datasheet' })
    fireEvent.click(file)
    await waitFor(() => expect(file).toHaveTextContent('Filed'))

    expect(addSolusEntry).toHaveBeenCalledTimes(1)
    expect(addSolusEntry).toHaveBeenCalledWith('p1', 'documentation', {
      kind: 'text',
      text: `OV9281 datasheet\n${HTTPS}`,
      subsection: 'datasheets'
    })
    expect(file).toBeDisabled()
    fireEvent.click(file) // a second click on a filed pill posts nothing
    expect(addSolusEntry).toHaveBeenCalledTimes(1)
  })

  it('says why when filing fails, and lets the person try again', async () => {
    addSolusEntry.mockRejectedValueOnce(new Error('That section is full.'))
    addSolusEntry.mockResolvedValueOnce({} as Awaited<ReturnType<typeof resources.addSolusEntry>>)
    render(<ResearchPills research={research([DATASHEET])} projectId="p1" />)

    const file = screen.getByRole('button', { name: 'File OV9281 datasheet' })
    fireEvent.click(file)
    expect(await screen.findByText('That section is full.')).toBeInTheDocument()
    expect(file).not.toBeDisabled()
    expect(file).toHaveTextContent('File')

    fireEvent.click(file)
    await waitFor(() => expect(file).toHaveTextContent('Filed'))
    expect(screen.queryByText('That section is full.')).toBeNull()
    expect(addSolusEntry).toHaveBeenCalledTimes(2)
  })

  it('marks a cached answer, and renders nothing when there is nothing to show', () => {
    const view = render(<ResearchPills research={research([DATASHEET], true)} projectId="p1" />)
    expect(screen.getByText('cached')).toBeInTheDocument()

    view.rerender(<ResearchPills research={research([])} projectId="p1" />)
    expect(view.container).toBeEmptyDOMElement()
    view.rerender(<ResearchPills research={undefined} projectId="p1" />)
    expect(view.container).toBeEmptyDOMElement()
  })
})
