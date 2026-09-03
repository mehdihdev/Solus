// SOLUSDEV-168 — all the `@`-mention picker state, lifted out of the composer.
//
// Extracted because inlining it pushed `Composer` past the complexity ceiling,
// which was a fair signal: caret tracking, the open/dismissed list, keyboard
// navigation and the picked-id bookkeeping are one concern, and the composer's
// own job (text, mode, send) is another.
//
// State lives here rather than in solChatStore on purpose: sessions there
// outlive components and are keyed by project, which is the wrong lifetime for
// a half-typed draft.
import { useRef, useState } from 'react'
import type { Entity } from '../../lib/api/resources'
import {
  activeMentionToken,
  replaceMentionToken,
  MAX_MENTIONS,
  type PickedMention
} from './mentionToken'
import { useMentionSearch } from './useMentionSearch'

export interface MentionPicker {
  listOpen: boolean
  results: readonly Entity[]
  active: Entity | null
  /** Ids to send with this message, in pick order. */
  mentionIds: readonly string[]
  inputRef: React.RefObject<HTMLInputElement | null>
  /** Call on every input change, with the element, before/after setting text. */
  onInput: (el: HTMLInputElement) => void
  /** Call on caret-moving events (keyup, click). */
  onCaretMove: (el: HTMLInputElement) => void
  /** Returns true when the picker consumed the key. */
  onKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => boolean
  choose: (entity: Entity) => void
  /** Clear picked mentions after a send. */
  reset: () => void
}

export function useMentionPicker(
  projectId: string | null,
  input: string,
  setInput: (text: string) => void
): MentionPicker {
  const [caret, setCaret] = useState(0)
  const [picked, setPicked] = useState<readonly PickedMention[]>([])
  const [highlight, setHighlight] = useState(0)
  const [dismissed, setDismissed] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const token = activeMentionToken(input, caret)
  const results = useMentionSearch(projectId, token?.query ?? null)
  const listOpen = token !== null && results.length > 0 && !dismissed
  const active = listOpen ? (results[Math.min(highlight, results.length - 1)] ?? null) : null

  // Ids travel beside the text, never inside it — but a mention the user has
  // since deleted must not still be sent, so the surviving `@Name` decides.
  // Trimmed to the server's cap rather than letting the request 422.
  const mentionIds = picked
    .filter((m) => input.includes(`@${m.name}`))
    .map((m) => m.id)
    .slice(0, MAX_MENTIONS)

  const onCaretMove = (el: HTMLInputElement): void => setCaret(el.selectionStart ?? el.value.length)

  const choose = (entity: Entity): void => {
    if (!token) return
    const next = replaceMentionToken(input, token, entity.name)
    setInput(next.text)
    setCaret(next.caret)
    setHighlight(0)
    setPicked((prev) =>
      prev.some((m) => m.id === entity.id) ? prev : [...prev, { id: entity.id, name: entity.name }]
    )
    // Setting the value resets the DOM caret to the end; restore it once React
    // has committed, or the next keystroke lands in the wrong place.
    queueMicrotask(() => inputRef.current?.setSelectionRange(next.caret, next.caret))
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): boolean => {
    if (!listOpen) return false
    if (event.key === 'ArrowDown') {
      setHighlight((h) => (h + 1) % results.length)
    } else if (event.key === 'ArrowUp') {
      setHighlight((h) => (h - 1 + results.length) % results.length)
    } else if (event.key === 'Enter' && active) {
      // Picking, not sending — Enter must not fire the form while the user is
      // still choosing which node they meant.
      choose(active)
    } else if (event.key === 'Escape') {
      setDismissed(true)
    } else {
      return false
    }
    event.preventDefault()
    return true
  }

  return {
    listOpen,
    results,
    active,
    mentionIds,
    inputRef,
    onInput: (el) => {
      setDismissed(false)
      setHighlight(0)
      onCaretMove(el)
    },
    onCaretMove,
    onKeyDown,
    choose,
    reset: () => {
      setPicked([])
      setCaret(0)
    }
  }
}
