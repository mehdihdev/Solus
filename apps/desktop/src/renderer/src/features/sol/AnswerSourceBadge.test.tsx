// SOLUSDEV-321 P1-T6: the "answered from the graph" badge. The first tier answers from the graph
// with no model call; the badge says so, and names the fact sources it read (the trace step the
// dropped synthetic tool call used to be). It shows only what the server said — a source it does
// not know shows nothing, never a guess.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AnswerSourceBadge } from './AnswerSourceBadge'

describe('AnswerSourceBadge', () => {
  it('says the graph answered, and which fact sources it read', () => {
    render(<AnswerSourceBadge answer={{ source: 'graph', sources: ['config', 'telemetry'] }} />)
    expect(screen.getByText('answered from the graph')).toBeInTheDocument()
    expect(screen.getByText('sources: config, telemetry')).toBeInTheDocument()
  })

  it('names no sources when it read none', () => {
    render(<AnswerSourceBadge answer={{ source: 'graph', sources: [] }} />)
    expect(screen.getByText('answered from the graph')).toBeInTheDocument()
    expect(screen.queryByText(/sources:/)).toBeNull()
  })

  it('renders nothing for a turn that has no answer source', () => {
    const { container } = render(<AnswerSourceBadge answer={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing for a source it does not know — empty beats invented', () => {
    const { container } = render(
      <AnswerSourceBadge answer={{ source: 'a_tier_from_the_future', sources: ['config'] }} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders text only', () => {
    render(<AnswerSourceBadge answer={{ source: 'graph', sources: ['<b>bold</b>'] }} />)
    expect(document.querySelector('b')).toBeNull()
    expect(screen.getByText('sources: <b>bold</b>')).toBeInTheDocument()
  })
})
