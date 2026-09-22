// SOLUSDEV-233: SOL chat sessions outlive the page — background completion,
// the away toast, and sign-out teardown.
import { act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as solApi from './solApi'
import * as resources from '../../lib/api/resources'
import type { SolStreamEvent } from './solStream'
import { useAuthStore } from '../../store/authStore'
import { useShellStore } from '../workspace/shellStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSolSessionStore } from './solSessionStore'
import {
  fileArtifact,
  flushPendingTokens,
  resetSolChatSessions,
  selectConversation,
  selectSession,
  sendMessage,
  syncSession,
  useSolChatStore
} from './solChatStore'

vi.mock('../preferences/preferencesStore', () => ({
  preferencesForTurn: vi.fn(async () => ({
    schema_version: 1,
    freeText: '',
    codeStyle: '',
    mechanical: '',
    electrical: 'XT30 for power.',
    documentation: '',
    unitsStandards: ''
  }))
}))
vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn(),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof resources>()),
  addSolusEntry: vi.fn()
}))
const streamSolMessage = vi.mocked(solApi.streamSolMessage)
const addSolusEntry = vi.mocked(resources.addSolusEntry)

function messageEvent(content: string): SolStreamEvent {
  return { type: 'message', role: 'assistant', content, citations: [] }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useShellStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
})

describe('engineering preferences ride along (SOLUSDEV-244)', () => {
  it('passes the loaded document to every turn', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => onEvent(messageEvent('ok')))
    await act(async () => {
      await sendMessage('p1', 'hi', 'guide')
    })
    expect(streamSolMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        preferences: expect.objectContaining({ electrical: 'XT30 for power.' })
      })
    )
  })
})

describe('background completion + away toast', () => {
  backgroundReplyNotificationsTests()
  backgroundReplyPersistenceTests()
})

describe('sign-out teardown (SEC-M4)', () => {
  it('aborts every live stream and drops every session', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    let seen: AbortSignal | undefined
    streamSolMessage.mockImplementation(async ({ signal }) => {
      seen = signal
      await new Promise(() => undefined) // never resolves on its own
    })
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' } })
    void sendMessage('p1', 'hello', 'guide')
    await act(async () => {
      await Promise.resolve()
    })
    expect(seen?.aborted).toBe(false)

    useAuthStore.setState({ status: 'unauthenticated', user: null })
    expect(seen?.aborted).toBe(true)
    expect(useSolChatStore.getState().sessions).toEqual({})
    expect(useSolSessionStore.getState().streaming).toBe(false)
  })
})

describe('~/.solus cache (ADR-034 Layer 1)', () => {
  const cacheRead = vi.fn()
  const cacheWrite = vi.fn().mockResolvedValue({ ok: true })
  const cacheRemove = vi.fn().mockResolvedValue({ ok: true })

  beforeEach(() => {
    cacheRead.mockReset()
    cacheWrite.mockClear()
    ;(window as unknown as { solus?: unknown }).solus = {
      solChat: { read: cacheRead, write: cacheWrite, remove: cacheRemove }
    }
  })
  afterEach(() => {
    delete (window as unknown as { solus?: unknown }).solus
  })
  cachedHistoryFallbackTests(cacheRead)
  cachedHistoryRefreshTests(cacheRead, cacheWrite)
})

describe('sendMessage reports whether the turn settled clean (FIX-2-R M3)', () => {
  it('true on a completed turn, false on a transport failure or an error frame', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => onEvent(messageEvent('ok')))
    await expect(sendMessage('p1', 'hi', 'guide')).resolves.toBe(true)
    streamSolMessage.mockRejectedValue(new Error('ECONNREFUSED'))
    await expect(sendMessage('p1', 'again', 'guide')).resolves.toBe(false)
    streamSolMessage.mockImplementation(async ({ onEvent }) =>
      onEvent({ type: 'error', code: 'insufficient_credits', message: 'no credits' })
    )
    await expect(sendMessage('p1', 'once more', 'guide')).resolves.toBe(false)
  })
})

