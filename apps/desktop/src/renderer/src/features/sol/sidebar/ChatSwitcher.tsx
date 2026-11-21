// The SOL sidebar's chat switcher (sol-sidebar.md §3, Chat switcher): a row under the header
// naming the open chat. Clicking the title drops a searchable list of this project's chats
// (TODAY / THIS WEEK / EARLIER); + starts a new one. Selection and "new chat" are the shared
// chat hook's transitions, so the SOL page and the pill follow the same conversation.
import { useEffect, useId, useRef, useState } from 'react'
import { Icons } from '../../../components/ui/icons.constants'
import { Spinner } from '../../../components/ui/Spinner'
import { relativeTime } from '../../../lib/relativeTime'
import type { SolConversation } from '../solApi'
import type { SolConversationsData } from '../useSolConversations'
import { chatTitle, filterChats, stepHighlight, UNTITLED_CHAT } from './chatSwitcherModel'
import { motionMs, SWITCHER_CLOSE_MS } from './sidebarMotion.constants'

export interface ChatSwitcherProps {
  data: SolConversationsData
  activeConversationId: string | null
  onSelect: (conversationId: string) => void
  onNewChat: () => void
  /** "All chats": the SOL page's full list (rename / delete live there). */
  onShowAll: () => void
}

type Phase = 'closed' | 'open' | 'closing'

/** The list stays mounted through its closing motion, then unmounts. */
function usePhase(open: boolean): Phase {
  const [closing, setClosing] = useState(false)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    setClosing(!open)
  }
  useEffect(() => {
    if (!closing) return
    const timer = window.setTimeout(() => setClosing(false), motionMs(SWITCHER_CLOSE_MS))
    return () => window.clearTimeout(timer)
  }, [closing])
  return open ? 'open' : closing ? 'closing' : 'closed'
}

export function ChatSwitcher(props: ChatSwitcherProps): React.JSX.Element {
  const { data, activeConversationId, onNewChat } = props
  const [open, setOpen] = useState(false)
  const phase = usePhase(open)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const active = data.conversations.find((c) => c.id === activeConversationId)
  const title = active ? chatTitle(active) : UNTITLED_CHAT

  const show = (): void => {
    if (open) return
    data.refresh()
    setOpen(true)
  }
  const hide = (refocus: boolean): void => {
    setOpen(false)
    if (refocus) triggerRef.current?.focus()
  }
  useDismissOnOutsidePress(rootRef, open, () => hide(false))

  return (
    <div
      ref={rootRef}
      className="sol-sb-switch"
      onBlur={(e) => {
        if (open && !rootRef.current?.contains(e.relatedTarget as Node | null)) hide(false)
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        className="sol-sb-switch-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Switch chat: ${title}`}
        title={title}
        onClick={() => (open ? hide(false) : show())}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            show()
          }
        }}
      >
        <span key={activeConversationId ?? 'new'} className="sol-sb-switch-title">
          {title}
        </span>
        <svg
          className="sol-sb-switch-chev"
          width="12"
          height="12"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
      </button>
      <button
        type="button"
        className="sol-sb-icon"
        aria-label="New chat"
        title="New chat"
        onClick={onNewChat}
      >
        <Icons.plus size={15} />
      </button>
      {phase !== 'closed' && (
        <SwitcherList
          {...props}
          closing={phase === 'closing'}
          onDone={() => hide(true)}
          onEscape={() => hide(true)}
        />
      )}
    </div>
  )
}

function useDismissOnOutsidePress(
  ref: React.RefObject<HTMLElement | null>,
  active: boolean,
  dismiss: () => void
): void {
  const latest = useRef(dismiss)
  latest.current = dismiss
  useEffect(() => {
    if (!active) return
    const onPress = (e: PointerEvent): void => {
      if (!ref.current?.contains(e.target as Node)) latest.current()
    }
    document.addEventListener('pointerdown', onPress)
    return () => document.removeEventListener('pointerdown', onPress)
  }, [active, ref])
}

interface SwitcherListProps extends ChatSwitcherProps {
  closing: boolean
  onDone: () => void
  onEscape: () => void
}

