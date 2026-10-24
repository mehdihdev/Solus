// SOLX-02 / SOLUSDEV-252 S3: the SOL chat surface — one component for the SOL
// window (`panel`) and the full SolScreen page. Consolidates SOL-04/05/06.
//
// SOL-02 obligations pinned by SolChat.test.tsx:
// - citations render from the message event's STRUCTURED array in a dedicated
//   region: plain text spans, never linkified, each display-capped (~64 chars),
//   never parsed out of prose;
// - the tool trace shows tool name + ok/error only — raw args never reach this
//   component (solStream drops them at the parse boundary);
// - model text renders as markdown through SolMarkdown, which emits React
//   elements only (no HTML injection path — raw HTML is skipped, links are
//   inert, images dropped; pinned by Markdown.test.tsx).
import { memo, useCallback, useEffect, useRef } from 'react'
import { Mono } from '../../components/ui/Mono'
import { ArtifactCard } from './ArtifactCard'
import { ConfirmationCard, type ConfirmationDecision } from './ConfirmationCard'
import { AutoRunsView } from './AutoRunRow'
import { CommandOutput } from './CommandOutput'
import { ProcessStrip } from './ProcessStrip'
import { CommandApprovalContext, useCommandShortcut } from './commandHotkey'
import { Composer } from './Composer'
import { SolMarkdown } from './Markdown'
import { ASK_WHAT_IS_THIS, RegionCard } from './RegionCard'
import type { PendingConfirmation } from '../../lib/api/solStream'
import type { SolScreenshot } from './solApi'
import { selectSession, setForceConfirmation, useSolChatStore } from './solChatStore'
import { regionToScreenshot, useSolActionMode, useSolWindowStore } from './solWindowStore'
import {
  useSolChat,
  type ChatArtifact,
  type ChatItem,
  type SolChat,
  type TraceEntry
} from './useSolChat'

const CITATION_DISPLAY_CAP = 64

/** Display ceiling on the citations region (SEC-M5). */
const MAX_CITATIONS = 12

function capCitation(token: string): string {
  return token.length > CITATION_DISPLAY_CAP
    ? `${token.slice(0, CITATION_DISPLAY_CAP - 1)}…`
    : token
}

const MUTED: React.CSSProperties = { fontSize: 11, color: 'var(--mut)' }

/** Height the citations region will take (rule + label + one row of chips), reserved
 *  under a streaming reply so the body does not jump when citations land (S2). */
const CITATIONS_RESERVE_PX = 52

function TraceView({ trace }: { trace: readonly TraceEntry[] }): React.JSX.Element | null {
  if (trace.length === 0) return null
  return (
    <details data-testid="tool-trace" style={{ marginTop: 6 }}>
      <summary style={{ ...MUTED, cursor: 'pointer', userSelect: 'none' }}>
        {trace.length} tool {trace.length === 1 ? 'step' : 'steps'}
      </summary>
      {trace.map((t) => (
        <div key={t.callId} style={{ ...MUTED, fontFamily: 'var(--font-mono)', padding: '2px 0' }}>
          {/* Same arrow format the backend persists (`tool → outcome`), so live
              and reloaded turns read as one language (SOLUSDEV-233). */}
          {t.tool} → {t.ok === null ? 'running…' : t.ok ? 'ok' : (t.errorCode ?? 'error')}
        </div>
      ))}
    </details>
  )
}

