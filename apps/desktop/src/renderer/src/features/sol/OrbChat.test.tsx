// SOLX-02: the chat surface. Pins the SOL-02 security obligations — citations
// render from the STRUCTURED array in a dedicated region, never linkified,
// display-capped; the tool trace shows names + ok/error, never raw args — and
// the guide/do toggle posting action_mode.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react'
import * as solApi from './solApi'
import * as resources from '../../lib/api/resources'
import { useOrbStore } from './orbStore'
import { resetSolChatSessions } from './solChatStore'
import { OrbChat } from './OrbChat'

vi.mock('./solApi', () => ({
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  // Spread the real module so genuinely-shared values (the
  // `ConfirmationRefused` error class) are not silently undefined here.
  ...(await importOriginal<typeof resources>()),
  classifyQuery: vi.fn(),
  decideSolConfirmation: vi.fn(),
  listEntities: vi.fn()
}))
const createSolConversation = vi.mocked(solApi.createSolConversation)
const listSolTurns = vi.mocked(solApi.listSolTurns)
const streamSolMessage = vi.mocked(solApi.streamSolMessage)
const classifyQuery = vi.mocked(resources.classifyQuery)
const decideSolConfirmation = vi.mocked(resources.decideSolConfirmation)
const listEntities = vi.mocked(resources.listEntities)

const LONG_CITATION = `entity:${'x'.repeat(90)}`

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  // Sessions outlive components (SOLUSDEV-233) — reset the singleton per test.
  resetSolChatSessions()
  useOrbStore.setState({
    corner: 'br',
    expanded: false,
    detached: false,
    streaming: false,
    conversationByProject: {}
  })
  createSolConversation.mockResolvedValue({ id: 'c1' } as solApi.SolConversation)
  listSolTurns.mockResolvedValue([])
  classifyQuery.mockReturnValue(new Promise(() => undefined))
})

function sendMessage(text: string): void {
  fireEvent.change(screen.getByPlaceholderText('Ask about a signal, a change, a part…'), {
    target: { value: text }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
}

// CTR-03 / CLAUDE.md §7: a destructive action must be shown and approved before
// it runs. LANE C's orb chat had no confirmation path at all, so the backend
// could park an action this surface never rendered — invisible to every test
// because ConfirmationCard's own suite renders it directly.
describe('OrbChat destructive-action approval', () => {
  it('shows a parked action with its diff, inline in the conversation', async () => {
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({
        type: 'tool_confirmation',
        pending: {
          confirmationId: 'cf1',
          tool: 'onshape.set_variable',
          summary: 'Set WIDTH to 120 mm',
          preview: [{ label: 'WIDTH', before: '100 mm', after: '120 mm' }]
        }
      })
    })
    render(<OrbChat projectId="p1" />)
    sendMessage('make it wider')
    const card = await screen.findByLabelText('Action needs your approval')
    expect(within(card).getByText('WIDTH')).toBeInTheDocument()
    expect(within(card).getByText('100 mm')).toBeInTheDocument()
    expect(within(card).getByText('120 mm')).toBeInTheDocument()
  })

  it('records an approval and clears the card', async () => {
    decideSolConfirmation.mockResolvedValue({ ok: true } as Awaited<
      ReturnType<typeof resources.decideSolConfirmation>
    >)
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({
        type: 'tool_confirmation',
        pending: {
          confirmationId: 'cf1',
          tool: 'onshape.set_variable',
          summary: 'Set WIDTH to 120 mm',
          preview: []
        }
      })
    })
    render(<OrbChat projectId="p1" />)
    sendMessage('make it wider')
    const card = await screen.findByLabelText('Action needs your approval')
    await act(async () => {
      fireEvent.click(within(card).getByRole('button', { name: 'Approve' }))
    })
    // The decision names the confirmation only — the arguments that execute are
    // the stored server-side ones the user was shown, never re-sent from here.
    expect(decideSolConfirmation).toHaveBeenCalledWith('p1', 'cf1', 'approve')
    await waitFor(() =>
      expect(screen.queryByLabelText('Action needs your approval')).not.toBeInTheDocument()
    )
  })

  it('keeps the card, with the server reason, when the decision fails', async () => {
    // The action really is still parked, so removing the card would strand it:
    // the user could no longer approve what the server is still holding.
    decideSolConfirmation.mockRejectedValue(new Error('That confirmation has expired.'))
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({
        type: 'tool_confirmation',
        pending: {
          confirmationId: 'cf1',
          tool: 'onshape.set_variable',
          summary: 'Set WIDTH to 120 mm',
          preview: []
        }
      })
    })
    render(<OrbChat projectId="p1" />)
    sendMessage('make it wider')
    const card = await screen.findByLabelText('Action needs your approval')
    await act(async () => {
      fireEvent.click(within(card).getByRole('button', { name: 'Approve' }))
    })
    expect(screen.getByLabelText('Action needs your approval')).toBeInTheDocument()
    expect(screen.getByText(/That confirmation has expired/)).toBeInTheDocument()
  })
})

