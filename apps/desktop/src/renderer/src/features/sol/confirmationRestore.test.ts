import { beforeEach, expect, it, vi } from 'vitest'
import {
  syncSession,
  resetSolChatSessions,
  useSolChatStore,
  decideConfirmation
} from './solChatStore'
import { useSolSessionStore } from './solSessionStore'
import { listSolTurns, listSolConfirmations } from './solApi'
import { decideSolConfirmation } from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (original) => ({
  ...(await original<typeof import('../../lib/api/resources')>()),
  decideSolConfirmation: vi.fn().mockResolvedValue({ ok: true })
}))

vi.mock('./solApi', () => ({
  listSolTurns: vi.fn(),
  listSolConfirmations: vi.fn(),
  createSolConversation: vi.fn(),
  streamSolMessage: vi.fn()
}))

beforeEach(() => {
  resetSolChatSessions()
  useSolSessionStore.setState({ conversationByProject: { p: 'c' }, streaming: false })
})

it('restores original server approval IDs and previews without proposing or approving', async () => {
  vi.mocked(listSolTurns).mockResolvedValue([])
  const card = {
    confirmationId: 'original',
    tool: 'code.run',
    summary: 'Build',
    preview: [{ label: 'Command', before: null, after: 'python acceptance_build.py' }]
  }
  vi.mocked(listSolConfirmations).mockResolvedValue([card])
  await syncSession('p')
  expect(useSolChatStore.getState().sessions.p.items.flatMap((i) => i.confirmations)).toEqual([
    card
  ])
  expect(listSolConfirmations).toHaveBeenCalledWith('p', 'c')
})

it('does not restore cached or historical waiting prose as approval authority', async () => {
  vi.mocked(listSolTurns).mockResolvedValue([
    {
      id: 't',
      conversation_id: 'c',
      role: 'assistant',
      content: 'Waiting for approval',
      attrs: {},
      created_at: '2026-09-13'
    }
  ])
  vi.mocked(listSolConfirmations).mockResolvedValue([])
  await syncSession('p')
  expect(useSolChatStore.getState().sessions.p.items.flatMap((i) => i.confirmations)).toEqual([])
})

it('does not revive a decided card when an earlier history request resolves late', async () => {
  const card = { confirmationId: 'original', tool: 'code.run', summary: 'Build', preview: [] }
  vi.mocked(listSolTurns).mockResolvedValue([])
  let resolve!: (cards: (typeof card)[]) => void
  vi.mocked(listSolConfirmations).mockReturnValue(
    new Promise((r) => {
      resolve = r
    })
  )
  const loading = syncSession('p')
  await Promise.resolve()
  await decideConfirmation('p', 'original', 'approve')
  resolve([card])
  await loading
  expect(decideSolConfirmation).toHaveBeenCalledWith('p', 'original', 'approve')
  expect(useSolChatStore.getState().sessions.p.items.flatMap((i) => i.confirmations)).toEqual([])
})

it('replaces current waiting status after the original restored card is approved', async () => {
  vi.mocked(listSolTurns).mockResolvedValue([])
  vi.mocked(listSolConfirmations).mockResolvedValue([
    { confirmationId: 'original', tool: 'code.run', summary: 'Build', preview: [] }
  ])
  await syncSession('p')
  await decideConfirmation('p', 'original', 'approve')
  const items = useSolChatStore.getState().sessions.p.items
  expect(items.flatMap((i) => i.confirmations)).toEqual([])
  expect(items.at(-1)?.content).toBe('Approval recorded.')
})

it('does not claim completion when an accepted approval has an uncertain execution outcome', async () => {
  vi.mocked(listSolTurns).mockResolvedValue([])
  vi.mocked(listSolConfirmations).mockResolvedValue([
    { confirmationId: 'uncertain', tool: 'code.run', summary: 'Build', preview: [] }
  ])
  // Transport success does not establish that the command started or completed.
  const outcome = { ok: true, value: { uncertain: true, started: false } }
  vi.mocked(decideSolConfirmation).mockResolvedValue(outcome)
  await syncSession('p')
  await decideConfirmation('p', 'uncertain', 'approve')
  const item = useSolChatStore.getState().sessions.p.items.at(-1)
  expect(item?.content).toBe('Approval recorded.')
  expect(item?.content).not.toMatch(/completed/)
})
