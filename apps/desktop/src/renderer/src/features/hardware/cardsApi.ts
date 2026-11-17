// SOLUSDEV-326 P3: the caller's open card in a project (docs/contracts/action-gate.md §Cards,
// item 3), read through the typed client. The body is narrowed here: a card that is not the
// contract's shape is not drawn (the server skips such rows too).
import { openCardsPath, type OpenCard, type OpenCards } from '@solus/shared-types'
import { isCard, isRow, isText } from '../../lib/api/card'
import { api, type ApiClient } from '../../lib/api/client'

function isOpenCard(value: unknown): value is OpenCard {
  return (
    isRow(value) &&
    [value.confirmation_id, value.conversation_id, value.tool, value.expires_at].every(isText) &&
    isCard(value.card)
  )
}

export async function fetchOpenCards(
  projectId: string,
  client: ApiClient = api
): Promise<OpenCards> {
  // The contract's path names the API root; the client's base URL already ends with it.
  const path = openCardsPath(projectId).replace(/^\/api\/v1/, '')
  const body = await client.request<unknown>(path)
  if (!isRow(body) || !isOpenCard(body.card)) return { card: null, queued: 0 }
  return { card: body.card, queued: typeof body.queued === 'number' ? body.queued : 0 }
}
