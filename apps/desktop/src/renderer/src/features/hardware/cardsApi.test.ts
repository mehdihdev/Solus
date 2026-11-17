// SOLUSDEV-326 P3: the open-card read, through the typed client and narrowed at the boundary.
import { expect, it, vi } from 'vitest'
import type { ApiClient } from '../../lib/api/client'
import { fetchOpenCards } from './cardsApi'
import { openCard } from './testing/cards'

const client = (data: unknown): ApiClient =>
  ({ request: vi.fn().mockResolvedValue(data) }) as unknown as ApiClient

it('reads GET …/sol/cards/open of the project', async () => {
  const api = client({ card: openCard(), queued: 2 })
  await expect(fetchOpenCards('p 1', api)).resolves.toEqual({ card: openCard(), queued: 2 })
  expect(api.request).toHaveBeenCalledExactlyOnceWith('/projects/p%201/sol/cards/open')
})

it('answers no card when there is none', async () => {
  await expect(fetchOpenCards('p1', client({ card: null, queued: 0 }))).resolves.toEqual({
    card: null,
    queued: 0
  })
})

it.each([
  ['a body that is not an object', 'nope'],
  ['a card with an unknown kind', { card: openCard({}, { kind: 'banner' as never }), queued: 0 }],
  ['a card with a non-text title', { card: openCard({}, { title: 7 as never }), queued: 0 }],
  [
    'a card with a malformed field',
    { card: openCard({}, { field: { label: 1 } as never }), queued: 0 }
  ],
  ['a row with no confirmation id', { card: { ...openCard(), confirmation_id: null }, queued: 0 }]
])('shows nothing for %s', async (_name, data) => {
  await expect(fetchOpenCards('p1', client(data))).resolves.toEqual({ card: null, queued: 0 })
})
