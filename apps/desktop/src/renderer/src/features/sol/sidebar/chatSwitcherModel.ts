// The SOL sidebar chat switcher's list logic (sol-sidebar.md §3, Chat switcher): the day groups
// filtered by the search text, the flat keyboard order, and arrow-key stepping. Pure.
import { groupChats, type ChatGroup } from '../chatGroups'
import type { SolConversation } from '../solApi'

export const UNTITLED_CHAT = 'New chat'

export interface FilteredChats {
  groups: ChatGroup[]
  /** The rows in the order they are drawn: what ↑/↓ walk through. */
  order: SolConversation[]
}

export function chatTitle(conversation: SolConversation): string {
  return conversation.title?.trim() || UNTITLED_CHAT
}

export function filterChats(
  conversations: readonly SolConversation[],
  query: string,
  now: number = Date.now()
): FilteredChats {
  const needle = query.trim().toLowerCase()
  const shown = needle
    ? conversations.filter((c) => chatTitle(c).toLowerCase().includes(needle))
    : conversations
  const groups = groupChats(shown, now)
  return { groups, order: groups.flatMap((g) => g.items) }
}

/** One ↑/↓ step through `length` rows, wrapping; -1 means nothing highlighted. */
export function stepHighlight(index: number, delta: 1 | -1, length: number): number {
  if (length === 0) return -1
  if (index < 0) return delta > 0 ? 0 : length - 1
  return (index + delta + length) % length
}