describe('screenshot on a turn (SOLUSDEV-252 S3)', () => {
  const cacheWrite = vi.fn().mockResolvedValue({ ok: true })
  const SHOT = {
    media_type: 'image/png' as const,
    data: 'iVBORw0KGgoPIXELS=',
    width: 320,
    height: 200,
    source: { app: 'Onshape', title: 'Bracket v3' },
    context: 'iVBORw0KGgoCONTEXT='
  }

  beforeEach(() => {
    cacheWrite.mockClear()
    ;(window as unknown as { solus?: unknown }).solus = {
      solChat: {
        read: vi.fn().mockResolvedValue(null),
        write: cacheWrite,
        remove: vi.fn().mockResolvedValue({ ok: true })
      }
    }
  })
  afterEach(() => {
    delete (window as unknown as { solus?: unknown }).solus
  })

  it('rides the send it was attached to and marks the user row, never the next send', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => onEvent(messageEvent('A bracket.')))
    await act(async () => {
      await sendMessage('p1', 'What do you think this is?', 'guide', [], false, SHOT)
    })
    expect(streamSolMessage).toHaveBeenLastCalledWith(expect.objectContaining({ screenshot: SHOT }))
    await act(async () => {
      await sendMessage('p1', 'and the hole spacing?', 'guide')
    })
    expect(streamSolMessage.mock.calls.at(-1)?.[0]).not.toHaveProperty('screenshot')
    const items = selectSession(useSolChatStore.getState(), 'p1').items
    expect(items[0]).toMatchObject({ role: 'user', hasScreenshot: true })
    expect(items[2]).toMatchObject({ role: 'user' })
    expect(items[2].hasScreenshot).toBeFalsy()
  })

  it('never lets pixels reach the ~/.solus chat cache', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => onEvent(messageEvent('A bracket.')))
    await act(async () => {
      await sendMessage('p1', 'What do you think this is?', 'guide', [], false, SHOT)
    })
    const payload = cacheWrite.mock.calls.at(-1)?.[2] as string
    expect(payload).not.toContain(SHOT.data)
    expect(payload).not.toContain(SHOT.context)
    expect(payload).not.toMatch(/screenshot|pngBase64|"data"/)
  })

  it('reloaded turns carry hasScreenshot from the server’s pixel-free attrs', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    vi.mocked(solApi.listSolTurns).mockResolvedValue([
      {
        id: 't1',
        conversation_id: 'c1',
        role: 'user',
        content: 'What do you think this is?',
        attrs: { screenshot: { width: 320, height: 200, app: 'Onshape' } },
        created_at: ''
      }
    ])
    await act(async () => {
      await syncSession('p1')
    })
    expect(selectSession(useSolChatStore.getState(), 'p1').items[0].hasScreenshot).toBe(true)
  })
})

