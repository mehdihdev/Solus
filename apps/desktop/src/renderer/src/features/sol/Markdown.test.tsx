// SYS-04 UI: SOL's model text renders as markdown WITHOUT an HTML injection
// path (CLAUDE.md §7 — model output is untrusted). These tests pin the security
// posture, not the typography: raw HTML stays inert, links never become
// anchors, images never load.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SolMarkdown } from './Markdown'

describe('SolMarkdown', () => {
  it('renders headings, emphasis, lists and inline code as elements', () => {
    render(
      <SolMarkdown content={'## Parts\n\nThe **shoulder** drives `joint_2`:\n\n- Base\n- Link 1'} />
    )
    expect(screen.getByRole('heading', { name: 'Parts' })).toBeInTheDocument()
    expect(screen.getByText('shoulder').tagName).toBe('STRONG')
    expect(screen.getByText('joint_2').tagName).toBe('CODE')
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Base', 'Link 1'])
  })

  it('renders fenced code blocks in a pre', () => {
    render(<SolMarkdown content={'```python\nprint("hi")\n```'} />)
    const code = screen.getByText('print("hi")')
    expect(code.closest('pre')).not.toBeNull()
  })

  it('never parses raw HTML from model output into the DOM', () => {
    render(<SolMarkdown content={'before <img src=x onerror=alert(1)> <b>bold?</b> after'} />)
    // The tags are SKIPPED, not executed and not shown as literal text — and
    // nothing becomes a real element.
    expect(document.querySelector('img')).toBeNull()
    expect(document.querySelector('b')).toBeNull()
    expect(screen.getByText(/before/)).toBeInTheDocument()
    expect(screen.getByText(/after/)).toBeInTheDocument()
  })

  it('renders links as inert text, never anchors (no navigation from model output)', () => {
    render(
      <SolMarkdown
        content={'See [the datasheet](https://evil.example/x) or https://example.com/y'}
      />
    )
    expect(screen.queryAllByRole('link')).toEqual([])
    expect(document.querySelector('a')).toBeNull()
    expect(screen.getByText('the datasheet')).toBeInTheDocument() // text survives
  })

  it('drops images entirely (the CSP blocks remote sources anyway)', () => {
    render(<SolMarkdown content={'![diagram](https://example.com/d.png)'} />)
    expect(document.querySelector('img')).toBeNull()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('renders plain prose unchanged', () => {
    render(<SolMarkdown content="Just a sentence with no markup." />)
    expect(screen.getByText('Just a sentence with no markup.')).toBeInTheDocument()
  })
})
