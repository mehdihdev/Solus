// SOLUSDEV-320 P5-T3d — the history node: a list over GET /history with "Load more".
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { HistoryRow } from '../../lib/api/history'
import { HistoryList } from './HistoryList'

afterEach(cleanup)

function row(over: Partial<HistoryRow>): HistoryRow {
  return {
    id: 'a1',
    type: 'sync.completed',
    domain: 'code',
    actor_id: '0123456789abcdef',
    project_id: 'p1',
    payload: {},
    entity_ids: ['e1', 'e2'],
    why_ref: null,
    created_at: '2026-10-18T10:00:00Z',
    ...over
  }
}

describe('HistoryList', () => {
  it('lists type, domain, short actor, time, entity count and why_ref', async () => {
    const load = vi.fn(async () => ({
      data: [row({}), row({ id: 'a2', type: 'edge.confirmed', why_ref: 'conv-9', entity_ids: [] })],
      meta: {}
    }))
    render(<HistoryList projectId="p1" load={load} />)
    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('sync.completed')
    expect(items[0]).toHaveTextContent('code')
    expect(items[0]).toHaveTextContent('01234567')
    expect(items[0]).not.toHaveTextContent('0123456789abcdef')
    expect(items[0]).toHaveTextContent('2 entities')
    expect(items[1]).toHaveTextContent('why conv-9')
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
    expect(load).toHaveBeenCalledWith('p1', {})
  })

  it('renders system rows that carry no actor and no domain', async () => {
    const load = vi.fn(async () => ({ data: [row({ actor_id: null, domain: null })], meta: {} }))
    render(<HistoryList projectId="p1" load={load} />)
    const [item] = await screen.findAllByRole('listitem')
    expect(item).toHaveTextContent('system')
    expect(item).toHaveTextContent('sync.completed')
  })

  it('loads the next page with the cursor and appends it', async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce({ data: [row({})], meta: { next_cursor: 'c2' } })
      .mockResolvedValueOnce({ data: [row({ id: 'a2' })], meta: { next_cursor: null } })
    render(<HistoryList projectId="p1" load={load} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findAllByRole('listitem')).toHaveLength(2)
    expect(load).toHaveBeenLastCalledWith('p1', { cursor: 'c2' })
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
  })

  it('is honest when empty and when the load fails', async () => {
    const { unmount } = render(
      <HistoryList projectId="p1" load={vi.fn(async () => ({ data: [], meta: {} }))} />
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Nothing recorded yet.')
    unmount()
    render(<HistoryList projectId="p1" load={vi.fn(async () => Promise.reject(new Error('x')))} />)
    expect(await screen.findByRole('status')).toHaveTextContent('Could not load history.')
  })
})