describe('OrbChat basics', () => {
  it('asks for a project when none is open — no input rendered', () => {
    render(<OrbChat projectId={null} />)
    expect(screen.getByText(/Open a project to chat with SOL/)).toBeInTheDocument()
    expect(
      screen.queryByPlaceholderText('Ask about a signal, a change, a part…')
    ).not.toBeInTheDocument()
  })

  it('renders the composer and loads per-project history', async () => {
    useOrbStore.getState().setConversation('p1', 'c1')
    listSolTurns.mockResolvedValue([
      {
        id: 't1',
        conversation_id: 'c1',
        role: 'user',
        content: 'earlier question',
        attrs: {},
        created_at: ''
      }
    ])
    render(<OrbChat projectId="p1" />)
    expect(screen.getByPlaceholderText('Ask about a signal, a change, a part…')).toBeInTheDocument()
    expect(await screen.findByText('earlier question')).toBeInTheDocument()
    expect(listSolTurns).toHaveBeenCalledWith('p1', 'c1')
  })
})

describe('OrbChat streaming render (SOL-02 obligations)', () => {
  it('renders streamed tokens progressively, then citations in a dedicated non-link region, capped', async () => {
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'token', text: 'The IMU ' })
      onEvent({ type: 'token', text: 'shares the bus.' })
      onEvent({
        type: 'message',
        role: 'assistant',
        content: 'The IMU shares the bus. See https://example.com/x',
        citations: ['entity:imu_bno085', LONG_CITATION]
      })
      onEvent({ type: 'done', conversationId: 'c1', turnId: 't1' })
    })
    render(<OrbChat projectId="p1" />)
    sendMessage('why?')
    await waitFor(() => expect(screen.getByText(/shares the bus/)).toBeInTheDocument())
    const region = screen.getByTestId('citations-region')
    // Structured tokens only, never anchors — even when prose contains a URL.
    expect(within(region).queryAllByRole('link')).toEqual([])
    expect(screen.queryAllByRole('link')).toEqual([])
    expect(within(region).getByText('entity:imu_bno085')).toBeInTheDocument()
    const capped = within(region).getByText(/^entity:x+…$/)
    expect(capped.textContent?.length).toBeLessThanOrEqual(64)
    // Citations come only from the structured array, never parsed out of prose.
    expect(within(region).queryByText(/example\.com/)).not.toBeInTheDocument()
  })

  it('collapses the tool trace to names + outcomes, never raw args', async () => {
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'tool_call', callId: 'k1', tool: 'get_entity' })
      onEvent({ type: 'tool_result', callId: 'k1', ok: true, errorCode: null })
      onEvent({ type: 'tool_call', callId: 'k2', tool: 'run_checker' })
      onEvent({ type: 'tool_result', callId: 'k2', ok: false, errorCode: 'not_found' })
      onEvent({ type: 'message', role: 'assistant', content: 'Done.', citations: [] })
    })
    render(<OrbChat projectId="p1" />)
    sendMessage('check it')
    await waitFor(() => expect(screen.getByTestId('tool-trace')).toBeInTheDocument())
    const trace = screen.getByTestId('tool-trace')
    expect(within(trace).getByText('2 tool steps')).toBeInTheDocument()
    // Arrow format matches the backend's persisted tool turns (SOLUSDEV-233).
    expect(within(trace).getByText(/get_entity → ok/)).toBeInTheDocument()
    expect(within(trace).getByText(/run_checker → not_found/)).toBeInTheDocument()
    expect(trace).not.toHaveAttribute('open')
  })

  it('shows the author-safe error frame text', async () => {
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'error', code: 'timeout', message: 'The SOL turn timed out.' })
    })
    render(<OrbChat projectId="p1" />)
    sendMessage('hi')
    expect(await screen.findByText('The SOL turn timed out.')).toBeInTheDocument()
  })
})

