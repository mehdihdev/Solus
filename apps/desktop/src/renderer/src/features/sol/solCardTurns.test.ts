// SOLUSDEV-326 P3: the turns the Hardware surface starts, asserted on the request body that leaves
// the renderer. Whatever the shared Guide/Build toggle says, every one of them — typed, notice,
// answer, the resume after a card — goes as action_mode "do" with force_confirmation true.
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Card } from '@solus/shared-types'
import { ConfirmationRefused, decideSolConfirmation } from '../../lib/api/resources'
import type { PendingConfirmation } from '../../lib/api/solStream'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useShellStore } from '../workspace/shellStore'
import {
  resetSolChatSessions,
  selectSession,
  setForceConfirmation,
  useSolChatStore,
  type ChatItem
} from './solChatStore'
import { useSolSessionStore } from './solSessionStore'
import { useSolSidebarStore } from './sidebar/solSidebarStore'
import { useSolChat, type SolSurface } from './useSolChat'

vi.mock('./solApi', async (original) => ({
  ...(await original<typeof import('./solApi')>()),
  listSolTurns: vi.fn().mockResolvedValue([]),
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn().mockResolvedValue({ id: 'c' })
}))
vi.mock('../../lib/api/resources', async (original) => ({
  ...(await original<typeof import('../../lib/api/resources')>()),
  decideSolConfirmation: vi.fn()
}))
vi.mock('../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))

const decide = vi.mocked(decideSolConfirmation)
const fetchMock = vi.fn()

const ok = (): Response =>
  ({
    ok: true,
    status: 200,
    body: new ReadableStream<Uint8Array>({ start: (c) => c.close() })
  }) as unknown as Response
const refused = (status: number, code: string): Response =>
  ({
    ok: false,
    status,
    body: null,
    text: async () => JSON.stringify({ error: { code, message: code } })
  }) as unknown as Response

interface Sent {
  url: string
  body: Record<string, unknown>
}
const sent = (): Sent[] =>
  fetchMock.mock.calls.map(([url, init]) => ({
    url: String(url),
    body: JSON.parse((init as RequestInit).body as string) as Record<string, unknown>
  }))

const CARD: Card = {
  kind: 'offer',
  title: 'Found: 3 servos',
  body: 'They match arm.yaml.',
  more: null,
  field: null,
  primary: 'Add',
  secondary: 'Not now',
  receipt: '3 servos added',
  resumes: true
}
const row = (id: string, tool: string, card?: Card): PendingConfirmation => ({
  confirmationId: id,
  tool,
  summary: tool,
  preview: [],
  ...(card ? { card } : {})
})

function seed(...confirmations: PendingConfirmation[]): void {
  const item: ChatItem = {
    id: 'local-a',
    role: 'assistant',
    content: 'Here.',
    citations: [],
    trace: [],
    pending: false,
    error: null,
    confirmations,
    artifacts: []
  }
  useSolChatStore.setState({
    sessions: {
      p: {
        conversationId: 'c',
        items: [item],
        contextUsed: null,
        creditsExhausted: false,
        streaming: false,
        status: 'ready'
      }
    }
  })
}

const items = (): readonly ChatItem[] => selectSession(useSolChatStore.getState(), 'p').items
const chatOn = (surface?: SolSurface): { current: ReturnType<typeof useSolChat> } =>
  renderHook(() => useSolChat('p', surface)).result
const FORCED = { action_mode: 'do', force_confirmation: true }
const tick = (): Promise<void> => act(async () => void (await new Promise((r) => setTimeout(r))))

beforeEach(() => {
  vi.clearAllMocks()
  resetSolChatSessions()
  useShellStore.getState().reset()
  useWorkspaceStore.setState({ project: null })
  useSolSessionStore.setState({ conversationByProject: { p: 'c' }, streaming: false })
  fetchMock.mockReset().mockImplementation(async () => ok())
  vi.stubGlobal('fetch', fetchMock)
  decide.mockResolvedValue({ ok: true, value: {} } as Awaited<ReturnType<typeof decide>>)
})

describe('the Hardware surface forces Build with confirmation', () => {
  it('on a typed message sent as Guide', async () => {
    const chat = chatOn('hardware')
    await act(async () => void (await chat.current.send('I have an arm', 'guide')))
    expect(sent()[0].body).toMatchObject({ content: 'I have an arm', ...FORCED })
  })

  it('on a device notice, which carries no words', async () => {
    const chat = chatOn('hardware')
    await act(async () => void (await chat.current.sendNotice('usb:5B42')))
    expect(sent()[0].body).toEqual({
      notice: { kind: 'device', device_ref: 'usb:5B42' },
      ...FORCED
    })
  })

  it('on an answer, posted to the conversation the card was asked in, never to the decide route', async () => {
    seed(row('q1', 'ask_user', { ...CARD, primary: 'Yes', secondary: 'No' }))
    const chat = chatOn('hardware')
    await act(async () => void (await chat.current.answer('q1', 0, 'Rover arm', 'conv2')))
    const [turn] = sent()
    expect(turn.url).toContain('/conversations/conv2/messages')
    expect(turn.body).toEqual({
      answer: { question_id: 'q1', choice: 0, text: 'Rover arm' },
      ...FORCED
    })
    expect(decide).not.toHaveBeenCalled()
    expect(useSolSessionStore.getState().conversationByProject.p).toBe('conv2')
  })

  it('on the resume after a card, in the card’s own conversation', async () => {
    const chat = chatOn('hardware')
    await act(() => chat.current.resumeCard({ confirmation_id: 'k1', conversation_id: 'conv2' }))
    const [turn] = sent()
    expect(turn.url).toContain('/conversations/conv2/messages')
    expect(turn.body).toEqual({ resume_confirmation_id: 'k1', mentions: [], ...FORCED })
  })

  it('on the resume after a card decided in the thread', async () => {
    seed(row('k1', 'hardware.add_parts', CARD))
    const chat = chatOn('hardware')
    await act(() => chat.current.decide('k1', 'reject', 'guide'))
    await waitFor(() => expect(sent()).toHaveLength(1))
    expect(sent()[0].body).toMatchObject({ resume_confirmation_id: 'k1', ...FORCED })
  })
})

describe('every other surface keeps the shared toggle', () => {
  it('sends Guide as Guide, with no forced confirmation', async () => {
    const chat = chatOn()
    await act(async () => void (await chat.current.send('hello', 'guide')))
    expect(sent()[0].body.action_mode).toBe('guide')
    expect(sent()[0].body).not.toHaveProperty('force_confirmation')
  })
})

describe('an answer off the Hardware surface follows the shared mode and the session’s choice', () => {
  const QUESTION = row('q1', 'ask_user', { ...CARD, primary: 'Yes', secondary: 'No' })

  it('goes as Guide when the caller is in Guide, and as Guide when no mode is given', async () => {
    for (const mode of ['guide', undefined] as const) {
      fetchMock.mockClear()
      seed(QUESTION)
      const chat = chatOn()
      await act(async () => void (await chat.current.answer('q1', 0, undefined, undefined, mode)))
      expect(sent()[0].body.action_mode).toBe('guide')
    }
  })

  it('carries Confirm every change, so Build never runs unasked', async () => {
    seed(QUESTION)
    setForceConfirmation('p', true)
    const chat = chatOn()
    await act(async () => void (await chat.current.answer('q1', 0, undefined, undefined, 'do')))
    expect(sent()[0].body).toMatchObject({ action_mode: 'do', force_confirmation: true })
  })

  it('a notice carries the session’s Confirm every change too', async () => {
    seed()
    setForceConfirmation('p', true)
    const chat = chatOn()
    await act(async () => void (await chat.current.sendNotice('usb:5B42')))
    expect(sent()[0].body.force_confirmation).toBe(true)
  })
})

describe('one live turn per project', () => {
  /** A fetch per call that stays open until released. */
  function gated(): { release: (index: number) => void; signal: (index: number) => AbortSignal } {
    const releases: Array<(response: Response) => void> = []
    fetchMock.mockImplementation(
      () => new Promise<Response>((resolve) => void releases.push(resolve))
    )
    return {
      release: (index) => releases[index](ok()),
      signal: (index) => (fetchMock.mock.calls[index][1] as RequestInit).signal as AbortSignal
    }
  }

  it('two notices queued behind a live turn go one after the other', async () => {
    const net = gated()
    const chat = chatOn('hardware')
    act(() => void chat.current.send('hello', 'do'))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    act(() => {
      void chat.current.sendNotice('usb:A')
      void chat.current.sendNotice('usb:B')
    })
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    net.release(0)
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    net.release(1)
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(sent().map((turn) => turn.body.notice)).toEqual([
      undefined,
      { kind: 'device', device_ref: 'usb:A' },
      { kind: 'device', device_ref: 'usb:B' }
    ])
    net.release(2)
    await tick()
    expect(selectSession(useSolChatStore.getState(), 'p').streaming).toBe(false)
  })

  it('a resume and a notice queued behind a live turn go one after the other', async () => {
    const net = gated()
    const chat = chatOn('hardware')
    act(() => void chat.current.send('hello', 'do'))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    act(() => {
      void chat.current.resumeCard({ confirmation_id: 'k1', conversation_id: 'c' })
      void chat.current.sendNotice('usb:B')
    })
    net.release(0)
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    net.release(1)
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(3)
    net.release(2)
    await tick()
  })

  it('a resumes card approved in the thread during a live turn resumes once, after that turn settles', async () => {
    const net = gated()
    seed(row('k1', 'hardware.add_parts', CARD))
    const chat = chatOn()
    act(() => void chat.current.send('hello', 'do'))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    await act(() => chat.current.decide('k1', 'approve', 'do'))
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    net.release(0)
    await tick()
    expect(sent().map((turn) => turn.body.resume_confirmation_id)).toEqual([undefined, 'k1'])
    net.release(1)
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('a thread resume waiting behind a live turn is dropped when the person opens another chat', async () => {
    const net = gated()
    seed(row('k1', 'hardware.add_parts', CARD))
    const chat = chatOn()
    act(() => void chat.current.send('hello', 'do'))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    await act(() => chat.current.decide('k1', 'approve', 'do'))
    act(() => chat.current.selectConversation('other'))
    await tick()
    expect(net.signal(0).aborted).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(useSolSessionStore.getState().conversationByProject.p).toBe('other')
  })

  it('a notice, an answer and a resume queued behind a live turn never start after a sign-out', async () => {
    gated()
    seed(row('q1', 'ask_user', { ...CARD, primary: 'Yes', secondary: 'No' }))
    const chat = chatOn('hardware')
    act(() => void chat.current.send('hello', 'do'))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const queued: Promise<unknown>[] = []
    act(() => {
      queued.push(chat.current.sendNotice('usb:A'))
      queued.push(chat.current.answer('q1', 0, undefined, 'conv2'))
      queued.push(chat.current.resumeCard({ confirmation_id: 'k1', conversation_id: 'conv3' }))
    })
    act(() => resetSolChatSessions())
    await tick()
    expect(await Promise.all(queued)).toEqual([false, false, undefined])
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(useSolSessionStore.getState().conversationByProject.p).toBe('c')
    expect(selectSession(useSolChatStore.getState(), 'p').items).toEqual([])
  })

  it('an answer for another conversation waits for the live reply; it never cuts it off', async () => {
    const net = gated()
    seed(row('q1', 'ask_user', { ...CARD, primary: 'Yes', secondary: 'No' }))
    const chat = chatOn('hardware')
    act(() => void chat.current.send('hello', 'do'))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    act(() => void chat.current.answer('q1', 0, undefined, 'conv2'))
    await tick()
    expect(net.signal(0).aborted).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(useSolSessionStore.getState().conversationByProject.p).toBe('c')
    net.release(0)
    await tick()
    expect(net.signal(0).aborted).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(sent()[1].url).toContain('/conversations/conv2/messages')
    net.release(1)
    await tick()
  })

  it('a typed Hardware-surface send behind a live turn waits and goes after it; it is never dropped', async () => {
    const net = gated()
    const chat = chatOn('hardware')
    act(() => void chat.current.sendNotice('usb:A'))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    let typed: Promise<boolean> = Promise.resolve(false)
    act(() => {
      typed = chat.current.send('Connect a robot computer', 'do')
    })
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(net.signal(0).aborted).toBe(false)
    net.release(0)
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(sent()[1].body).toMatchObject({ content: 'Connect a robot computer', ...FORCED })
    net.release(1)
    await tick()
    expect(await typed).toBe(true)
    expect(items().some((m) => m.role === 'user' && m.content === 'Connect a robot computer')).toBe(
      true
    )
  })

  it('a second send while the first is still opening its conversation is refused', async () => {
    useSolSessionStore.setState({ conversationByProject: {}, streaming: false })
    const chat = chatOn()
    let second = true
    await act(async () => {
      const first = chat.current.send('one', 'guide')
      second = await chat.current.send('two', 'guide')
      await first
    })
    expect(second).toBe(false)
    expect(sent()).toHaveLength(1)
  })
})

describe('resume after a card', () => {
  it('an approved command resumes only when the server’s list admits a resume after it', async () => {
    seed(row('k1', 'code.run'), row('k2', 'code.process_input'))
    const chat = chatOn()
    await act(() => chat.current.decide('k1', 'approve', 'do'))
    await waitFor(() => expect(sent()).toHaveLength(1))
    await act(() => chat.current.decide('k2', 'approve', 'do'))
    await tick()
    expect(sent().map((turn) => turn.body.resume_confirmation_id)).toEqual(['k1'])
  })

  it('follows the server-sent resumes flag on approve and on reject', async () => {
    for (const decision of ['approve', 'reject'] as const) {
      fetchMock.mockClear()
      seed(row('k1', 'hardware.add_parts', CARD))
      const chat = chatOn()
      await act(() => chat.current.decide('k1', decision, 'do'))
      await waitFor(() => expect(sent()).toHaveLength(1))
      expect(sent()[0].body).toMatchObject({ resume_confirmation_id: 'k1', action_mode: 'do' })
    }
  })

  it('follows it when the server refused the decision (stale, expired)', async () => {
    decide.mockRejectedValue(new ConfirmationRefused('This action expired.', 'expired'))
    seed(row('k1', 'hardware.add_parts', CARD))
    const chat = chatOn()
    await act(async () => {
      await expect(chat.current.decide('k1', 'approve', 'do')).rejects.toThrow('expired')
    })
    await waitFor(() => expect(sent()).toHaveLength(1))
  })

  it('never follows a card whose flag is off, or a rejected row with no card', async () => {
    seed(row('k1', 'hardware.add_parts', { ...CARD, resumes: false }), row('k2', 'onshape.x'))
    const chat = chatOn()
    await act(() => chat.current.decide('k1', 'approve', 'do'))
    await act(() => chat.current.decide('k2', 'reject', 'do'))
    expect(sent()).toHaveLength(0)
  })
})

describe('Solus-written turns in the transcript', () => {
  const bubbles = (): string[] =>
    items()
      .filter((m) => m.role === 'user')
      .map((m) => m.content)

  it('an answer reads as the server stores it — the label quoted as data — and takes the question out', async () => {
    seed(row('q1', 'ask_user', { ...CARD, primary: 'Yes, 6 servos', secondary: 'No' }))
    const chat = chatOn()
    await act(async () => void (await chat.current.answer('q1', 0)))
    expect(items().flatMap((m) => m.confirmations)).toEqual([])
    expect(bubbles()).toEqual(['Chose "Yes, 6 servos"'])
  })

  it('an answer with typed text, and one to a card with no secondary, match the server’s words', async () => {
    seed(
      row('q1', 'ask_user', { ...CARD, primary: 'Use "this"', secondary: 'No' }),
      row('q2', 'ask_user', { ...CARD, primary: 'OK', secondary: null })
    )
    const chat = chatOn()
    await act(async () => void (await chat.current.answer('q1', 0, 'Scout')))
    await act(async () => void (await chat.current.answer('q2', 1)))
    expect(bubbles()).toEqual(['Chose "Use \\"this\\"" — Scout', 'Chose "Not now"'])
  })

  it('an answer that never reached SOL leaves the question where it was', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    seed(row('q1', 'ask_user', { ...CARD, primary: 'Yes', secondary: 'No' }))
    const chat = chatOn()
    let accepted = true
    await act(async () => void (accepted = await chat.current.answer('q1', 0)))
    expect(accepted).toBe(false)
    expect(items()[0].confirmations.map((c) => c.confirmationId)).toEqual(['q1'])
  })

  it('the last answered question takes a restored "Awaiting your approval" row with it', async () => {
    seed(row('q1', 'ask_user', { ...CARD, primary: 'Yes', secondary: 'No' }))
    useSolChatStore.setState((state) => ({
      sessions: {
        p: {
          ...state.sessions.p,
          items: [
            { ...state.sessions.p.items[0], id: 'approvals-c', content: 'Awaiting your approval' }
          ]
        }
      }
    }))
    const chat = chatOn()
    await act(async () => void (await chat.current.answer('q1', 0)))
    expect(items().some((m) => m.content === 'Awaiting your approval')).toBe(false)
  })

  it('a notice waits for the live turn to settle instead of being dropped', async () => {
    let release: (response: Response) => void = () => undefined
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => (release = resolve)))
    const chat = chatOn('hardware')
    let first: Promise<boolean> = Promise.resolve(false)
    act(() => {
      first = chat.current.send('hello', 'do')
    })
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    let notice: Promise<boolean> = Promise.resolve(false)
    await act(async () => {
      notice = chat.current.sendNotice('usb:5B42')
      await Promise.resolve()
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => {
      release(ok())
      await first
      await notice
    })
    expect(sent()[1].body).toMatchObject({ notice: { kind: 'device', device_ref: 'usb:5B42' } })
  })

  it('a notice the server debounced leaves nothing behind', async () => {
    fetchMock.mockImplementation(async () => refused(409, 'notice_debounced'))
    const chat = chatOn('hardware')
    await act(async () => void (await chat.current.sendNotice('usb:5B42')))
    expect(items()).toEqual([])
  })
  it('a notice for a device that has gone leaves nothing behind either', async () => {
    fetchMock.mockImplementation(async () => refused(422, 'validation_error'))
    const chat = chatOn('hardware')
    await act(async () => void (await chat.current.sendNotice('usb:5B42')))
    expect(items()).toEqual([])
  })

  it('a notice that went through leaves a Solus line before SOL’s reply, never a bubble of the person’s', async () => {
    const chat = chatOn('hardware')
    await act(async () => void (await chat.current.sendNotice('usb:5B42')))
    expect(items().map((m) => [m.role, m.kind, m.content])).toEqual([
      ['user', 'notice', 'Solus told SOL about a device plugged into this computer.'],
      ['assistant', undefined, '']
    ])
  })

  it('an answer is marked as one, so it draws as a receipt and not as typed words', async () => {
    seed(row('q1', 'ask_user', { ...CARD, primary: 'Yes', secondary: 'No' }))
    const chat = chatOn()
    await act(async () => void (await chat.current.answer('q1', 0)))
    expect(items().find((m) => m.role === 'user')?.kind).toBe('answer')
  })

  it('a typed turn the server refuses with 422 still says so', async () => {
    fetchMock.mockImplementation(async () => refused(422, 'validation_error'))
    const chat = chatOn('hardware')
    await act(async () => void (await chat.current.send('hello', 'do')))
    expect(items().some((m) => m.error)).toBe(true)
  })
})

describe('the away toast', () => {
  const finishTurnOnHardware = async (sidebarOpen: boolean): Promise<void> => {
    useWorkspaceStore.setState({ project: { id: 'p' } as never })
    useShellStore.setState({ lastMain: 'hardware', toast: null })
    useSolSidebarStore.getState().setOpen(sidebarOpen)
    const chat = chatOn('hardware')
    await act(async () => void (await chat.current.send('hello', 'do')))
  }

  it('stays down on the Hardware screen while the SOL sidebar is open: it shows the reply', async () => {
    await finishTurnOnHardware(true)
    expect(useShellStore.getState().toast).toBeNull()
  })

  it('rises on the Hardware screen with the sidebar closed', async () => {
    await finishTurnOnHardware(false)
    expect(useShellStore.getState().toast).not.toBeNull()
  })
})