describe('server refusals outrank the cache (SEC review H1)', () => {
  const cacheRead = vi.fn()
  const cacheWrite = vi.fn().mockResolvedValue({ ok: true })
  const cacheRemove = vi.fn().mockResolvedValue({ ok: true })
  const cacheClear = vi.fn().mockResolvedValue({ ok: true })
  const CACHED = JSON.stringify({
    schema_version: 1,
    items: [{ role: 'assistant', content: 'previous owner content' }]
  })

  beforeEach(() => {
    cacheRead.mockReset()
    cacheRemove.mockClear()
    cacheClear.mockClear()
    ;(window as unknown as { solus?: unknown }).solus = {
      solChat: { read: cacheRead, write: cacheWrite, remove: cacheRemove, clear: cacheClear }
    }
  })
  afterEach(() => {
    delete (window as unknown as { solus?: unknown }).solus
  })

  it('drops the painted cache AND the file on a 404 — never renders refused data', async () => {
    const { ApiError } = await import('../../lib/api/envelope.types')
    useSolSessionStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(CACHED)
    vi.mocked(solApi.listSolTurns).mockRejectedValue(new ApiError(404, 'not_found', 'gone'))
    await act(async () => {
      await syncSession('p1')
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items).toEqual([])
    expect(cacheRemove).toHaveBeenCalledWith('p1', 'c1')
    // The stale conversation id is forgotten so the next send starts fresh.
    expect(useSolSessionStore.getState().conversationByProject).toEqual({})
  })

  it('drops the painted cache on a 403 and shows offline, not the transcript', async () => {
    const { ApiError } = await import('../../lib/api/envelope.types')
    useSolSessionStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(CACHED)
    vi.mocked(solApi.listSolTurns).mockRejectedValue(new ApiError(403, 'forbidden', 'no'))
    await act(async () => {
      await syncSession('p1')
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items).toEqual([])
    expect(session.status).toBe('offline')
    expect(cacheRemove).toHaveBeenCalledWith('p1', 'c1')
  })

  it('an in-place identity swap tears down sessions and purges the disk cache', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    let seen: AbortSignal | undefined
    streamSolMessage.mockImplementation(async ({ signal }) => {
      seen = signal
      await new Promise(() => undefined)
    })
    useAuthStore.setState({ status: 'authenticated', user: { email: 'a@x.dev' } })
    void sendMessage('p1', 'hello', 'guide')
    await act(async () => {
      await Promise.resolve()
    })
    expect(seen?.aborted).toBe(false)

    // No 'unauthenticated' edge — the session is swapped in place (OAuth
    // loopback / magic link / another window).
    useAuthStore.setState({ status: 'authenticated', user: { email: 'b@x.dev' } })
    expect(seen?.aborted).toBe(true)
    expect(useSolChatStore.getState().sessions).toEqual({})
    expect(useSolSessionStore.getState().conversationByProject).toEqual({})
    expect(cacheClear).toHaveBeenCalled()
  })
})

describe('token batching — one store commit per frame (SOLUSDEV-252 S2-A)', () => {
  const nextFrame = (): Promise<void> =>
    new Promise((resolve) => requestAnimationFrame(() => resolve()))
  tokenFrameBatchingTests(nextFrame)
  tokenFrameOrderingTests()
  tokenFailureAndCancellationTests(nextFrame)
})

// SOLUSDEV-252 S5: a tool's artifact lands on the assistant item it followed.
describe('artifacts on a turn (SOLUSDEV-252 S5)', () => {
  const ARTIFACT = {
    artifactId: 'a1',
    uri: '/api/v1/projects/p1/artifacts/a1/content',
    mediaType: 'image/svg+xml',
    title: 'Power tree',
    sourceTool: 'solus.make_diagram',
    summary: null
  }

  it('appends each artifact to the assistant item once, in arrival order', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'artifact', artifact: ARTIFACT })
      onEvent({ type: 'artifact', artifact: ARTIFACT }) // a re-sent frame is not a second card
      onEvent({ type: 'artifact', artifact: { ...ARTIFACT, artifactId: 'a2', title: 'Wiring' } })
      onEvent(messageEvent('Here you go.'))
    })
    await sendMessage('p1', 'draw the power tree', 'guide')
    const [, reply] = selectSession(useSolChatStore.getState(), 'p1').items
    expect(reply.artifacts?.map((a) => a.artifactId)).toEqual(['a1', 'a2'])
    expect(reply.artifacts?.[0]).toEqual({ ...ARTIFACT, filedTo: null })
  })

  it('fileArtifact posts the entry and marks the card filed — never twice', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'artifact', artifact: ARTIFACT })
      onEvent(messageEvent('ok'))
    })
    await sendMessage('p1', 'draw', 'guide')
    addSolusEntry.mockResolvedValue({ id: 'e1' } as resources.SolusEntry)
    await fileArtifact('p1', 'a1', 'docs')
    expect(addSolusEntry).toHaveBeenCalledWith('p1', 'docs', {
      kind: 'artifact',
      artifact_id: 'a1',
      name: 'Power tree'
    })
    const filed = selectSession(useSolChatStore.getState(), 'p1').items[1].artifacts?.[0]
    expect(filed?.filedTo).toBe('docs')
    await fileArtifact('p1', 'a1', 'hardware')
    expect(addSolusEntry).toHaveBeenCalledTimes(1)
    expect(selectSession(useSolChatStore.getState(), 'p1').items[1].artifacts?.[0].filedTo).toBe(
      'docs'
    )
  })

  it('a failed filing rethrows and leaves the card unfiled', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'artifact', artifact: ARTIFACT })
      onEvent(messageEvent('ok'))
    })
    await sendMessage('p1', 'draw', 'guide')
    addSolusEntry.mockRejectedValue(new Error('artifact not found'))
    await expect(fileArtifact('p1', 'a1', 'errors')).rejects.toThrow('artifact not found')
    expect(
      selectSession(useSolChatStore.getState(), 'p1').items[1].artifacts?.[0].filedTo
    ).toBeNull()
  })

  it('an unknown artifact id is a no-op, not a request', async () => {
    await fileArtifact('p1', 'nope', 'docs')
    expect(addSolusEntry).not.toHaveBeenCalled()
  })
})

