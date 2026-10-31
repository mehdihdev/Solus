// SOLUSDEV-321 P1-T6: a tool step's arguments in the trace — the server's REDACTED copy, bounded by
// the stream parser, shown as `key: value` text. Text nodes only: model-proposed args are the
// least trusted string on the page.
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TraceArgs } from './TraceArgs'

describe('TraceArgs', () => {
  it('shows each arg as key: value text, in the order they arrived', () => {
    render(<TraceArgs args={{ entity_id: 'imu', password: '[REDACTED]' }} />)
    const block = screen.getByTestId('tool-args')
    expect(within(block).getByText('entity_id: imu')).toBeInTheDocument()
    expect(within(block).getByText('password: [REDACTED]')).toBeInTheDocument()
    expect(Array.from(block.children).map((row) => row.textContent)).toEqual([
      'entity_id: imu',
      'password: [REDACTED]'
    ])
  })

  it('renders nothing when the call carried no args', () => {
    const { container, rerender } = render(<TraceArgs args={undefined} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<TraceArgs args={{}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders every value as text, never markup', () => {
    render(
      <TraceArgs
        args={{
          note: '<img src=x onerror=alert(1)>',
          link: '<a href="https://evil.example">click</a>',
          script: '<script>alert(1)</script>',
          bold: '<b>x</b>'
        }}
      />
    )
    expect(document.querySelector('img, a, script, b, [onerror]')).toBeNull()
    expect(screen.getByText('note: <img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(screen.getByText('script: <script>alert(1)</script>')).toBeInTheDocument()
    expect(screen.getByText('bold: <b>x</b>')).toBeInTheDocument()
  })

  // Masking is the server's job (pinned in packages/api/tests/test_stream.py) and the 64-character
  // bound is the stream parser's (solStream.test.ts, and end to end in SolChat.test.tsx): this
  // component draws exactly what it is given.
  it('shows a value, masked or not, exactly as it arrived', () => {
    render(<TraceArgs args={{ api_key: '[REDACTED]', query: 'OV9281 supply' }} />)
    expect(screen.getByText('api_key: [REDACTED]')).toBeInTheDocument()
    expect(screen.getByText('query: OV9281 supply')).toBeInTheDocument()
  })
})