function SwitcherList(props: SwitcherListProps): React.JSX.Element {
  const { data, activeConversationId, onSelect, onNewChat, onShowAll, closing, onDone, onEscape } =
    props
  const listId = useId()
  const searchRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const { groups, order } = filterChats(data.conversations, query)
  const [highlight, setHighlight] = useState(() =>
    order.findIndex((c) => c.id === activeConversationId)
  )
  const lit = order[highlight]
  const rowId = (c: SolConversation): string => `${listId}-${c.id}`

  useEffect(() => searchRef.current?.focus({ preventScroll: true }), [])
  useEffect(() => {
    if (lit) document.getElementById(rowId(lit))?.scrollIntoView?.({ block: 'nearest' })
  })

  const pick = (c: SolConversation): void => {
    if (c.id !== activeConversationId) onSelect(c.id)
    onDone()
  }
  const onKeyDown = listKeys({ count: order.length, lit, setHighlight, pick, onEscape })

  return (
    <div className="sol-sb-switch-pop" data-closing={closing || undefined}>
      <label className="sol-sb-switch-search">
        <Icons.search size={13} />
        <input
          ref={searchRef}
          type="text"
          role="combobox"
          aria-label="Search chats"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={lit ? rowId(lit) : undefined}
          placeholder="Search chats"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setHighlight(e.target.value.trim() ? 0 : -1)
          }}
          onKeyDown={onKeyDown}
        />
      </label>
      <div className="sol-sb-switch-scroll">
        <NewChatRow
          onClick={() => {
            onNewChat()
            onDone()
          }}
        />
        <div id={listId} role="listbox" aria-label="Chats in this project">
          {groups.map((g) => (
            <div key={g.label} role="group" aria-label={g.label}>
              <div className="sol-sb-switch-group" aria-hidden="true">
                {g.label}
              </div>
              {g.items.map((c) => (
                <SwitcherRow
                  key={c.id}
                  id={rowId(c)}
                  conversation={c}
                  index={order.indexOf(c)}
                  selected={c.id === activeConversationId}
                  lit={c === lit}
                  onPick={pick}
                />
              ))}
            </div>
          ))}
        </div>
        <ListNote data={data} shown={order.length} />
      </div>
      <SwitcherFoot onShowAll={onShowAll} />
    </div>
  )
}

/** ↑/↓ walk the rows (wrapping), ↵ opens the highlighted one, Esc closes the list only. */
function listKeys(opts: {
  count: number
  lit: SolConversation | undefined
  setHighlight: React.Dispatch<React.SetStateAction<number>>
  pick: (c: SolConversation) => void
  onEscape: () => void
}): (e: React.KeyboardEvent) => void {
  return (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      opts.setHighlight((i) => stepHighlight(i, e.key === 'ArrowDown' ? 1 : -1, opts.count))
    } else if (e.key === 'Enter' && opts.lit) {
      e.preventDefault()
      opts.pick(opts.lit)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      opts.onEscape()
    }
  }
}

function NewChatRow({ onClick }: { onClick: () => void }): React.JSX.Element {
  return (
    <button
      type="button"
      className="sol-sb-switch-new"
      aria-label="Start a new chat"
      onClick={onClick}
    >
      <Icons.plus size={13} />
      New chat
    </button>
  )
}

function SwitcherFoot({ onShowAll }: { onShowAll: () => void }): React.JSX.Element {
  return (
    <div className="sol-sb-switch-foot">
      <span aria-hidden="true">↑↓ · ↵ · ESC</span>
      <button type="button" className="sol-sb-switch-all" onClick={onShowAll}>
        All chats
      </button>
    </div>
  )
}

function SwitcherRow({
  id,
  conversation,
  index,
  selected,
  lit,
  onPick
}: {
  id: string
  conversation: SolConversation
  index: number
  selected: boolean
  lit: boolean
  onPick: (c: SolConversation) => void
}): React.JSX.Element {
  return (
    <div
      id={id}
      role="option"
      aria-selected={selected}
      className="sol-sb-switch-row"
      data-lit={lit || undefined}
      style={{ ['--i' as string]: Math.min(index, 8) }}
      onPointerDown={(e) => e.preventDefault()}
      onClick={() => onPick(conversation)}
    >
      <span className="sol-sb-switch-check">{selected && <Icons.check size={12} />}</span>
      <span className="sol-sb-switch-row-title">{chatTitle(conversation)}</span>
      <span className="sol-sb-switch-when">
        {relativeTime(conversation.updated_at || conversation.created_at)}
      </span>
    </div>
  )
}

function ListNote({
  data,
  shown
}: {
  data: SolConversationsData
  shown: number
}): React.JSX.Element | null {
  const { status, conversations } = data
  if (status === 'loading' && conversations.length === 0)
    return (
      <div className="sol-sb-switch-note">
        <Spinner size={13} />
      </div>
    )
  if (status === 'offline' && conversations.length === 0)
    return <p className="sol-sb-switch-note">Chats unavailable — offline.</p>
  if (conversations.length === 0)
    return <p className="sol-sb-switch-note">No chats yet. Ask SOL anything to start one.</p>
  if (shown === 0) return <p className="sol-sb-switch-note">No chats match.</p>
  return null
}
