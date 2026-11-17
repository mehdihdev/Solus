// SOLUSDEV-326 P3 follow-up: the turns Solus writes for the person never pass for words they
// typed. A device notice is a quiet Solus line and an answered question a receipt naming the
// button, each drawn the same live and after a reload (docs/wireflows/sol-page.md).
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Card } from '@solus/shared-types'
import * as solApi from './solApi'
import type { SolTurn } from './solApi'
import { sendNotice } from './solCardTurns'
import { SolChat } from './SolChat'
import { resetSolChatSessions } from './solChatStore'
import { useSolSessionStore } from './solSessionStore'
import { useSolWindowStore } from './solWindowStore'

vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources')>()),
  classifyQuery: vi.fn(() => new Promise(() => undefined))
}))
vi.mock('../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))

const listSolTurns = vi.mocked(solApi.listSolTurns)
const listSolConfirmations = vi.mocked(solApi.listSolConfirmations)
const streamSolMessage = vi.mocked(solApi.streamSolMessage)

const STORED_NOTICE =
  'Solus noticed a device plugged into this computer: Possible Arduino connection ("usb:port-5-1.2.3").'
const DO = { actionMode: 'do', forceConfirmation: true } as const

const turn = (id: string, content: string, attrs: Record<string, unknown>): SolTurn => ({
  id,
  conversation_id: 'c1',
  role: 'user',
  content,
  attrs,
  created_at: '2026-11-16T00:00:00Z'
})

const QUESTION: Card = {
  kind: 'step',
  title: 'Is this the arm?',
  body: 'A board answered on the port.',
  more: null,
  field: null,
  primary: 'Yes',
  secondary: 'No',
  receipt: 'Arm confirmed',
  resumes: false
}

/** The row's own text, and whether it sits on the person's side of the thread. */
const bubbleText = (): string[] =>
  [...document.querySelectorAll('[data-testid="sol-user-bubble"]')].map((b) => b.textContent ?? '')

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolWindowStore.setState({ state: null, region: null })
  useSolSessionStore.setState({ streaming: false, conversationByProject: { p1: 'c1' } })
  listSolTurns.mockResolvedValue([])
  listSolConfirmations.mockResolvedValue([])
  streamSolMessage.mockResolvedValue(undefined)
})

describe('a device notice', () => {
  it('reloaded, is a quiet Solus line with the stored words, never the person’s bubble', async () => {
    listSolTurns.mockResolvedValue([
      turn('n1', STORED_NOTICE, { authored_by: 'solus', notice: { kind: 'device' } }),
      turn('u1', 'what is plugged in?', {})
    ])
    render(<SolChat projectId="p1" layout="page" />)
    expect(await screen.findByTestId('sol-notice-line')).toHaveTextContent(STORED_NOTICE)
    expect(bubbleText()).toEqual(['what is plugged in?'])
  })

  it('live, draws the line as soon as it is sent', async () => {
    let finish: () => void = () => undefined
    streamSolMessage.mockImplementation(() => new Promise<void>((resolve) => (finish = resolve)))
    render(<SolChat projectId="p1" layout="page" />)
    let sending: Promise<boolean> = Promise.resolve(false)
    await act(async () => {
      sending = sendNotice('p1', 'usb:port-5-1.2.3', DO)
      await Promise.resolve()
    })
    expect(await screen.findByTestId('sol-notice-line')).toHaveTextContent(
      'Solus told SOL about a device plugged into this computer.'
    )
    expect(bubbleText()).toEqual([])
    await act(async () => {
      finish()
      await sending
    })
    expect(screen.getByTestId('sol-notice-line')).toBeInTheDocument()
  })
})

describe('an answered question', () => {
  it('reloaded, is a receipt naming the button, not a bubble of typed text', async () => {
    listSolTurns.mockResolvedValue([
      turn('a1', 'Chose "Yes"', { answer: { question_id: 'q1', choice: 0 } })
    ])
    render(<SolChat projectId="p1" layout="page" />)
    expect(await screen.findByTestId('sol-answer-line')).toHaveTextContent(/^Answered: Yes$/)
    expect(bubbleText()).toEqual([])
  })

  it('live, is the same receipt', async () => {
    listSolConfirmations.mockResolvedValue([
      { confirmationId: 'q1', tool: 'ask_user', summary: 'ask', preview: [], card: QUESTION }
    ])
    render(<SolChat projectId="p1" layout="page" />)
    const question = await screen.findByRole('region', { name: 'Is this the arm?' })
    await act(
      async () => void fireEvent.click(within(question).getByRole('button', { name: 'Yes' }))
    )
    expect(await screen.findByTestId('sol-answer-line')).toHaveTextContent(/^Answered: Yes$/)
    expect(bubbleText()).toEqual([])
  })

  it('a label written as markup is drawn as its characters', async () => {
    listSolTurns.mockResolvedValue([
      turn('a1', 'Chose "<img src=x onerror=alert(1)> **Yes**" — on the bench', {
        answer: { question_id: 'q1', choice: 0 }
      })
    ])
    render(<SolChat projectId="p1" layout="page" />)
    const line = await screen.findByTestId('sol-answer-line')
    expect(line).toHaveTextContent('Answered: <img src=x onerror=alert(1)> **Yes** — on the bench')
    expect(line.querySelector('img, strong')).toBeNull()
  })
})

describe('an edited card', () => {
  const EDITED = /^Edited: Robot name — Arm B$/

  it.each([
    [
      'with the server’s edit mark',
      { question_id: 'k1', choice: 0, edit: true, label: 'Robot name' }
    ],
    ['with no mark, from the turn’s own words', { question_id: 'k1', choice: 0 }]
  ])('reloaded %s, is a receipt naming the field and the new value', async (_, answer) => {
    listSolTurns.mockResolvedValue([turn('e1', 'Robot name: "Arm B"', { answer })])
    render(<SolChat projectId="p1" layout="page" />)
    expect(await screen.findByTestId('sol-answer-line')).toHaveTextContent(EDITED)
    expect(bubbleText()).toEqual([])
  })

  it('live, is the same receipt', async () => {
    listSolConfirmations.mockResolvedValue([
      {
        confirmationId: 'k1',
        tool: 'hardware.add_parts',
        summary: 'add',
        preview: [],
        card: { ...QUESTION, kind: 'offer', field: { label: 'Robot name', value: 'Rover arm' } }
      }
    ])
    render(<SolChat projectId="p1" layout="page" />)
    const offer = await screen.findByRole('region', { name: 'Is this the arm?' })
    fireEvent.change(within(offer).getByLabelText('Robot name'), { target: { value: 'Arm B' } })
    await act(async () => void fireEvent.click(within(offer).getByRole('button', { name: 'Yes' })))
    expect(await screen.findByTestId('sol-answer-line')).toHaveTextContent(EDITED)
    expect(bubbleText()).toEqual([])
  })

  it('a value written as markup, quotes and all, is drawn as its characters', async () => {
    listSolTurns.mockResolvedValue([
      turn('e1', 'Robot name: "<img src=x onerror=alert(1)> \\"B\\""', {
        answer: { question_id: 'k1', choice: 0, edit: true }
      })
    ])
    render(<SolChat projectId="p1" layout="page" />)
    const line = await screen.findByTestId('sol-answer-line')
    expect(line).toHaveTextContent('Edited: Robot name — <img src=x onerror=alert(1)> "B"')
    expect(line.querySelector('img')).toBeNull()
  })
})
