// SOLUSDEV-321 P7: what SOL weighed before a proposal, in a collapsible block above ITS card (fix 1,
// M1: mounted once per card, so a block sits on its own card and goes with it). The strings are
// model text the server validated, masked and capped and solStream bounded again, so they render
// as text nodes only — no markup, no link. Guide opens the block; Expert keeps it shut.
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useSettingsStore } from '../../store/settingsStore'
import { ReasoningBlock } from './ReasoningBlock'

const reasoning = {
  considered: ['raise the lid 2 mm', 'move the USB-C port'],
  ruledOut: [{ what: 'a thinner wall', why: 'under the 1.2 mm print minimum' }],
  proposing: 'Set WIDTH to 120 mm so the port clears the casing.'
}

beforeEach(() => {
  useSettingsStore.setState({ solMode: 'Expert' })
})

describe('ReasoningBlock', () => {
  it('shows what SOL considered, ruled out and why, and proposes — shut in Expert', () => {
    render(
      <ReasoningBlock reasoning={[{ confirmationId: 'cf1', reasoning }]} confirmationId="cf1" />
    )
    const block = screen.getByTestId('reasoning-block')
    expect(block.tagName).toBe('DETAILS')
    expect(block).not.toHaveAttribute('open')
    expect(within(block).getByText('raise the lid 2 mm')).toBeInTheDocument()
    expect(within(block).getByText('move the USB-C port')).toBeInTheDocument()
    expect(
      within(block).getByText('a thinner wall — under the 1.2 mm print minimum')
    ).toBeInTheDocument()
    expect(
      within(block).getByText('Set WIDTH to 120 mm so the port clears the casing.')
    ).toBeInTheDocument()
  })

  it('opens in Guide, where the reasoning is part of the teaching', () => {
    useSettingsStore.setState({ solMode: 'Guide' })
    render(
      <ReasoningBlock reasoning={[{ confirmationId: 'cf1', reasoning }]} confirmationId="cf1" />
    )
    expect(screen.getByTestId('reasoning-block')).toHaveAttribute('open')
  })

  it('renders model text as text, never as markup or a link', () => {
    const hostile = {
      considered: ['<img src=x onerror=alert(1)>'],
      ruledOut: [{ what: '<b>bold</b>', why: '[docs](https://example.com)' }],
      proposing: '**not bold**'
    }
    const { container } = render(
      <ReasoningBlock
        reasoning={[{ confirmationId: 'cf1', reasoning: hostile }]}
        confirmationId="cf1"
      />
    )
    expect(container.querySelector('img, b, strong, a')).toBeNull()
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(screen.getByText('<b>bold</b> — [docs](https://example.com)')).toBeInTheDocument()
    expect(screen.getByText('**not bold**')).toBeInTheDocument()
  })

  it('draws its own card’s block alone, and none for reasoning still waiting for its card', () => {
    const later = { ...reasoning, proposing: 'Move the port instead.' }
    const both = [
      { confirmationId: 'cf1', reasoning },
      { confirmationId: null, reasoning: later }
    ]
    const { container, rerender } = render(<ReasoningBlock reasoning={both} confirmationId="cf1" />)
    expect(screen.getAllByTestId('reasoning-block')).toHaveLength(1)
    expect(screen.queryByText('Move the port instead.')).not.toBeInTheDocument()
    rerender(<ReasoningBlock reasoning={both} confirmationId="cf2" />)
    expect(container).toBeEmptyDOMElement()
    rerender(<ReasoningBlock reasoning={undefined} confirmationId="cf1" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('leaves out a list with nothing in it', () => {
    render(
      <ReasoningBlock
        reasoning={[{ confirmationId: 'cf1', reasoning: { ...reasoning, considered: [] } }]}
        confirmationId="cf1"
      />
    )
    expect(screen.queryByText('Considered')).not.toBeInTheDocument()
    expect(screen.getByText('Ruled out')).toBeInTheDocument()
  })
})
