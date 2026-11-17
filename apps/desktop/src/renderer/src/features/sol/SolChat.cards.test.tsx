// SOLUSDEV-326 P3: cards in the SOL thread (docs/wireflows/sol-page.md "Cards in the thread"). A
// parked row that carries a card renders the card's own copy in the existing .confirmation-card;
// a question is answered with a turn, never decided; the pill's plan never batches a card; and a
// surface with a card slot leaves cards out of its thread.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Card } from '@solus/shared-types'
import * as resources from '../../lib/api/resources'
import type { PendingConfirmation } from '../../lib/api/solStream'
import * as solApi from './solApi'
import { SolChat } from './SolChat'
import { cardDecided, resetSolChatSessions, syncSession } from './solChatStore'
import { useSolSessionStore } from './solSessionStore'
import { useSolWindowStore } from './solWindowStore'

vi.mock('./solApi', () => ({
  listSolConfirmations: vi.fn().mockResolvedValue([]),
  createSolConversation: vi.fn(),
  listSolTurns: vi.fn().mockResolvedValue([]),
  streamSolMessage: vi.fn()
}))
vi.mock('../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof resources>()),
  classifyQuery: vi.fn(() => new Promise(() => undefined)),
  decideSolConfirmation: vi.fn()
}))
vi.mock('../preferences/preferencesStore', () => ({ preferencesForTurn: async () => null }))

const listSolConfirmations = vi.mocked(solApi.listSolConfirmations)
const streamSolMessage = vi.mocked(solApi.streamSolMessage)
const decideSolConfirmation = vi.mocked(resources.decideSolConfirmation)

const card = (over: Partial<Card> = {}): Card => ({
  kind: 'offer',
  title: 'Found: 3 servos on a USB adapter',
  body: 'They match `arm.yaml` in rover_ws.',
  more: null,
  field: null,
  primary: 'Add',
  secondary: 'Not now',
  receipt: '3 servos added',
  resumes: false,
  ...over
})
const row = (id: string, tool: string, c?: Card): PendingConfirmation => ({
  confirmationId: id,
  tool,
  summary: `summary of ${tool}`,
  preview: [],
  ...(c ? { card: c } : {})
})

/** Open the project on a conversation whose server-owned open rows are `rows`. */
function restore(...rows: PendingConfirmation[]): void {
  useSolSessionStore.setState({ streaming: false, conversationByProject: { p1: 'c1' } })
  listSolConfirmations.mockResolvedValue(rows)
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  resetSolChatSessions()
  useSolSessionStore.setState({ streaming: false, conversationByProject: {} })
  useSolWindowStore.setState({ state: null, region: null })
  listSolConfirmations.mockResolvedValue([])
  streamSolMessage.mockResolvedValue(undefined)
  decideSolConfirmation.mockResolvedValue({ ok: true, value: {} } as Awaited<
    ReturnType<typeof resources.decideSolConfirmation>
  >)
})

