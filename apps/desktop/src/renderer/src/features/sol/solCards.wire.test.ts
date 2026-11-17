// SOLUSDEV-326 P3: the wire edges of cards in SOL (docs/contracts/action-gate.md §Cards): the
// notice and answer bodies, the `working` line on a tool_call frame, and the card a parked row
// carries. Everything crossing here is validated; a card that is not the contract's shape is dropped.
import { describe, expect, it, vi } from 'vitest'
import type { Card } from '@solus/shared-types'
import { toPendingConfirmation } from '../../lib/api/solStream'
import { streamSolMessage } from './solApi'
import { blankItem, workingLine } from './solChatItems'
import { createSolStreamParser } from './solStream'

const CARD: Card = {
  kind: 'approval',
  title: 'Approve: flash the Nano',
  body: 'Runs `arduino-cli upload` on the board.',
  more: null,
  field: null,
  primary: 'Approve',
  secondary: 'Not now',
  receipt: 'Nano flashed',
  resumes: true
}

function emptyStream(): Response {
  const body = new ReadableStream<Uint8Array>({ start: (c) => c.close() })
  return { ok: true, status: 200, body } as unknown as Response
}

async function bodyOf(
  input: Partial<Parameters<typeof streamSolMessage>[0]>
): Promise<Record<string, unknown>> {
  const fetchImpl = vi.fn().mockResolvedValue(emptyStream())
  await streamSolMessage({
    projectId: 'p',
    conversationId: 'c',
    content: '',
    actionMode: 'do',
    forceConfirmation: true,
    onEvent: () => undefined,
    fetchImpl,
    getToken: async () => null,
    baseUrl: 'http://api.invalid',
    frontApp: null,
    ...input
  })
  return JSON.parse(fetchImpl.mock.calls[0][1].body as string) as Record<string, unknown>
}

describe('Solus-written turns', () => {
  it('a notice carries the device and the turn settings, and no words', async () => {
    expect(await bodyOf({ notice: { kind: 'device', device_ref: 'usb:5B42' } })).toEqual({
      notice: { kind: 'device', device_ref: 'usb:5B42' },
      action_mode: 'do',
      force_confirmation: true
    })
  })

  it('an answer carries the question, the choice and the typed text, and no content', async () => {
    const answer = { question_id: 'q1', choice: 1 as const, text: 'Rover arm' }
    expect(await bodyOf({ answer })).toEqual({
      answer,
      action_mode: 'do',
      force_confirmation: true
    })
  })
})

describe('the working line', () => {
  const frame = (data: unknown): string => `event: tool_call\ndata: ${JSON.stringify(data)}\n\n`

  it('rides a tool_call frame as bounded text', () => {
    const [event] = createSolStreamParser().push(
      frame({ call_id: 'k1', tool: 'hardware.inspect_device', working: 'Reading the USB adapter' })
    )
    expect(event).toMatchObject({ type: 'tool_call', working: 'Reading the USB adapter' })
  })

  it('is left off when it is not text or is past the server cap', () => {
    const parser = createSolStreamParser()
    for (const working of [7, 'x'.repeat(161)]) {
      const [event] = parser.push(frame({ call_id: 'k1', tool: 't', working }))
      expect(event).toEqual({ type: 'tool_call', callId: 'k1', tool: 't' })
    }
  })

  it('shows only while the reply has nothing to say and a named call is in flight', () => {
    const step = { callId: 'k1', tool: 't', ok: null, errorCode: null, working: 'Reading' }
    const waiting = { ...blankItem('local-1', 'assistant', '', true), trace: [step] }
    expect(workingLine([waiting])).toBe('Reading')
    expect(workingLine([{ ...waiting, content: 'Found it.' }])).toBeNull()
    expect(workingLine([{ ...waiting, trace: [{ ...step, ok: true }] }])).toBeNull()
    expect(workingLine([{ ...waiting, pending: false }])).toBeNull()
    expect(workingLine([])).toBeNull()
  })
})

describe('a parked row with a card', () => {
  const data = { confirmation_id: 'c1', tool: 'hardware.add_parts', summary: 's', preview: [] }

  it('keeps the card when it is the contract shape', () => {
    const pending = toPendingConfirmation({
      type: 'tool_confirmation',
      data: { ...data, card: CARD }
    })
    expect(pending?.card).toEqual(CARD)
  })

  it('drops a card that is not, and keeps the row', () => {
    const bad = { ...CARD, kind: 'banner' }
    const pending = toPendingConfirmation({
      type: 'tool_confirmation',
      data: { ...data, card: bad }
    })
    expect(pending).toMatchObject({ confirmationId: 'c1' })
    expect(pending?.card).toBeUndefined()
  })
})