describe('OrbChat auto-scroll', () => {
  // jsdom has no layout: scrollHeight/clientHeight are always 0 and no test can
  // measure pixels. Stub the geometry on HTMLElement.prototype (shadowing
  // jsdom's Element accessors) and record scrollTop assignments instead.
  function stubScrollGeometry(): { pins: number[]; restore: () => void } {
    const proto = window.HTMLElement.prototype
    const pins: number[] = []
    Object.defineProperty(proto, 'scrollHeight', { configurable: true, get: () => 1000 })
    Object.defineProperty(proto, 'clientHeight', { configurable: true, get: () => 200 })
    Object.defineProperty(proto, 'scrollTop', {
      configurable: true,
      get: () => 0,
      set: (v: number) => {
        pins.push(v)
      }
    })
    return {
      pins,
      restore: () => {
        delete (proto as { scrollHeight?: unknown }).scrollHeight
        delete (proto as { clientHeight?: unknown }).clientHeight
        delete (proto as { scrollTop?: unknown }).scrollTop
      }
    }
  }

  it('follows the stream to the bottom as tokens grow a message in place', async () => {
    // The regression this pins: token events mutate one item's CONTENT without
    // changing the item COUNT, so a count-keyed effect never scrolls mid-stream
    // and the reply runs off-screen.
    const { pins, restore } = stubScrollGeometry()
    try {
      let emit:
        | ((e: Parameters<Parameters<typeof streamSolMessage>[0]['onEvent']>[0]) => void)
        | null = null
      streamSolMessage.mockImplementation(async ({ onEvent }) => {
        emit = onEvent
      })
      render(<OrbChat projectId="p1" />)
      sendMessage('why?')
      await waitFor(() => expect(emit).not.toBeNull())
      const pinsAfterSend = pins.length
      expect(pinsAfterSend).toBeGreaterThan(0) // the send itself pinned to bottom
      await act(async () => {
        emit?.({ type: 'token', text: 'a long streamed line ' })
      })
      await act(async () => {
        emit?.({ type: 'token', text: 'and another one' })
      })
      // Each token growth re-pinned the list (count never changed).
      expect(pins.length).toBeGreaterThan(pinsAfterSend)
      expect(pins.every((v) => v === 1000)).toBe(true)
    } finally {
      restore()
    }
  })

  it('stops following when the user scrolls up to read, and resumes on a new row', async () => {
    const { pins, restore } = stubScrollGeometry()
    try {
      let emit:
        | ((e: Parameters<Parameters<typeof streamSolMessage>[0]['onEvent']>[0]) => void)
        | null = null
      streamSolMessage.mockImplementation(async ({ onEvent }) => {
        emit = onEvent
      })
      render(<OrbChat projectId="p1" />)
      sendMessage('why?')
      await waitFor(() => expect(emit).not.toBeNull())
      // scrollTop reads 0 from the stub, so the list believes the user is
      // 1000-0-200 = 800px above the bottom — far beyond the follow slack.
      const list = screen.getByText('thinking…').parentElement?.parentElement as HTMLElement
      fireEvent.scroll(list)
      const pinned = pins.length
      await act(async () => {
        emit?.({ type: 'token', text: 'more text' })
      })
      expect(pins.length).toBe(pinned) // reading position respected — no yank
      await act(async () => {
        emit?.({ type: 'message', role: 'assistant', content: 'done', citations: [] })
        emit?.({ type: 'done', conversationId: 'c1', turnId: 't1' })
      })
      sendMessage('follow up')
      // A new row re-engages follow.
      await waitFor(() => expect(pins.length).toBeGreaterThan(pinned))
    } finally {
      restore()
    }
  })
})

