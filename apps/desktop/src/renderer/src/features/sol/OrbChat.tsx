// SOLX-02: the SOL chat surface — one component for the orb's anchored panel
// and the full SolScreen page. Consolidates SOL-04/05/06.
//
// SOL-02 obligations pinned by OrbChat.test.tsx:
// - citations render from the message event's STRUCTURED array in a dedicated
//   region: plain text spans, never linkified, each display-capped (~64 chars),
//   never parsed out of prose;
// - the tool trace shows tool name + ok/error only — raw args never reach this
//   component (solStream drops them at the parse boundary);
// - model text renders as markdown through SolMarkdown, which emits React
//   elements only (no HTML injection path — raw HTML is skipped, links are
//   inert, images dropped; pinned by Markdown.test.tsx).
import { useEffect, useRef, useState } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import { ClassifyIndicator } from './ClassifyIndicator'
import { ConfirmationCard } from './ConfirmationCard'
import { SolMarkdown } from './Markdown'
import { useClassifyPreview } from './useClassifyPreview'
import type { SolActionMode } from './solApi'
import { useSolChat, type ChatItem, type SolChat, type TraceEntry } from './useSolChat'

const CITATION_DISPLAY_CAP = 64

/** Display ceiling on the citations region (SEC-M5). */
const MAX_CITATIONS = 12

function capCitation(token: string): string {
  return token.length > CITATION_DISPLAY_CAP
    ? `${token.slice(0, CITATION_DISPLAY_CAP - 1)}…`
    : token
}

const MUTED: React.CSSProperties = { fontSize: 11, color: 'var(--mut)' }

function TraceView({ trace }: { trace: readonly TraceEntry[] }): React.JSX.Element | null {
  if (trace.length === 0) return null
  return (
    <details data-testid="tool-trace" style={{ marginTop: 6 }}>
      <summary style={{ ...MUTED, cursor: 'pointer', userSelect: 'none' }}>
        {trace.length} tool {trace.length === 1 ? 'step' : 'steps'}
      </summary>
      {trace.map((t) => (
        <div key={t.callId} style={{ ...MUTED, fontFamily: 'var(--font-mono)', padding: '2px 0' }}>
          {t.tool} — {t.ok === null ? 'running…' : t.ok ? 'ok' : (t.errorCode ?? 'error')}
        </div>
      ))}
    </details>
  )
}

function CitationsView({ citations }: { citations: readonly string[] }): React.JSX.Element | null {
  if (citations.length === 0) return null
  return (
    <div
      data-testid="citations-region"
      style={{ marginTop: 8, borderTop: '1px solid var(--bd)', paddingTop: 6 }}
    >
      <Mono size={9}>CITATIONS</Mono>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
        {citations.slice(0, MAX_CITATIONS).map((token, i) => (
          <span
            key={`${token}-${i}`}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              color: 'var(--mut)',
              background: 'var(--sur2)',
              border: '1px solid var(--bd)',
              borderRadius: 3,
              padding: '2px 6px'
            }}
          >
            {capCitation(token)}
          </span>
        ))}
      </div>
    </div>
  )
}

function MessageRow({
  item,
  onDecide
}: {
  item: ChatItem
  onDecide: SolChat['decide']
}): React.JSX.Element {
  if (item.role === 'user') {
    return (
      <div style={{ alignSelf: 'flex-end', maxWidth: '85%' }}>
        <div
          style={{
            background: 'var(--sur2)',
            border: '1px solid var(--bd)',
            borderRadius: 6,
            padding: '8px 10px',
            fontSize: 12.5,
            whiteSpace: 'pre-wrap'
          }}
        >
          {item.content}
        </div>
      </div>
    )
  }
  if (item.role === 'tool') {
    return (
      <div style={{ ...MUTED, fontFamily: 'var(--font-mono)', fontSize: 10.5 }}>{item.content}</div>
    )
  }
  const confirmation = item.confirmation
  return (
    <div style={{ alignSelf: 'stretch', maxWidth: '95%' }}>
      <TraceView trace={item.trace} />
      {item.content ? (
        <SolMarkdown content={item.content} />
      ) : item.pending ? (
        <div style={MUTED}>thinking…</div>
      ) : null}
      {item.error && <div style={{ ...MUTED, color: 'var(--err)' }}>{item.error}</div>}
      {/* CTR-03: a destructive action is parked, not executed, until this user
          approves the concrete diff shown here (CLAUDE.md §7). */}
      {confirmation && (
        <ConfirmationCard
          pending={confirmation}
          onDecide={(decision) => onDecide(confirmation.confirmationId, decision)}
        />
      )}
      <CitationsView citations={item.citations} />
    </div>
  )
}

