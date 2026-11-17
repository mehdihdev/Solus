// The SOL transcript's item shapes (split from solChatStore.ts, which re-exports them, to keep
// that file under the size ceiling). Types only.
import type { SolusSection } from '../../lib/api/resources'
import type { AutoRun, PendingConfirmation, SolArtifact } from '../../lib/api/solStream'
import type { CommandRun } from './commandRuns'
import type { ResearchSources } from './researchSources'
import type { AnswerSourceInfo, BudgetReachedInfo, ReasonedItem, ToolArgs } from './solStream'
import type { ThinkingInfo } from './thinking'

export interface TraceEntry {
  callId: string
  tool: string
  /** Null while the call is in flight. */
  ok: boolean | null
  errorCode: string | null
  /** The call's args: redacted by the server, bounded for display (SOLUSDEV-321 P1-T6). */
  args?: ToolArgs
  /** SOLUSDEV-326: the tool's own line for what the call is doing, while it runs. */
  working?: string
  /** SOLUSDEV-326: the gate parked this call for the person's OK. It answers one `ok: false` /
   *  `unauthorized`, as it does a real refusal, so this is set only on proof: live, the
   *  `tool_confirmation` frame that follows the result (its id kept, and the decision once made
   *  here); reloaded, the stored row's own "parked, awaiting your approval" (nothing more known). */
  parked?: { confirmationId?: string; decision?: 'approve' | 'reject' }
}

/** SOLUSDEV-252 S5: an artifact in the transcript plus where the user filed it.
 *  `filedTo` lives in the store, not the card, so a remount cannot file twice. */
export interface ChatArtifact extends SolArtifact {
  filedTo: SolusSection | null
}

export interface ChatItem extends ReasonedItem {
  id: string
  role: 'user' | 'assistant' | 'tool'
  /** SOLUSDEV-326: a user-role turn whose words Solus wrote, so it never draws as the person's
   *  bubble: a device notice (`attrs.authored_by`), or the answer to a question card
   *  (`attrs.answer`). Absent on a turn the person typed. */
  kind?: 'notice' | 'answer'
  content: string
  /** SOL-02: structured provenance from the message event — never parsed from prose. */
  citations: readonly string[]
  trace: readonly TraceEntry[]
  pending: boolean
  /** Author-safe failure text (backend error frame or a local transport note). */
  error: string | null
  /** CTR-03: every action this turn parked, in the order they were proposed.
   *  A LIST since SOLUSDEV-168: the turn no longer ends at the first parked
   *  call, so one message can park several. Overwriting a single slot would
   *  silently drop every card but the last — and a dropped card is a
   *  destructive action the user can neither approve nor reject. */
  confirmations: readonly PendingConfirmation[]
  /** SOLUSDEV-252 S5: every artifact a tool produced this turn, in order.
   *  Optional (like hasScreenshot) so reloaded/cached items and fixtures built
   *  before S5 stay valid — absent reads as none. */
  artifacts?: readonly ChatArtifact[]
  /** SOLUSDEV-321 P1-T5: the web sources the turn's research found; absent reads as none. */
  researchSources?: ResearchSources
  /** SOLUSDEV-321 P1-T6: who answered (the graph, no model) and a ceiling the turn hit. */
  answerSource?: AnswerSourceInfo
  budgetReached?: BudgetReachedInfo
  /** SOLUSDEV-326: SOL's thought summary for this reply; absent reads as none. */
  thinking?: ThinkingInfo
  /** SOLUSDEV-252 S3: this user turn carried a screen capture. A flag only —
   *  pixels live in memory for one send and never enter an item. */
  hasScreenshot?: boolean
  /** SOLUSDEV-317: approved commands' output, kept (bounded, plain text) with
   *  the exit status under this message until the conversation is closed.
   *  Runtime only — never cached (solCache keeps role + content). */
  commandRuns?: readonly CommandRun[]
  /** SOLUSDEV-317 §10.1: Build-mode commands that ran without a card, as
   *  compact rows. Runtime only, like commandRuns. */
  autoRuns?: readonly AutoRun[]
}