function backgroundReplyNotificationsTests(): void {
  it('names the fact, not the prompt, when the reply lands under another project (SOLUSDEV-242)', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
    useShellStore.getState().setLastMain('sol')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      // The user switches to Arm while Rover's turn is still streaming.
      useWorkspaceStore.setState({ project: { id: 'p2', name: 'Arm' } })
      onEvent(messageEvent('All good.'))
    })
    await act(async () => {
      await sendMessage('p1', 'why is joint 2 stalling?', 'guide')
    })
    const toast = useShellStore.getState().toast
    expect(toast?.title).toBe('SOL replied')
    expect(toast?.body).not.toContain('joint 2')
    expect(toast?.action).toBeUndefined()
  })

  it('raises the shell toast when a reply completes while the user is away', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
    useShellStore.getState().setLastMain('home') // not on the SOL page
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent(messageEvent('All good.'))
    })
    await act(async () => {
      await sendMessage('p1', 'why is joint 2 stalling?', 'guide')
    })
    const toast = useShellStore.getState().toast
    expect(toast).not.toBeNull()
    expect(toast?.kind).toBe('ok')
    expect(toast?.title).toBe('SOL replied')
    expect(toast?.body).toContain('why is joint 2 stalling?')
    // The workspace is still on the turn's project, so View jumps to SOL.
    expect(toast?.action).toBe('View')
    expect(toast?.screen).toBe('sol')
  })

  it('stays quiet when the user is watching the SOL page', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    useWorkspaceStore.setState({ project: { id: 'p1', name: 'Rover' } })
    useShellStore.getState().setLastMain('sol')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent(messageEvent('All good.'))
    })
    await act(async () => {
      await sendMessage('p1', 'hi', 'guide')
    })
    expect(useShellStore.getState().toast).toBeNull()
  })
}

function backgroundReplyPersistenceTests(): void {
  it('warns (without a raw error) when a backgrounded turn fails', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    useShellStore.getState().setLastMain('home')
    streamSolMessage.mockRejectedValue(new Error('ECONNREFUSED'))
    await act(async () => {
      await sendMessage('p1', 'hi', 'guide')
    })
    const toast = useShellStore.getState().toast
    expect(toast?.kind).toBe('warn')
    expect(toast?.title).toBe('SOL turn failed')
    expect(JSON.stringify(toast)).not.toContain('ECONNREFUSED')
  })

  it('the finished reply waits in the session for the next mount', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    let finish: () => void = () => undefined
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      await new Promise<void>((resolve) => {
        finish = () => {
          onEvent(messageEvent('Done in the background.'))
          resolve()
        }
      })
    })
    const pending = sendMessage('p1', 'hello', 'guide')
    expect(selectSession(useSolChatStore.getState(), 'p1').streaming).toBe(true)
    // The turn first collects the user's preferences (SOLUSDEV-244), so the
    // stream opens one tick later than the call.
    await vi.waitFor(() => expect(streamSolMessage).toHaveBeenCalled())
    await act(async () => {
      finish()
      await pending
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.streaming).toBe(false)
    expect(session.items.at(-1)?.content).toBe('Done in the background.')
  })
}

function cachedHistoryFallbackTests(cacheRead: ReturnType<typeof vi.fn>): void {
  it('keeps a cached chat readable when the server cannot load it', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(
      JSON.stringify({
        schema_version: 1,
        items: [
          { role: 'user', content: 'old question' },
          { role: 'assistant', content: 'old answer' }
        ]
      })
    )
    vi.mocked(solApi.listSolTurns).mockRejectedValue(new Error('down'))
    await act(async () => {
      await syncSession('p1')
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items.map((m) => m.content)).toEqual(['old question', 'old answer'])
    expect(session.status).toBe('ready') // the cache IS the readable history
  })
}

function cachedHistoryRefreshTests(
  cacheRead: ReturnType<typeof vi.fn>,
  cacheWrite: ReturnType<typeof vi.fn>
): void {
  it('the server load wins over the cache and refreshes it', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(
      JSON.stringify({
        schema_version: 1,
        // Even an id posing as a live turn cannot survive the server load —
        // file ids are rewritten to the cache- namespace (SEC review H2).
        items: [{ id: 'local-999', role: 'user', content: 'stale' }]
      })
    )
    vi.mocked(solApi.listSolTurns).mockResolvedValue([
      {
        id: 't9',
        conversation_id: 'c1',
        role: 'assistant',
        content: 'fresh from the server',
        attrs: {},
        created_at: ''
      }
    ])
    await act(async () => {
      await syncSession('p1')
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items.map((m) => m.content)).toEqual(['fresh from the server'])
    expect(cacheWrite).toHaveBeenCalled() // refreshed with server truth
  })

  it('mirrors the transcript to the cache when a turn settles', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    cacheRead.mockResolvedValue(null)
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent(messageEvent('cached reply'))
    })
    await act(async () => {
      await sendMessage('p1', 'question', 'guide')
    })
    const [pid, cid, payload] = cacheWrite.mock.calls.at(-1) as [string, string, string]
    expect(pid).toBe('p1')
    expect(cid).toBe('c1')
    expect(JSON.parse(payload).items.map((m: { content: string }) => m.content)).toEqual([
      'question',
      'cached reply'
    ])
  })
}