/** SOLUSDEV-252 S5: what a tool produced, each with its "File this to…?" row. */
function ArtifactsView({
  artifacts,
  projectId,
  onFile
}: {
  artifacts: readonly ChatArtifact[]
  projectId: string
  onFile: SolChat['fileArtifact']
}): React.JSX.Element | null {
  if (artifacts.length === 0) return null
  return (
    <>
      {artifacts.map((artifact) => (
        <ArtifactCard
          key={artifact.artifactId}
          projectId={projectId}
          artifact={artifact}
          onFile={(section) => onFile(artifact.artifactId, section)}
        />
      ))}
    </>
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

/** A message the person sent. */
function UserRow({ item, rowClass }: { item: ChatItem; rowClass: string }): React.JSX.Element {
  return (
    <div className={rowClass} style={{ alignSelf: 'flex-end', maxWidth: '85%' }}>
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
      {/* SOLUSDEV-252 S3: a flag, never the pixels (sol-window.md §8). */}
      {item.hasScreenshot && (
        <div style={{ ...MUTED, fontSize: 10, textAlign: 'right', marginTop: 3 }}>
          screen attached
        </div>
      )}
    </div>
  )
}

/** One parked action's card, with a decide callback that is stable for as long
 *  as the card and the surface's decide are, so the card's keyboard approver is
 *  not re-registered on every transcript render (SOLUSDEV-317). */
function ParkedConfirmation({
  pending,
  onDecide
}: {
  pending: PendingConfirmation
  onDecide: SolChat['decide']
}): React.JSX.Element {
  const { confirmationId } = pending
  const decide = useCallback(
    (decision: ConfirmationDecision) => onDecide(confirmationId, decision),
    [onDecide, confirmationId]
  )
  return <ConfirmationCard pending={pending} onDecide={decide} />
}

// memo (S2): a token patch replaces ONE ChatItem immutably, so every other row
// keeps its `item` identity and skips the render. `onDecide` is stable from
// useSolChat. `settled` rows (not the last, not streaming) also opt into CSS
// content-visibility (main.css .sol-msg-settled) so a long transcript is not
// laid out or painted off-screen — native virtualisation, no library.
// ponytail: a windowing library only if a measured long transcript still stutters.
const MessageRow = memo(function MessageRow({
  item,
  projectId,
  onDecide,
  onFile,
  settled
}: {
  item: ChatItem
  projectId: string
  onDecide: SolChat['decide']
  onFile: SolChat['fileArtifact']
  settled: boolean
}): React.JSX.Element {
  const rowClass = settled ? 'sol-msg-in sol-msg-settled' : 'sol-msg-in'
  if (item.role === 'user') return <UserRow item={item} rowClass={rowClass} />
  if (item.role === 'tool') {
    return (
      <div
        className={rowClass}
        style={{ ...MUTED, fontFamily: 'var(--font-mono)', fontSize: 10.5 }}
      >
        {item.content}
      </div>
    )
  }
  const confirmations = item.confirmations
  return (
    <div className={rowClass} style={{ alignSelf: 'stretch', maxWidth: '95%' }}>
      <TraceView trace={item.trace} />
      <ArtifactsView artifacts={item.artifacts ?? []} projectId={projectId} onFile={onFile} />
      {/* SOLUSDEV-317 §10.1: Build-mode commands that ran without a card. */}
      <AutoRunsView runs={item.autoRuns} />
      {item.content ? (
        <SolMarkdown content={item.content} />
      ) : item.pending ? (
        <div style={MUTED}>thinking…</div>
      ) : null}
      {item.error && <div style={{ ...MUTED, color: 'var(--err)' }}>{item.error}</div>}
      {/* CTR-03: a destructive action is parked, not executed, until this user
          approves the concrete diff shown here (CLAUDE.md §7). */}
      {/* One card per parked action. A turn can park several since SOLUSDEV-168,
          and each is approved on its own — approving a batch would suspend the
          staleness re-check that makes "what you saw is what runs" true. */}
      {confirmations.map((confirmation) => (
        <ParkedConfirmation
          key={confirmation.confirmationId}
          pending={confirmation}
          onDecide={onDecide}
        />
      ))}
      {/* SOLUSDEV-317: an approved command's output, live while it runs and
          kept with its exit status after the card is gone. */}
      {(item.commandRuns ?? []).map((run) => (
        <CommandOutput key={run.confirmationId} run={run} />
      ))}
      {/* Space for the citations is held while the reply streams, so their
          arrival with the closing `message` frame extends nothing above. */}
      <div style={{ minHeight: item.pending ? CITATIONS_RESERVE_PX : undefined }}>
        <CitationsView citations={item.citations} />
      </div>
    </div>
  )
})

/** Stick-to-bottom margin: within this many px of the bottom counts as "following". */
const FOLLOW_SLACK_PX = 48

function MessageList({
  chat,
  projectId,
  page,
  onDecide
}: {
  chat: SolChat
  projectId: string
  page: boolean
  onDecide: SolChat['decide']
}): React.JSX.Element {
  const listRef = useRef<HTMLDivElement>(null)
  const followRef = useRef(true)
  const lastCountRef = useRef(0)
  const count = chat.items.length
  // Streamed tokens grow an item's CONTENT without changing the item count, so
  // the follow signal must track text length, not just rows — the old
  // count-only dep is why replies ran off-screen mid-stream. Only the LAST
  // row ever grows (the streaming reply), so its length is the whole signal.
  const textSize = count ? chat.items[count - 1].content.length : 0
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
      {chat.items.map((item, i) => (
        <MessageRow
          key={item.id}
          item={item}
          projectId={projectId}
          onDecide={onDecide}
          onFile={chat.fileArtifact}
          settled={i < count - 1 && !item.pending}
        />
      ))}
    </div>
  )
}

export interface SolChatProps {
  projectId: string | null
  /** 'panel' fills the SOL window; 'page' is the SolScreen column. */
  layout?: 'panel' | 'page'
  /** SOLUSDEV-233: a shared chat instance (the SOL page drives the sidebar and
   *  context panel from the same one). Omitted, the surface owns its own. */
  chat?: SolChat
}

export function SolChat({
  projectId,
  layout = 'panel',
  chat: shared
}: SolChatProps): React.JSX.Element {
  // Hooks run unconditionally; with a shared instance the internal hook is
  // parked on a null project, which is inert (no fetch, no store writes).
  const ownChat = useSolChat(shared ? null : projectId)
  const chat = shared ?? ownChat
  const forceConfirmation = useSolChatStore(
    (state) => selectSession(state, projectId).forceConfirmation ?? false
  )
  const { mode, setMode } = useSolActionMode()
  // SOLUSDEV-317: an approved command resumes SOL in the surface's current mode;
  // Cmd/Ctrl+Enter approves the newest command card inside THIS surface only.
  const decideInMode = useCallback<SolChat['decide']>(
    (confirmationId, decision) => chat.decide(confirmationId, decision, mode),
    [chat, mode]
  )
  const shortcut = useCommandShortcut(chat.items)
  // The circled region (SOL window only — main pushes it to that renderer).
  // Attached to exactly ONE send, then dropped from memory (sol-window.md §8) —
  // but only once that turn settled clean: a failed send keeps it attached so
  // the person can retry (FIX-2-R M3). A region circled meanwhile is not ours.
  const region = useSolWindowStore((s) => s.region)
  const clearRegion = useSolWindowStore((s) => s.clearRegion)
  const sendWithRegion = (
    text: string,
    mentions: readonly string[],
    thinkHarder: boolean
  ): void => {
    const screenshot: SolScreenshot | undefined = region ? regionToScreenshot(region) : undefined
    void chat
      .send(text, mode, mentions, thinkHarder, screenshot, { forceConfirmation })
      .then((ok) => {
        if (ok && region && useSolWindowStore.getState().region === region) clearRegion()
      })
  }
  if (!projectId) {
    return (
      <div style={{ ...MUTED, padding: 16, textAlign: 'center' }}>
        Open a project to chat with SOL — it answers with evidence from that project&apos;s graph.
      </div>
    )
  }
  const page = layout === 'page'
  return (
    <CommandApprovalContext.Provider value={shortcut.registry}>
      <div
        onKeyDownCapture={shortcut.onKeyDownCapture}
        style={{
          flex: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          width: '100%',
          ...(page ? { maxWidth: 800, margin: '0 auto' } : {})
        }}
      >
        <MessageList chat={chat} projectId={projectId} page={page} onDecide={decideInMode} />
        {region && (
          <RegionCard region={region} onAsk={() => sendWithRegion(ASK_WHAT_IS_THIS, [], false)} />
        )}
        <ProcessStrip projectId={projectId} refreshSignal={chat.items.length} actionMode={mode} />
        <Composer
          streaming={chat.streaming}
          page={page}
          projectId={projectId}
          mode={mode}
          onModeChange={setMode}
          regionAttached={region !== null}
          onDismissRegion={clearRegion}
          forceConfirmation={forceConfirmation}
          onForceConfirmationChange={(checked) => setForceConfirmation(projectId, checked)}
          onSend={sendWithRegion}
        />
      </div>
    </CommandApprovalContext.Provider>
  )
}
