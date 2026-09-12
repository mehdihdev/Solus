// Keyboard navigation for the `@`-mention picker. SolChat.test.tsx covers the
// mouse path and the wire; this covers the keys, which are the part a
// keyboard-only user depends on entirely.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useMentionPicker } from './useMentionPicker'
import { MENTION_DEBOUNCE_MS } from './useMentionSearch'

vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  listEntities: vi.fn()
}))

const { listEntities } = await import('../../lib/api/resources')
const mockListEntities = vi.mocked(listEntities)

function entity(id: string, name: string): Record<string, string> {
  return { id, name, type: 'part', domain: 'mechanical', source_key: `k-${id}` }
}

let submitted = 0

function Harness(): React.JSX.Element {
  const [text, setText] = useState('')
  const picker = useMentionPicker('p1', text, setText)
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submitted += 1
      }}
    >
      <input
        ref={picker.inputRef}
        aria-label="Message SOL"
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          picker.onInput(e.target)
        }}
        onKeyDown={(e) => {
          if (picker.onKeyDown(e)) return
          if (e.key === 'Enter') {
            e.preventDefault()
            submitted += 1
          }
        }}
      />
      <div data-testid="open">{String(picker.listOpen)}</div>
      <div data-testid="active">{picker.active?.name ?? ''}</div>
      <div data-testid="ids">{picker.mentionIds.join(',')}</div>
    </form>
  )
}

async function openPicker(): Promise<HTMLElement> {
  render(<Harness />)
  const box = screen.getByLabelText('Message SOL')
  fireEvent.change(box, { target: { value: '@b' } })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
  })
  return box
}

beforeEach(() => {
  submitted = 0
  vi.clearAllMocks()
  vi.useFakeTimers()
  mockListEntities.mockResolvedValue([
    entity('e-1', 'Bracket A'),
    entity('e-2', 'Bracket B')
  ] as never)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useMentionPicker keyboard navigation', () => {
  it('starts on the first result', async () => {
    await openPicker()
    expect(screen.getByTestId('open').textContent).toBe('true')
    expect(screen.getByTestId('active').textContent).toBe('Bracket A')
  })

  it('moves down and wraps around', async () => {
    const box = await openPicker()
    fireEvent.keyDown(box, { key: 'ArrowDown' })
    expect(screen.getByTestId('active').textContent).toBe('Bracket B')
    fireEvent.keyDown(box, { key: 'ArrowDown' })
    expect(screen.getByTestId('active').textContent).toBe('Bracket A')
  })

  it('moves up from the first result to the last', async () => {
    const box = await openPicker()
    fireEvent.keyDown(box, { key: 'ArrowUp' })
    expect(screen.getByTestId('active').textContent).toBe('Bracket B')
  })

  it('Enter picks the highlighted entity and does NOT send the message', async () => {
    const box = await openPicker()
    fireEvent.keyDown(box, { key: 'ArrowDown' })
    await act(async () => {
      fireEvent.keyDown(box, { key: 'Enter' })
    })

    expect(box).toHaveValue('@Bracket B ')
    expect(screen.getByTestId('ids').textContent).toBe('e-2')
    expect(submitted).toBe(0)
  })

  it('Enter sends normally once the picker is closed', async () => {
    const box = await openPicker()
    fireEvent.keyDown(box, { key: 'Escape' })
    fireEvent.keyDown(box, { key: 'Enter' })

    expect(submitted).toBe(1)
  })

  it('Escape dismisses the list without clearing what was typed', async () => {
    const box = await openPicker()
    fireEvent.keyDown(box, { key: 'Escape' })

    expect(screen.getByTestId('open').textContent).toBe('false')
    expect(box).toHaveValue('@b')
  })

  it('reopens the list once the user keeps typing after dismissing it', async () => {
    const box = await openPicker()
    fireEvent.keyDown(box, { key: 'Escape' })
    fireEvent.change(box, { target: { value: '@br' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MENTION_DEBOUNCE_MS)
    })

    expect(screen.getByTestId('open').textContent).toBe('true')
  })

  it('passes ordinary keys through to the composer', async () => {
    const box = await openPicker()
    expect(screen.getByTestId('open').textContent).toBe('true')
    // A key the picker does not own must not be swallowed.
    fireEvent.keyDown(box, { key: 'a' })
    expect(screen.getByTestId('open').textContent).toBe('true')
  })
})