function tokenFrameBatchingTests(nextFrame: () => Promise<void>): void {
  it('applies a burst of tokens as ONE notification on the next frame', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    let emit: (e: SolStreamEvent) => void = () => undefined
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      emit = onEvent
      await new Promise(() => undefined)
    })
    void sendMessage('p1', 'hi', 'guide')
    await vi.waitFor(() => expect(streamSolMessage).toHaveBeenCalled())
    let notifies = 0
    const unsubscribe = useSolChatStore.subscribe(() => notifies++)
    for (let i = 0; i < 100; i++) emit({ type: 'token', text: `w${i} ` })
    // Nothing lands synchronously…
    expect(notifies).toBe(0)
    expect(selectSession(useSolChatStore.getState(), 'p1').items.at(-1)?.content).toBe('')
    await nextFrame()
    // …then the whole burst lands in one commit.
    expect(notifies).toBe(1)
    const content = selectSession(useSolChatStore.getState(), 'p1').items.at(-1)?.content
    expect(content?.startsWith('w0 w1 ')).toBe(true)
    expect(content?.endsWith('w99 ')).toBe(true)
    unsubscribe()
  })

  it('flushPendingTokens lands buffered text without waiting for a frame', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    let emit: (e: SolStreamEvent) => void = () => undefined
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      emit = onEvent
      await new Promise(() => undefined)
    })
    void sendMessage('p1', 'hi', 'guide')
    await vi.waitFor(() => expect(streamSolMessage).toHaveBeenCalled())
    emit({ type: 'token', text: 'now' })
    flushPendingTokens('p1')
    expect(selectSession(useSolChatStore.getState(), 'p1').items.at(-1)?.content).toBe('now')
  })
}

function tokenFrameOrderingTests(): void {
  it('a non-token event flushes pending text FIRST so it never overtakes the prose', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    const seen: string[] = []
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      const unsubscribe = useSolChatStore.subscribe((s) => {
        const last = selectSession(s, 'p1').items.at(-1)
        seen.push(`${last?.content}|${last?.trace.length}|${last?.error ?? ''}`)
      })
      onEvent({ type: 'token', text: 'partial ' })
      onEvent({ type: 'tool_call', callId: 'k1', tool: 'get_entity' })
      onEvent({ type: 'token', text: 'answer' })
      onEvent({ type: 'error', code: 'timeout', message: 'timed out' })
      unsubscribe()
    })
    await act(async () => {
      await sendMessage('p1', 'hi', 'guide')
    })
    expect(seen).toEqual([
      'partial |0|',
      'partial |1|',
      'partial answer|1|',
      'partial answer|1|timed out'
    ])
  })

  it('text still buffered when the stream ends lands before the turn settles', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'token', text: 'tail text' })
      // No message frame: the transport just ends.
    })
    await act(async () => {
      await sendMessage('p1', 'hi', 'guide')
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items.at(-1)?.content).toBe('tail text')
    expect(session.streaming).toBe(false)
  })
}

function tokenFailureAndCancellationTests(nextFrame: () => Promise<void>): void {
  it('a transport failure keeps the streamed prefix ahead of the failure note', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      onEvent({ type: 'token', text: 'half an ' })
      throw new Error('ECONNRESET')
    })
    await act(async () => {
      await sendMessage('p1', 'hi', 'guide')
    })
    const last = selectSession(useSolChatStore.getState(), 'p1').items.at(-1)
    expect(last?.content).toBe('half an ')
    expect(last?.error).toBe('SOL is unreachable right now.')
  })

  it('a cancelled turn drops its buffered tokens instead of writing into the next chat', async () => {
    useSolSessionStore.getState().setConversation('p1', 'c1')
    vi.mocked(solApi.listSolTurns).mockResolvedValue([])
    let emit: (e: SolStreamEvent) => void = () => undefined
    streamSolMessage.mockImplementation(async ({ onEvent }) => {
      emit = onEvent
      await new Promise(() => undefined)
    })
    void sendMessage('p1', 'hi', 'guide')
    await vi.waitFor(() => expect(streamSolMessage).toHaveBeenCalled())
    emit({ type: 'token', text: 'stale' })
    selectConversation('p1', 'c2')
    await nextFrame()
    await act(async () => {
      await Promise.resolve()
    })
    const session = selectSession(useSolChatStore.getState(), 'p1')
    expect(session.items.some((m) => m.content.includes('stale'))).toBe(false)
  })
}