/** Stick-to-bottom margin: within this many px of the bottom counts as "following". */
const FOLLOW_SLACK_PX = 48

function MessageList({ chat, page }: { chat: SolChat; page: boolean }): React.JSX.Element {
  const listRef = useRef<HTMLDivElement>(null)
  const followRef = useRef(true)
  const lastCountRef = useRef(0)
  const count = chat.items.length
  // Streamed tokens grow an item's CONTENT without changing the item count, so
  // the follow signal must track total text length, not just rows — the old
  // count-only dep is why replies ran off-screen mid-stream.
  const textSize = chat.items.reduce((n, item) => n + item.content.length, 0)
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    if (count !== lastCountRef.current) {
      // A new row (the user's send, SOL's reply starting) re-engages follow
      // even if they had scrolled up to read history.
      lastCountRef.current = count
      followRef.current = true
    }
    if (followRef.current) el.scrollTop = el.scrollHeight
  }, [count, textSize])
  const handleScroll = (): void => {
    const el = listRef.current
    if (!el) return
    // The user's intent, read from where they left the scrollbar: near the
    // bottom = follow the stream; scrolled up = reading, don't yank them back.
    followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_SLACK_PX
  }
  return (
    <div
      ref={listRef}
      onScroll={handleScroll}
      style={{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        padding: page ? '12px 24px' : 12
      }}
    >
      {chat.status === 'offline' && <Mono size={9.5}>SOL HISTORY UNAVAILABLE — OFFLINE</Mono>}
      {chat.status === 'ready' && count === 0 && (
        <div style={{ ...MUTED, textAlign: 'center', padding: '18px 8px' }}>
          Ask SOL about your robot — it answers with evidence from the graph.
        </div>
      )}
      {chat.items.map((item) => (
        <MessageRow key={item.id} item={item} onDecide={chat.decide} />
      ))}
    </div>
  )
}

type ActionModeLabel = 'Guide' | 'Do'

function Composer({
  streaming,
  page,
  onSend
}: {
  streaming: boolean
  page: boolean
  onSend: (text: string, mode: SolActionMode) => void
}): React.JSX.Element {
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<ActionModeLabel>('Guide')
  const classify = useClassifyPreview(input)
  const empty = input.trim() === ''

  const submit = (): void => {
    const text = input.trim()
    if (!text || streaming) return
    onSend(text, mode === 'Do' ? 'do' : 'guide')
    setInput('')
    classify.resetOverride()
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      style={{
        borderTop: '1px solid var(--bd)',
        padding: page ? '10px 24px 14px' : 10,
        display: 'flex',
        flexDirection: 'column',
        gap: 6
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about a signal, a change, a part…"
          aria-label="Message SOL"
          style={{
            flex: 1,
            minWidth: 0,
            background: 'var(--sur)',
            border: '1px solid var(--bd)',
            borderRadius: 4,
            color: 'var(--tx)',
            fontFamily: 'var(--font-ui)',
            fontSize: 12.5,
            padding: '8px 10px',
            outline: 'none'
          }}
        />
        <Segmented
          options={['Guide', 'Do'] as const}
          value={mode}
          onChange={setMode}
          size="sm"
          ariaLabel="SOL action mode"
        />
        <button
          type="submit"
          disabled={streaming || empty}
          style={{
            background: 'var(--acc)',
            color: 'var(--acc-ink)',
            border: 'none',
            borderRadius: 4,
            padding: '7px 14px',
            fontSize: 12,
            fontWeight: 600,
            cursor: streaming ? 'wait' : 'pointer',
            opacity: streaming || empty ? 0.6 : 1
          }}
        >
          Send
        </button>
      </div>
      <ClassifyIndicator
        preview={classify.preview}
        override={classify.override}
        onOverride={classify.setOverride}
        onReset={classify.resetOverride}
      />
    </form>
  )
}

export interface OrbChatProps {
  projectId: string | null
  /** 'panel' fills the orb popover; 'page' is the SolScreen column. */
  layout?: 'panel' | 'page'
}

export function OrbChat({ projectId, layout = 'panel' }: OrbChatProps): React.JSX.Element {
  const chat = useSolChat(projectId)
  if (!projectId) {
    return (
      <div style={{ ...MUTED, padding: 16, textAlign: 'center' }}>
        Open a project to chat with SOL — it answers with evidence from that project&apos;s graph.
      </div>
    )
  }
  const page = layout === 'page'
  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        ...(page ? { maxWidth: 800, margin: '0 auto' } : {})
      }}
    >
      <MessageList chat={chat} page={page} />
      <Composer
        streaming={chat.streaming}
        page={page}
        onSend={(text, mode) => void chat.send(text, mode)}
      />
    </div>
  )
}
