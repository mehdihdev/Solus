// SOLX-02 / SOLUSDEV-252 S3: the SOL chat surface — one component for the SOL
// window (`panel`) and the full SolScreen page. Consolidates SOL-04/05/06.
//
// SOL-02 obligations pinned by SolChat.test.tsx:
// - citations render from the message event's STRUCTURED array in a dedicated
//   region: plain text spans, never linkified, each display-capped (~64 chars),
//   never parsed out of prose;
// - the tool trace shows tool name + ok/error and each step's args as TEXT — only the
//   server-redacted copy, cut to display size at the parse boundary (solStream);
// - model text renders as markdown through SolMarkdown, which emits React
//   elements only (no HTML injection path — raw HTML is skipped, links are
//   inert, images dropped; pinned by Markdown.test.tsx).
import { Fragment, memo, useCallback, useEffect, useRef } from 'react'
import { Mono } from '../../components/ui/Mono'
import { SolusLogo } from '../../components/ui/SolusLogo'
import { DomainDot } from './domainDot'
import { citationDomain, citationTarget, type CitationTarget } from './domainIds'
import { ReasoningBlock } from './ReasoningBlock'
import { pageAnchors } from './pageAnchors'
import { ArtifactCard } from './ArtifactCard'
import { ConfirmationCard, type ConfirmationDecision } from './ConfirmationCard'
import { commandHeader } from './commandCard'
import { PlanCard } from './PlanCard'
import { AutoRunsView } from './AutoRunRow'
import { ResearchPills } from './ResearchPills'
import { AnswerSourceBadge } from './AnswerSourceBadge'
import { BudgetNotice } from './BudgetNotice'
import { TraceArgs } from './TraceArgs'
import { CommandOutput } from './CommandOutput'
import { DriveStrip } from './DriveStrip'
import { isDriveTool } from './driveProgress'
import { ProcessStrip } from './ProcessStrip'
import { CommandApprovalContext, useCommandShortcut } from './commandHotkey'
import { Composer, type ComposerSend } from './Composer'
import { PillPanel } from './PillPanel'
import { newestPendingCommand, PillTakeover, useTakeoverFocusReturn } from './PillTakeover'
import { SolMarkdown } from './Markdown'
import { ASK_WHAT_IS_THIS, RegionCard } from './RegionCard'
import type { PendingConfirmation } from '../../lib/api/solStream'
import type { SolActionMode, SolScreenshot } from './solApi'
import type { SolRegionPayload } from '../../../../main/sol-window/solWindow'
import { selectSession, setForceConfirmation, useSolChatStore } from './solChatStore'
import {
  regionToScreenshot,
  takeSummonScreenshot,
  useSolActionMode,
  useSolWindowStore
} from './solWindowStore'
import {
  useSolChat,
  type ChatArtifact,
  type ChatItem,
  type SolChat,
  type TraceEntry
} from './useSolChat'

const CITATION_DISPLAY_CAP = 64

/** The message the plan's "Show me how instead" sends, in Guide mode. */
const SHOW_ME_HOW = 'Show me how to do that myself, step by step, instead of doing it for me.'

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
          <TraceArgs args={t.args} />
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

const CHIP: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 5,
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  color: 'var(--mut)',
  background: 'var(--sur2)',
  border: '1px solid var(--bd)',
  borderRadius: 999,
  padding: '2px 8px'
}

/** Provenance chips (design template): the raw `[connector:ref]` token, a domain dot when
 *  the connector maps to one, and — on the page, for `[entity:id]`, `[finding:id]` and
 *  `[solus:section:id]` (SOLUSDEV-321 P7) — a jump to the surface it names. */