describe('OrbChat composer', () => {
  it('posts action_mode from the guide/do toggle and clears the input after send', async () => {
    streamSolMessage.mockResolvedValue(undefined)
    render(<OrbChat projectId="p1" />)
    fireEvent.click(screen.getByRole('radio', { name: 'Do' }))
    sendMessage('flash the board')
    await waitFor(() =>
      expect(streamSolMessage).toHaveBeenCalledWith(
        expect.objectContaining({ actionMode: 'do', content: 'flash the board' })
      )
    )
    expect(screen.getByPlaceholderText('Ask about a signal, a change, a part…')).toHaveValue('')
    // The toggle sticks for the panel instance rather than resetting per send.
    expect(screen.getByRole('radio', { name: 'Do' })).toHaveAttribute('aria-checked', 'true')
  })

  it('defaults to Do, so a mutating ask parks for approval instead of being refused', async () => {
    // Guide refuses exactly the tools whose descriptor sets
    // `requires_confirmation` (agent/modes.py) — precisely the set the CTR-03
    // gate already parks. So defaulting to Guide added no safety: it replaced an
    // approval card the user could act on with "switch to Do mode to operate the
    // tool". The gate is unchanged and still parks every mutation; only the
    // client default moves. `MessageCreate.action_mode` stays GUIDE for every
    // non-UI caller.
    streamSolMessage.mockResolvedValue(undefined)
    render(<OrbChat projectId="p1" />)

    expect(screen.getByRole('radio', { name: 'Do' })).toHaveAttribute('aria-checked', 'true')

    sendMessage('rename the mounting sketch')
    await waitFor(() =>
      expect(streamSolMessage).toHaveBeenCalledWith(expect.objectContaining({ actionMode: 'do' }))
    )
  })

  it('sends the ids of @-mentioned entities alongside the text', async () => {
    // SOLUSDEV-168. The point of the `@` is that the user can name ONE node at
    // any depth, from any integration, instead of hoping similarity search
    // guesses which "bracket" they meant. The id travels beside the prose, so
    // the composer's trim() and any later edit cannot invalidate an offset.
    streamSolMessage.mockResolvedValue(undefined)
    listEntities.mockResolvedValue([
      { id: 'e-1', name: 'Camera Bracket', type: 'part', domain: 'mechanical', source_key: 'k1' }
    ])
    vi.useFakeTimers()
    try {
      render(<OrbChat projectId="p1" />)
      const box = screen.getByPlaceholderText('Ask about a signal, a change, a part…')

      fireEvent.change(box, { target: { value: 'will @cam' } })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(400)
      })
      expect(listEntities).toHaveBeenCalledWith('p1', { q: 'cam', limit: 8 })

      fireEvent.mouseDown(screen.getByRole('option', { name: /Camera Bracket/ }))
      expect(box).toHaveValue('will @Camera Bracket ')

      fireEvent.click(screen.getByRole('button', { name: 'Send' }))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
    } finally {
      vi.useRealTimers()
    }

    expect(streamSolMessage).toHaveBeenCalledWith(
      expect.objectContaining({ content: 'will @Camera Bracket', mentions: ['e-1'] })
    )
  })

  it('drops a mention the user deleted before sending', async () => {
    // The id list is not the source of truth — the surviving `@Name` in the text
    // is. Otherwise deleting a mention would still ground SOL on it.
    streamSolMessage.mockResolvedValue(undefined)
    listEntities.mockResolvedValue([
      { id: 'e-1', name: 'Camera Bracket', type: 'part', domain: 'mechanical', source_key: 'k1' }
    ])
    vi.useFakeTimers()
    try {
      render(<OrbChat projectId="p1" />)
      const box = screen.getByPlaceholderText('Ask about a signal, a change, a part…')
      fireEvent.change(box, { target: { value: 'will @cam' } })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(400)
      })
      fireEvent.mouseDown(screen.getByRole('option', { name: /Camera Bracket/ }))

      // The user changes their mind and rewrites the question.
      fireEvent.change(box, { target: { value: 'never mind, why is the IMU noisy' } })
      fireEvent.click(screen.getByRole('button', { name: 'Send' }))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
    } finally {
      vi.useRealTimers()
    }

    expect(streamSolMessage).toHaveBeenCalledWith(expect.objectContaining({ mentions: [] }))
  })

  it('does not open the picker for an email address', async () => {
    listEntities.mockResolvedValue([])
    vi.useFakeTimers()
    try {
      render(<OrbChat projectId="p1" />)
      fireEvent.change(screen.getByPlaceholderText('Ask about a signal, a change, a part…'), {
        target: { value: 'ask maya@example.com' }
      })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(400)
      })
    } finally {
      vi.useRealTimers()
    }

    expect(listEntities).not.toHaveBeenCalled()
    expect(screen.queryByRole('listbox', { name: 'Graph entities' })).not.toBeInTheDocument()
  })

  it('still lets the user drop back to Guide for an explain-only turn', async () => {
    streamSolMessage.mockResolvedValue(undefined)
    render(<OrbChat projectId="p1" />)
    fireEvent.click(screen.getByRole('radio', { name: 'Guide' }))

    sendMessage('what would changing this break')

    await waitFor(() =>
      expect(streamSolMessage).toHaveBeenCalledWith(
        expect.objectContaining({ actionMode: 'guide' })
      )
    )
  })

  it('wires the classify preview onto the input (debounced, never per keystroke)', async () => {
    vi.useFakeTimers()
    try {
      render(<OrbChat projectId="p1" />)
      fireEvent.change(screen.getByPlaceholderText('Ask about a signal, a change, a part…'), {
        target: { value: 'why is the IMU noisy' }
      })
      expect(classifyQuery).not.toHaveBeenCalled()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(400)
      })
      expect(classifyQuery).toHaveBeenCalledWith({ query: 'why is the IMU noisy' })
    } finally {
      vi.useRealTimers()
    }
  })
})