describe('a card row on the SOL page', () => {
  it('shows the card’s title, body with code chips and its own button labels', async () => {
    restore(row('k1', 'hardware.add_parts', card()))
    render(<SolChat projectId="p1" layout="page" />)
    const shown = await screen.findByRole('region', { name: 'Found: 3 servos on a USB adapter' })
    expect(shown).toHaveClass('confirmation-card')
    const chip = within(shown).getByText('arm.yaml')
    expect(chip.tagName).toBe('CODE')
    expect(within(shown).getByRole('button', { name: 'Add' })).toBeInTheDocument()
    expect(within(shown).getByRole('button', { name: 'Not now' })).toBeInTheDocument()
    expect(within(shown).queryByRole('button', { name: 'Approve' })).toBeNull()
  })

  it('decides through the same route: primary approves, secondary rejects', async () => {
    restore(
      row('k1', 'hardware.add_parts', card()),
      row('k2', 'hardware.link_part', card({ title: 'Link elbow' }))
    )
    render(<SolChat projectId="p1" layout="page" />)
    fireEvent.click(within(await screen.findByRole('region', { name: /Found/ })).getByText('Add'))
    await waitFor(() => expect(decideSolConfirmation).toHaveBeenCalledWith('p1', 'k1', 'approve'))
    fireEvent.click(within(screen.getByRole('region', { name: 'Link elbow' })).getByText('Not now'))
    await waitFor(() => expect(decideSolConfirmation).toHaveBeenCalledWith('p1', 'k2', 'reject'))
  })

  describe('whose field the person edited', () => {
    const NAMED = card({ field: { label: 'Robot name', value: 'Rover arm' } })
    const edit = async (button: string): Promise<void> => {
      restore(row('k1', 'hardware.add_parts', NAMED))
      render(<SolChat projectId="p1" layout="page" />)
      const shown = await screen.findByRole('region', { name: /Found/ })
      fireEvent.change(within(shown).getByLabelText('Robot name'), { target: { value: ' Scout ' } })
      fireEvent.click(within(shown).getByRole('button', { name: button }))
    }

    it('answers the card with the new value — one request, never a decision — and the card leaves', async () => {
      await edit('Add')
      await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
      expect(streamSolMessage.mock.calls[0][0]).toMatchObject({
        conversationId: 'c1',
        content: '',
        answer: { question_id: 'k1', choice: 0, text: 'Scout' }
      })
      expect(decideSolConfirmation).not.toHaveBeenCalled()
      await waitFor(() => expect(screen.queryByRole('region', { name: /Found/ })).toBeNull())
      expect(screen.queryByText('Awaiting your approval')).toBeNull()
    })

    it('stays in the thread until the answer turn is admitted, and comes back when it failed', async () => {
      // A live turn holds the edit's turn back: the card waits, spent, and nothing is sent yet.
      let fail: (error: Error) => void = () => undefined
      streamSolMessage.mockImplementation(() => new Promise<void>((_, reject) => (fail = reject)))
      await edit('Add')
      await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
      await waitFor(() => expect(screen.queryByRole('region', { name: /Found/ })).toBeNull())
      await act(async () => fail(new TypeError('Failed to fetch')))
      const back = await screen.findByRole('region', { name: /Found/ })
      await waitFor(() => expect(within(back).getByRole('button', { name: 'Add' })).toBeEnabled())
      expect(decideSolConfirmation).not.toHaveBeenCalled()
    })

    it('"Not now" is still only a rejection, and an untouched field an approval', async () => {
      await edit('Not now')
      await waitFor(() => expect(decideSolConfirmation).toHaveBeenCalledWith('p1', 'k1', 'reject'))
      expect(streamSolMessage.mock.calls.every(([input]) => !input.answer)).toBe(true)
    })
  })

  it('marks an approval with the warn edge and tint, and no other kind', async () => {
    restore(
      row(
        'k1',
        'code.arduino_upload',
        card({ kind: 'approval', title: 'Approve: flash the Nano' })
      ),
      row('k2', 'hardware.add_parts', card())
    )
    render(<SolChat projectId="p1" layout="page" />)
    const approval = await screen.findByRole('region', { name: 'Approve: flash the Nano' })
    expect(approval).toHaveClass('confirmation-card--approval')
    expect(screen.getByRole('region', { name: /Found/ })).not.toHaveClass(
      'confirmation-card--approval'
    )
    const here = dirname(fileURLToPath(import.meta.url))
    const css = readFileSync(join(here, 'ConfirmationCard.css'), 'utf8')
    const rule = /\.confirmation-card--approval\s*\{([^}]*)\}/.exec(css)?.[1] ?? ''
    expect(rule).toMatch(/border-left-color:\s*var\(--warn\)/)
    expect(rule).toMatch(/color-mix\(in srgb, var\(--warn\) 8%/)
  })

  it('an offer titled like an approval gets no approval styling: the kind alone decides', async () => {
    restore(row('k1', 'hardware.add_parts', card({ title: 'Approve: flash the Nano' })))
    render(<SolChat projectId="p1" layout="page" />)
    const offer = await screen.findByRole('region', { name: 'Approve: flash the Nano' })
    expect(offer).toHaveAttribute('data-kind', 'offer')
    expect(offer).not.toHaveClass('confirmation-card--approval')
  })

  it('renders model-authored card text as text, never as markup', async () => {
    restore(
      row('k1', 'hardware.add_parts', card({ body: '<img src=x onerror=alert(1)> `<b>x</b>`' }))
    )
    const { container } = render(<SolChat projectId="p1" layout="page" />)
    const shown = await screen.findByRole('region', { name: /Found/ })
    expect(within(shown).getByText('<b>x</b>').tagName).toBe('CODE')
    expect(container.querySelector('img, b')).toBeNull()
  })
})