function CitationsView({
  citations,
  page,
  onFocusEntity
}: {
  citations: readonly string[]
  page: boolean
  onFocusEntity?: (target: CitationTarget) => void
}): React.JSX.Element | null {
  if (citations.length === 0) return null
  return (
    <div
      data-testid="citations-region"
      style={{ marginTop: 8, borderTop: page ? 0 : '1px solid var(--bd)', paddingTop: 6 }}
    >
      {!page && <Mono size={9}>CITATIONS</Mono>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
        {citations.slice(0, MAX_CITATIONS).map((token, i) => {
          const target = onFocusEntity ? citationTarget(token) : null
          const body = (
            <>
              <DomainDot d={citationDomain(token)} size={5} />
              {capCitation(token)}
            </>
          )
          return target ? (
            <button
              key={`${token}-${i}`}
              type="button"
              className="interactive"
              style={{ ...CHIP, cursor: 'pointer' }}
              onClick={() => onFocusEntity?.(target)}
            >
              {body}
            </button>
          ) : (
            <span key={`${token}-${i}`} style={CHIP}>
              {body}
            </span>
          )
        })}
      </div>
    </div>
  )
}

/** A message the person sent. */
function UserRow({
  item,
  rowClass,
  page
}: {
  item: ChatItem
  rowClass: string
  page: boolean
}): React.JSX.Element {
  return (
    <div className={rowClass} style={{ alignSelf: 'flex-end', maxWidth: page ? '78%' : '85%' }}>
      <div
        style={{
          background: 'var(--sur2)',
          border: '1px solid var(--bd)',
          borderRadius: 6,
          padding: page ? '10px 13px' : '8px 10px',
          fontSize: 12.5,
          lineHeight: 1.5,
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

/** One card per parked action. A turn can park several since SOLUSDEV-168,
 *  and each is approved on its own — approving a batch would suspend the
 *  staleness re-check that makes "what you saw is what runs" true. The pill
 *  (SOLUSDEV-319) groups the non-command ones into a PlanCard that still
 *  decides them one by one; its command cards take over the pill instead
 *  (PillTakeover), so the thread does not show them. */
function Confirmations({
  confirmations,
  reasoning,
  onDecide,
  onShowMe
}: {
  confirmations: readonly PendingConfirmation[]
  /** SOLUSDEV-321 P7: each proposal's reasoning, hung on its own card. */
  reasoning: ChatItem['reasoning']
  onDecide: SolChat['decide']
  onShowMe?: () => void
}): React.JSX.Element {
  const pill = onShowMe !== undefined
  const planned = pill ? confirmations.filter((c) => commandHeader(c) === null) : []
  const cards = pill ? [] : confirmations
  return (
    <>
      {planned.map((step) => (
        <ReasoningBlock
          key={step.confirmationId}
          reasoning={reasoning}
          confirmationId={step.confirmationId}
        />
      ))}
      {planned.length > 0 && onShowMe && (
        <PlanCard steps={planned} onDecide={onDecide} onShowMe={onShowMe} />
      )}
      {cards.map((confirmation) => (
        <Fragment key={confirmation.confirmationId}>
          <ReasoningBlock reasoning={reasoning} confirmationId={confirmation.confirmationId} />
          <ParkedConfirmation pending={confirmation} onDecide={onDecide} />
        </Fragment>
      ))}
    </>
  )
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
  settled,
  page,
  onFocusEntity,
  onShowMe
}: {
  item: ChatItem
  projectId: string
  onDecide: SolChat['decide']
  onFile: SolChat['fileArtifact']
  settled: boolean
  page: boolean
  onFocusEntity?: (target: CitationTarget) => void
  /** SOLUSDEV-319 (pill): given, non-command approvals render as one PlanCard. */
  onShowMe?: () => void
}): React.JSX.Element {
  const rowClass = settled ? 'sol-msg-in sol-msg-settled' : 'sol-msg-in'
  if (item.role === 'user') return <UserRow item={item} rowClass={rowClass} page={page} />
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
  const body = (
    <>
      <TraceView trace={item.trace} />
      <ArtifactsView artifacts={item.artifacts ?? []} projectId={projectId} onFile={onFile} />
      {/* SOLUSDEV-317 §10.1: Build-mode commands that ran without a card. */}
      <AutoRunsView runs={item.autoRuns} />
      {item.content ? (
        <SolMarkdown content={item.content} />
      ) : item.pending ? (
        <div style={MUTED}>thinking…</div>
      ) : null}
      <BudgetNotice budget={item.budgetReached} />
      {item.error && <div style={{ ...MUTED, color: 'var(--err)' }}>{item.error}</div>}
      <AnswerSourceBadge answer={item.answerSource} />
      <ResearchPills research={item.researchSources} projectId={projectId} />
      {/* CTR-03: a destructive action is parked, not executed, until this user
          approves the concrete diff shown here (CLAUDE.md §7). */}
      <Confirmations
        confirmations={confirmations}
        reasoning={item.reasoning}
        onDecide={onDecide}
        onShowMe={onShowMe}
      />
      {/* SOLUSDEV-317: an approved command's output, live while it runs and
          kept with its exit status after the card is gone. */}
      {/* SOLUSDEV-319: a drive.step shows the A3 strip instead, while it runs. */}
      {(item.commandRuns ?? []).map((run) =>
        isDriveTool(run.tool) ? (
          <DriveStrip key={run.confirmationId} run={run} trace={item.trace} />
        ) : (
          <CommandOutput key={run.confirmationId} run={run} />
        )
      )}
      {/* Space for the citations is held while the reply streams, so their
          arrival with the closing `message` frame extends nothing above. */}
      <div style={{ minHeight: item.pending ? CITATIONS_RESERVE_PX : undefined }}>
        <CitationsView citations={item.citations} page={page} onFocusEntity={onFocusEntity} />
      </div>
    </>
  )
  return (
    <AssistantFrame page={page} rowClass={rowClass}>
      {body}
    </AssistantFrame>
  )
})

/** Page (design template): the Solus mark in a gutter and a mono SOL label; the window
 *  and the pill keep their compact rows. */
function AssistantFrame({
  page,
  rowClass,
  children
}: {
  page: boolean
  rowClass: string
  children: React.ReactNode
}): React.JSX.Element {
  if (!page) {
    return (
      <div className={rowClass} style={{ alignSelf: 'stretch', maxWidth: '95%' }}>
        {children}
      </div>
    )
  }
  return (
    <div className={rowClass} style={{ alignSelf: 'stretch', display: 'flex', gap: 12 }}>
      <div style={{ flex: 'none', paddingTop: 2 }} aria-hidden="true">
        <SolusLogo size={18} />
      </div>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <Mono size={10} ls="0.08em">
          SOL
        </Mono>
        <div style={{ fontSize: 13, lineHeight: 1.6 }}>{children}</div>
      </div>
    </div>
  )
}

/** Stick-to-bottom margin: within this many px of the bottom counts as "following". */
const FOLLOW_SLACK_PX = 48

function MessageList({
  chat,
  projectId,
  page,
  onDecide,
  onFocusEntity,
  onShowMe
}: {
  chat: SolChat
  projectId: string
  page: boolean
  onDecide: SolChat['decide']
  onFocusEntity?: (target: CitationTarget) => void
  onShowMe?: () => void
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
      className="sol-thread"
      style={{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: page ? 20 : 10,
        padding: page ? '24px 24px' : 12,
        ...(page ? { width: '100%', boxSizing: 'border-box' } : {})
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
          page={page}
          onFocusEntity={onFocusEntity}
          onShowMe={onShowMe}
        />
      ))}
    </div>
  )
}

export interface SolChatProps {
  projectId: string | null
  /** 'panel' fills a column; 'page' is the SolScreen column; 'pill' is the
   *  SOLUSDEV-319 Ember Pill (panel above, bar below). */
  layout?: 'panel' | 'page' | 'pill'
  /** Pill only: content at the top of the panel (status, Guide tasks) — the
   *  panel opens for it — and the footer's leading/trailing slots. */
  pillTop?: React.ReactNode
  pillFooterStart?: React.ReactNode
  pillFooterEnd?: React.ReactNode
  /** SOLUSDEV-233: a shared chat instance (the SOL page drives the sidebar and
   *  context panel from the same one). Omitted, the surface owns its own. */
  chat?: SolChat
  /** Page: the chat's pinned nodes, sent as `pins` with every send and counted in the header
   *  (SOLUSDEV-321 P0-T3). Only the page also sends the workspace focus: the window and the
   *  pill are their own renderer with neither. */
  pinnedMentionIds?: readonly string[]
  /** Page: the attach menu's two paths. Absent ⇒ no "+" button. */
  onUpload?: (file: File) => void
  onAddNodeFromGraph?: () => void
  /** Page: a verified citation chip opens the surface it names (`citationTarget`, P7). */
  onFocusEntity?: (target: CitationTarget) => void
}

/** The circled region (SOL window only — main pushes it to that renderer).
 *  Attached to exactly ONE send, then dropped from memory (sol-window.md §8) —
 *  but only once that turn settled clean: a failed send keeps it attached so
 *  the person can retry (FIX-2-R M3). A region circled meanwhile is not ours. */
function useRegionSend(
  chat: SolChat,
  mode: SolActionMode,
  forceConfirmation: boolean,
  pageAnchorIds: readonly string[] | null
): {
  region: SolRegionPayload | null
  clearRegion: () => void
  sendWithRegion: ComposerSend
} {
  const region = useSolWindowStore((s) => s.region)
  const clearRegion = useSolWindowStore((s) => s.clearRegion)
  const sendWithRegion: ComposerSend = (text, mentions, thinkHarder) => {
    const anchors = pageAnchorIds ? pageAnchors(pageAnchorIds) : {}
    // A circled region wins; otherwise the picture taken at summon (SOLUSDEV-324).
    const pixels: Promise<SolScreenshot | undefined> = region
      ? Promise.resolve(regionToScreenshot(region))
      : takeSummonScreenshot()
    void pixels
      .then((screenshot) =>
        chat.send(text, mode, mentions, thinkHarder, screenshot, { forceConfirmation, ...anchors })
      )
      .then((ok) => {
        if (ok && region && useSolWindowStore.getState().region === region) clearRegion()
      })
  }
  return { region, clearRegion, sendWithRegion }
}

/** SOLUSDEV-319: the plan's "Show me how instead" — declined, now teach it. */
function useShowMeHow(
  chat: SolChat,
  setMode: (mode: SolActionMode) => void,
  forceConfirmation: boolean
): () => void {
  return useCallback(() => {
    setMode('guide')
    void chat.send(SHOW_ME_HOW, 'guide', [], false, undefined, { forceConfirmation })
  }, [chat, setMode, forceConfirmation])
}

interface SurfaceParts {
  layout: NonNullable<SolChatProps['layout']>
  shortcut: ReturnType<typeof useCommandShortcut>
  thread: React.ReactNode
  hasThread: boolean
  regionCard: React.ReactNode
  strip: React.ReactNode
  composer: React.ReactNode
  pillTop?: React.ReactNode
  /** Pill: the pending command card that takes the pill over, or null. */
  takeover?: PendingConfirmation | null
  onDecide?: SolChat['decide']
}

/** The pill: the usual stack, or a pending command card holding all of it. */
function PillSurface(p: SurfaceParts): React.JSX.Element {
  const stackRef = useRef<HTMLDivElement>(null)
  const active = p.takeover != null
  useTakeoverFocusReturn(active, stackRef)
  const panelOpen = p.hasThread || Boolean(p.regionCard) || Boolean(p.pillTop)
  return (
    <div
      ref={stackRef}
      className="sol-pill-stack"
      data-takeover={active ? 'on' : 'off'}
      onKeyDownCapture={p.shortcut.onKeyDownCapture}
    >
      <div className="sol-pill-normal" inert={active} aria-hidden={active || undefined}>
        <div className="sol-pill-normal-inner">
          {panelOpen && (
            <PillPanel>
              {p.pillTop}
              {p.hasThread && p.thread}
              {p.regionCard}
            </PillPanel>
          )}
          {p.strip}
          {p.composer}
        </div>
      </div>
      {p.onDecide && <PillTakeover pending={p.takeover ?? null} onDecide={p.onDecide} />}
    </div>
  )
}

/** SOLUSDEV-319: the pill stacks a panel (opened only when it has content)
 *  over the bar; the panel and page layouts are one column. */
function Surface(p: SurfaceParts): React.JSX.Element {
  if (p.layout === 'pill') return <PillSurface {...p} />
  return (
    <div
      onKeyDownCapture={p.shortcut.onKeyDownCapture}
      style={{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        width: '100%'
      }}
    >
      {p.thread}
      {p.regionCard}
      {p.strip}
      {p.composer}
    </div>
  )
}

export function SolChat({
  projectId,
  layout = 'panel',
  chat: shared,
  pillTop,
  pillFooterStart,
  pillFooterEnd,
  pinnedMentionIds,
  onUpload,
  onAddNodeFromGraph,
  onFocusEntity
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
  const { region, clearRegion, sendWithRegion } = useRegionSend(
    chat,
    mode,
    forceConfirmation,
    layout === 'page' ? (pinnedMentionIds ?? []) : null
  )
  const showMeHow = useShowMeHow(chat, setMode, forceConfirmation)
  if (!projectId) {
    return (
      <div style={{ ...MUTED, padding: 16, textAlign: 'center' }}>
        Open a project to chat with SOL — it answers with evidence from that project&apos;s graph.
      </div>
    )
  }
  return (
    <CommandApprovalContext.Provider value={shortcut.registry}>
      <Surface
        layout={layout}
        shortcut={shortcut}
        hasThread={chat.items.length > 0}
        thread={
          <MessageList
            chat={chat}
            projectId={projectId}
            page={layout === 'page'}
            onDecide={decideInMode}
            onFocusEntity={onFocusEntity}
            onShowMe={layout === 'pill' ? showMeHow : undefined}
          />
        }
        regionCard={
          region && (
            <RegionCard region={region} onAsk={() => sendWithRegion(ASK_WHAT_IS_THIS, [], false)} />
          )
        }
        strip={
          <ProcessStrip projectId={projectId} refreshSignal={chat.items.length} actionMode={mode} />
        }
        pillTop={pillTop}
        takeover={layout === 'pill' ? newestPendingCommand(chat.items) : null}
        onDecide={decideInMode}
        composer={
          <Composer
            streaming={chat.streaming}
            page={layout === 'page'}
            projectId={projectId}
            mode={mode}
            onModeChange={setMode}
            regionAttached={region !== null}
            onDismissRegion={clearRegion}
            forceConfirmation={forceConfirmation}
            onForceConfirmationChange={(checked) => setForceConfirmation(projectId, checked)}
            onSend={sendWithRegion}
            pill={layout === 'pill'}
            footerStart={pillFooterStart}
            footerEnd={pillFooterEnd}
            onUpload={onUpload}
            onAddNodeFromGraph={onAddNodeFromGraph}
          />
        }
      />
    </CommandApprovalContext.Provider>
  )
}
