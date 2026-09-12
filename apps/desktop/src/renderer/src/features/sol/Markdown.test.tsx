// SYS-04 UI: SOL's model text renders as markdown WITHOUT an HTML injection
// path (CLAUDE.md §7 — model output is untrusted). These tests pin the security
// posture, not the typography: raw HTML stays inert, links never become
// anchors, images never load.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { SolMarkdown } from './Markdown'
import { buildBenchMarkdown } from './streamBench'

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

// SOLUSDEV-252 S2: the settled/tail two-parse render. Settled blocks are
// parsed once and reused; only the block being written re-parses per token.
describe('SolMarkdown two-parse streaming render', () => {
  function oneParse(content: string): string {
    const { container, unmount } = render(
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
        {content}
      </ReactMarkdown>
    )
    const html = container.innerHTML
    unmount()
    return html
  }

  it('renders the same DOM as a single parse for settled content', () => {
    for (const content of [
      buildBenchMarkdown(),
      '# T\n\npara one\n\n- a\n- b\n\n```c\nint x;\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nend.\n',
      'no blank lines at all\nstill one paragraph'
    ]) {
      const expected = oneParse(content)
      const { container, unmount } = render(<SolMarkdown content={content} />)
      expect(container.querySelector('.sol-md')?.innerHTML).toBe(expected)
      unmount()
    }
  })

  it('a growing fenced code block stays ONE reused <pre> across renders', () => {
    const head = 'Intro paragraph.\n\n```c\nint a;\n'
    const { container, rerender } = render(<SolMarkdown content={head} />)
    const pres = container.querySelectorAll('pre')
    expect(pres).toHaveLength(1)
    const first = pres[0]
    rerender(<SolMarkdown content={`${head}int b;\nint c;\n`} />)
    const after = container.querySelectorAll('pre')
    expect(after).toHaveLength(1)
    expect(after[0]).toBe(first) // same DOM node, not a re-created block
    expect(after[0].textContent).toContain('int c;')
  })

  it('holds a half-typed table header back instead of toggling paragraph ↔ table', () => {
    const { container, rerender } = render(<SolMarkdown content={'See:\n\n| Signal | Addr'} />)
    expect(container.querySelector('table')).toBeNull()
    expect(container.textContent).not.toContain('| Signal')
    rerender(<SolMarkdown content={'See:\n\n| Signal | Addr |\n|---|---|\n| imu | 0x28 |'} />)
    expect(container.querySelector('table')).not.toBeNull()
  })

  it('keeps the security posture across both parses (no HTML, no anchors, no images)', () => {
    render(
      <SolMarkdown
        content={
          '<b>x</b> [l](https://e.example)\n\n![i](https://e.example/i.png) <img src=x> [m](https://e.example)'
        }
      />
    )
    expect(document.querySelector('b')).toBeNull()
    expect(document.querySelector('img')).toBeNull()
    expect(document.querySelector('a')).toBeNull()
    expect(screen.getByText('l')).toBeInTheDocument()
    expect(screen.getByText('m')).toBeInTheDocument()
  })
})
