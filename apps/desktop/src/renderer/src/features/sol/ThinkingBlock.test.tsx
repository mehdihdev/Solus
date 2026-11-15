// SOLUSDEV-326: the reply's Thinking block — SOL's thought summary and its tool steps, live and
// then folded into "Thought for Ns · N steps".
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useSettingsStore } from '../../store/settingsStore'
import { blankItem } from './solChatItems'
import type { ChatItem } from './solChatStore'
import { ThinkingBlock } from './ThinkingBlock'

const step = (callId: string, tool: string, ok: boolean | null) => ({
  callId,
  tool,
  ok,
  errorCode: ok === false ? 'TIMEOUT' : null
})

function thinkingItem(over: Partial<ChatItem> = {}): ChatItem {
  return {
    ...blankItem('a1', 'assistant', '', true),
    thinking: {
      segments: [
        { text: 'I should look at the IMU first.', afterSteps: 0 },
        { text: 'The address clashes with the baro.', afterSteps: 1 }
      ],
      lastAt: 0,
      ms: 4_200
    },
    trace: [step('c1', 'graph.get_entity', true)],
    ...over
  }
}

beforeEach(() => useSettingsStore.setState({ solMode: 'Expert' }))

describe('ThinkingBlock', () => {
  it('renders nothing for a turn with no thought and no steps', () => {
    const { container } = render(<ThinkingBlock item={blankItem('a1', 'assistant', 'Hi.')} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('is open while SOL thinks, with the thought and each step in order', () => {
    render(<ThinkingBlock item={thinkingItem()} />)

    expect(screen.getByRole('button', { name: /thinking/i })).toHaveAttribute(
      'aria-expanded',
      'true'
    )
    const body = screen.getByTestId('thinking-body')
    const text = body.textContent ?? ''
    expect(text.indexOf('IMU first')).toBeLessThan(text.indexOf('Get entity'))
    expect(text.indexOf('Get entity')).toBeLessThan(text.indexOf('clashes with the baro'))
  })

  it('shows a running step as running, and a failed step with its code', () => {
    render(
      <ThinkingBlock
        item={thinkingItem({
          trace: [step('c1', 'graph.get_entity', null), step('c2', 'kicad.read_netlist', false)]
        })}
      />
    )

    expect(screen.getByText(/Get entity/).closest('[data-step]')).toHaveAttribute(
      'data-step',
      'running'
    )
    expect(screen.getByText(/TIMEOUT/)).toBeInTheDocument()
  })

  it('stays live while the turn runs, even after SOL writes text before a tool', () => {
    render(<ThinkingBlock item={thinkingItem({ content: 'Let me check the netlist…' })} />)

    expect(screen.getByRole('button', { name: /thinking/i })).toHaveAttribute(
      'aria-expanded',
      'true'
    )
  })

  it('folds into a summary once the turn ends, shut in Expert mode', () => {
    render(
      <ThinkingBlock
        item={thinkingItem({ content: 'The IMU and baro share 0x76.', pending: false })}
      />
    )

    const toggle = screen.getByRole('button', { name: 'Thought for 4s · 1 step' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('thinking-body')).toBeNull()

    fireEvent.click(toggle)
    expect(screen.getByTestId('thinking-body')).toHaveTextContent('IMU first')
  })

  it('stays open after the answer in Guide mode, where the reasoning is part of the teaching', () => {
    useSettingsStore.setState({ solMode: 'Guide' })
    render(<ThinkingBlock item={thinkingItem({ content: 'Done.', pending: false })} />)

    expect(screen.getByRole('button', { name: /Thought for/ })).toHaveAttribute(
      'aria-expanded',
      'true'
    )
  })

  it('draws model text as text, never markup', () => {
    render(
      <ThinkingBlock
        item={thinkingItem({
          thinking: {
            segments: [{ text: '<img src=x onerror=alert(1)> **bold**', afterSteps: 0 }],
            lastAt: 0,
            ms: 1
          }
        })}
      />
    )

    expect(screen.getByTestId('thinking-body')).toHaveTextContent('<img src=x onerror=alert(1)>')
    expect(document.querySelector('img')).toBeNull()
  })

  it('folds a steps-only turn into its step count', () => {
    render(
      <ThinkingBlock
        item={{
          ...blankItem('a1', 'assistant', 'Done.'),
          trace: [step('c1', 'graph.get_entity', true), step('c2', 'research', true)]
        }}
      />
    )

    expect(screen.getByRole('button', { name: '2 steps' })).toBeInTheDocument()
  })
})
