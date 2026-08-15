// SOLX-03 render site. SOL-IPC-01's M7 finding named this file before it
// existed: "`GuideStep` text and `failed.reason` are untrusted content end-to-end
// — render as text only … red-team fixtures at those sites." SOLX-02 recorded the
// render-site test as still owed. This is it.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { GuideOverlay } from './GuideOverlay'
import type { OverlayView } from './overlaySession'

const BOX = { x: 0.25, y: 0.5, w: 0.2, h: 0.1 }

function view(overrides: Partial<OverlayView> = {}): OverlayView {
  return {
    handoffId: 'h1',
    stepId: 's1',
    index: 0,
    total: 3,
    title: 'Place a symbol',
    instruction: 'Press A to open the symbol chooser.',
    decision: { kind: 'annotate', box: BOX },
    ...overrides
  }
}

describe('GuideOverlay — pointing', () => {
  it('draws the pointer as a percentage box, so it scales with the tool window', () => {
    // The locator is normalised 0..1; percentages keep it correct when the tool
    // window is resized without a fresh reposition round-trip.
    render(<GuideOverlay view={view()} />)
    const pointer = screen.getByTestId('overlay-pointer')
    expect(pointer.style.left).toBe('25%')
    expect(pointer.style.top).toBe('50%')
    expect(pointer.style.width).toBe('20%')
    expect(pointer.style.height).toBe('10%')
  })

  it('shows the step text alongside the pointer', () => {
    render(<GuideOverlay view={view()} />)
    expect(screen.getByText('Place a symbol')).toBeInTheDocument()
    expect(screen.getByText('Press A to open the symbol chooser.')).toBeInTheDocument()
  })

  it('draws NOTHING when the gate said fall back', () => {
    // The whole point of SOLX-03: no pointer is correct, a guessed pointer is not.
    render(<GuideOverlay view={view({ decision: { kind: 'fallback', reason: 'no_locator' } })} />)
    expect(screen.queryByTestId('overlay-pointer')).not.toBeInTheDocument()
  })

  it('renders nothing at all with no active view', () => {
    const { container } = render(<GuideOverlay view={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('GuideOverlay — untrusted text (M7 red-team)', () => {
  // Step text can originate in a vendored fork's knowledge base. It reaches this
  // component having crossed a process boundary and a wire, and it is rendered
  // over the user's real application — the worst place in the app to execute
  // someone else's markup.
  const PAYLOADS = [
    '<img src=x onerror="window.__pwned=1">',
    '<script>window.__pwned=1</script>',
    '<svg/onload=alert(1)>',
    '"><iframe src="https://evil.example"></iframe>'
  ]

  it('renders hostile step text as literal characters, never as markup', () => {
    for (const payload of PAYLOADS) {
      const { container, unmount } = render(
        <GuideOverlay view={view({ title: payload, instruction: payload })} />
      )
      // The text is present verbatim…
      expect(container.textContent).toContain(payload)
      // …and produced no elements: no injected tag, no execution site.
      expect(container.querySelector('img,script,iframe,svg')).toBeNull()
      expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined()
      unmount()
    }
  })

  it('keeps the panel bounded, however long the text', () => {
    // CTR-06 caps an IPC string at 2000 characters. 2000 characters with no
    // height bound would grow the panel up the screen and blanket the tool the
    // user is trying to look at.
    render(<GuideOverlay view={view({ instruction: 'x'.repeat(2000) })} />)
    const panel = screen.getByRole('status')
    expect(panel.style.maxHeight).toBeTruthy()
    expect(panel.style.overflow).toBe('hidden')
    expect(panel.style.maxWidth).toBeTruthy()
  })

  it('does not let hostile text escape through the accessible name either', () => {
    render(<GuideOverlay view={view({ title: PAYLOADS[0] })} />)
    const region = screen.getByRole('status')
    expect(region.querySelector('img')).toBeNull()
  })
})