describe('a question row', () => {
  const QUESTION = card({
    title: 'What should the robot be called?',
    body: 'Three servos answered.',
    field: { label: 'Robot name', value: 'Rover arm' },
    primary: 'Use this name',
    secondary: 'Skip'
  })

  it('shows its two labels and a field, and posts an answer turn — never a decision', async () => {
    restore(row('q1', 'ask_user', QUESTION))
    render(<SolChat projectId="p1" layout="page" />)
    const shown = await screen.findByRole('region', { name: 'What should the robot be called?' })
    fireEvent.change(within(shown).getByLabelText('Robot name'), { target: { value: 'Scout' } })
    fireEvent.click(within(shown).getByRole('button', { name: 'Use this name' }))
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
    expect(streamSolMessage.mock.calls[0][0]).toMatchObject({
      conversationId: 'c1',
      answer: { question_id: 'q1', choice: 0, text: 'Scout' }
    })
    expect(decideSolConfirmation).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByRole('region', { name: /called/ })).toBeNull())
    // The restored row held nothing else: its "Awaiting your approval" line goes with it.
    expect(screen.queryByText('Awaiting your approval')).toBeNull()
  })

  it('goes as Build, as every send does now that no surface offers a mode (SOLUSDEV-327)', async () => {
    restore(row('q1', 'ask_user', QUESTION))
    render(<SolChat projectId="p1" layout="page" />)
    const skip = await screen.findByRole('button', { name: 'Skip' })
    fireEvent.click(skip)
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
    expect(streamSolMessage.mock.calls[0][0].actionMode).toBe('do')
    expect(streamSolMessage.mock.calls[0][0]).not.toHaveProperty('forceConfirmation')
  })

  it('stays in the thread, live, when the answer never reached SOL', async () => {
    streamSolMessage.mockRejectedValue(new TypeError('Failed to fetch'))
    restore(row('q1', 'ask_user', QUESTION))
    render(<SolChat projectId="p1" layout="page" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Skip' }))
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
    const shown = await screen.findByRole('region', { name: 'What should the robot be called?' })
    await waitFor(() => expect(within(shown).getByRole('button', { name: 'Skip' })).toBeEnabled())
  })

  it('answers the secondary as choice 1, with no text when the field was left alone', async () => {
    restore(row('q1', 'ask_user', QUESTION))
    render(<SolChat projectId="p1" layout="page" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Skip' }))
    await waitFor(() => expect(streamSolMessage).toHaveBeenCalledTimes(1))
    expect(streamSolMessage.mock.calls[0][0].answer).toEqual({ question_id: 'q1', choice: 1 })
  })
})

describe('the pill’s plan', () => {
  it('batches only rows with no card; a card keeps its own card', async () => {
    restore(row('k1', 'onshape.set_variable'), row('k2', 'hardware.add_parts', card()))
    render(<SolChat projectId="p1" layout="pill" />)
    const plan = await screen.findByRole('region', { name: 'Plan needs your approval' })
    expect(within(plan).getAllByRole('listitem')).toHaveLength(1)
    expect(within(plan).queryByText(/Found: 3 servos/)).toBeNull()
    expect(screen.getByRole('region', { name: /Found: 3 servos/ })).toBeInTheDocument()
  })
})

describe('cardsInSlot', () => {
  it('leaves cards out of the thread and keeps a row the slot can never show', async () => {
    restore(row('k1', 'hardware.add_parts', card()), row('k2', 'onshape.set_variable'))
    render(<SolChat projectId="p1" cardsInSlot />)
    expect(await screen.findByLabelText('Action needs your approval')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /Found: 3 servos/ })).toBeNull()
  })
})

describe('a card decided in the Hardware page’s slot', () => {
  const awaiting = (): HTMLElement | null => screen.queryByText('Awaiting your approval')

  it('leaves the SOL page’s thread at once: no live card is left to press a second time', async () => {
    restore(row('k1', 'hardware.add_parts', card({ resumes: true })))
    render(<SolChat projectId="p1" layout="page" />)
    await screen.findByRole('region', { name: /Found/ })
    act(() => cardDecided('p1', 'k1', 'approve'))
    expect(screen.queryByRole('region', { name: /Found/ })).toBeNull()
    expect(screen.getByText('Approval recorded.')).toBeInTheDocument()
    // The decision was the slot's: the thread posts none, and starts no resume of its own.
    expect(decideSolConfirmation).not.toHaveBeenCalled()
    expect(streamSolMessage).not.toHaveBeenCalled()
    // A history load that still lists the row (the server has not caught up) does not restore it.
    useSolSessionStore.setState({ conversationByProject: { p1: 'c2' } })
    await act(() => syncSession('p1'))
    useSolSessionStore.setState({ conversationByProject: { p1: 'c1' } })
    await act(() => syncSession('p1'))
    expect(screen.queryByRole('region', { name: /Found/ })).toBeNull()
  })

  it('leaves no "Awaiting your approval" line with no card under it beside the slot', async () => {
    restore(row('k1', 'hardware.add_parts', card()))
    render(<SolChat projectId="p1" layout="sidebar" cardsInSlot />)
    await waitFor(() => expect(awaiting()).toBeInTheDocument())
    act(() => cardDecided('p1', 'k1', 'reject'))
    expect(awaiting()).toBeNull()
    expect(screen.getByText('Action rejected.')).toBeInTheDocument()
  })

  it('a card the server refused goes without a word of approval, and its restored line with it', async () => {
    restore(row('k1', 'hardware.add_parts', card()))
    render(<SolChat projectId="p1" layout="sidebar" cardsInSlot />)
    await waitFor(() => expect(awaiting()).toBeInTheDocument())
    act(() => cardDecided('p1', 'k1', null))
    expect(awaiting()).toBeNull()
    expect(screen.queryByText('Approval recorded.')).toBeNull()
    expect(screen.queryByText('Action rejected.')).toBeNull()
  })
})
