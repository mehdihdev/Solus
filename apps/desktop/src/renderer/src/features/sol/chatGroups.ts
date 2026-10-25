// The chats sidebar's day groups (design template): TODAY / THIS WEEK / EARLIER by the
// conversation's last activity, computed on the client. Order within a group is the
// list's own (newest first from the API). Empty groups are omitted.
import type { SolConversation } from './solApi'

export type ChatGroupLabel = 'TODAY' | 'THIS WEEK' | 'EARLIER'

export interface ChatGroup {
  label: ChatGroupLabel
  items: SolConversation[]
}

const DAY_MS = 24 * 60 * 60 * 1000
const ORDER: readonly ChatGroupLabel[] = ['TODAY', 'THIS WEEK', 'EARLIER']

function labelFor(iso: string, now: number): ChatGroupLabel {
  const at = new Date(iso)
  const today = new Date(now)
  if (
    at.getFullYear() === today.getFullYear() &&
    at.getMonth() === today.getMonth() &&
    at.getDate() === today.getDate()
  )
    return 'TODAY'
  return now - at.getTime() < 7 * DAY_MS ? 'THIS WEEK' : 'EARLIER'
}

export function groupChats(
  conversations: readonly SolConversation[],
  now: number = Date.now()
): ChatGroup[] {
  const groups = new Map<ChatGroupLabel, SolConversation[]>()
  for (const conversation of conversations) {
    const label = labelFor(conversation.updated_at || conversation.created_at, now)
    const bucket = groups.get(label)
    if (bucket) bucket.push(conversation)
    else groups.set(label, [conversation])
  }
  return ORDER.flatMap((label) => {
    const items = groups.get(label)
    return items ? [{ label, items }] : []
  })
}
