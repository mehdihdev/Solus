// SOLUSDEV-326 P3: the turns a card surface starts beside a typed message
// (docs/contracts/action-gate.md §Cards 4, 5, 7): a device notice, the answer to a question card,
// and the resume after a decided card. Each is the store's ordinary streamed turn (`runTurn`) —
// one live turn per project, the same admission — never a second send path. A card belongs to the
// conversation it was asked in, so an answer or a resume first opens that conversation. Each waits
// its turn behind a live one (the store's `afterLiveTurn`): nothing is dropped, nothing live is
// cut off.
import type { OpenCard } from '@solus/shared-types'
import { QUESTION_TOOL } from '../../lib/api/card'
import type { SolActionMode } from './solApi'
import { blankItem } from './solChatItems'
import {
  admitTurn,
  afterLiveTurn,
  patchSession,
  resumeTurn,
  runTurn,
  selectSession,
  useSolChatStore,
  type ChatItem
} from './solChatStore'

/** A surface whose every turn is Build with confirmation, whatever the shared toggle says. */
export type SolSurface = 'hardware'

export interface TurnSettings {
  actionMode: SolActionMode
  forceConfirmation?: boolean
}

/** The ONE place a surface overrides the turn settings: on the Hardware surface every send,
 *  notice, answer and resume parks a card (Guide would refuse the call before it parks). The
 *  server forces the same for notices and card resumes; this covers the typed ones too. */
export function surfaceSettings(
  surface: SolSurface | undefined,
  actionMode: SolActionMode,
  forceConfirmation?: boolean
): TurnSettings {
  return surface === 'hardware'
    ? { actionMode: 'do', forceConfirmation: true }
    : { actionMode, ...(forceConfirmation === undefined ? {} : { forceConfirmation }) }
}

const NOTICE_PROMPT = 'a device you plugged in'
/** The server's word for a missing secondary button (routers/sol_cards.py `NOT_NOW`). */
const NOT_NOW = 'Not now'
let turnSeq = 0

const sessionOf = (projectId: string): ReturnType<typeof selectSession> =>
  selectSession(useSolChatStore.getState(), projectId)

/** The surface's choice when it makes one, else the session's own "Confirm every change". */
const force = (projectId: string, settings: TurnSettings): { forceConfirmation?: true } =>
  (settings.forceConfirmation ?? sessionOf(projectId).forceConfirmation) === true
    ? { forceConfirmation: true }
    : {}

/** What the thread says the moment a notice goes; the server's stored words replace it when
 *  history next loads. */
export const NOTICE_LINE = 'Solus told SOL about a device plugged into this computer.'

/** Drop a notice's line when no reply of SOL's follows it: the server declined the notice on
 *  purpose (debounced, device gone) and the store took its reply row away. */
function dropUnansweredNotice(projectId: string, lineId: string): void {
  patchSession(projectId, (session) => {
    const at = session.items.findIndex((item) => item.id === lineId)
    if (at < 0 || session.items[at + 1]?.role === 'assistant') return session
    return { ...session, items: session.items.filter((item) => item.id !== lineId) }
  })
}

/** "Something was plugged in": the server checks the device and writes the turn's words, so
 *  nothing of the person's is sent and no bubble is drawn: a quiet Solus line marks it, from
 *  the moment it is admitted. A debounced notice vanishes, line and all. */
export function sendNotice(
  projectId: string,
  deviceRef: string,
  settings: TurnSettings
): Promise<boolean> {
  const start = async (): Promise<boolean> => {
    if (!admitTurn(projectId)) return false
    const line: ChatItem = {
      ...blankItem(`local-notice-${++turnSeq}`, 'user', NOTICE_LINE),
      kind: 'notice'
    }
    const sent = await runTurn(projectId, NOTICE_PROMPT, line, {
      projectId,
      content: '',
      actionMode: settings.actionMode,
      notice: { kind: 'device', device_ref: deviceRef },
      ...force(projectId, settings)
    })
    dropUnansweredNotice(projectId, line.id)
    return sent
  }
  return afterLiveTurn(projectId, undefined, start, false)
}

export interface CardAnswer {
  questionId: string
  /** 0 is the card's primary button, 1 its secondary. */
  choice: 0 | 1
  text?: string
  /** The conversation the question was asked in; omitted, the open one. */
  conversationId?: string
}

/** The answer as the server stores the turn (routers/sol_cards.py `answer_prompt`): the button's
 *  label is model-written, so it is quoted as data and never reads as the person's own words.
 *  An answer to a card that is no question is an edit of its field: `<label>: "<value>"`. Only
 *  the live receipt is drawn from this; the server writes the turn itself. */
function answerLabel(projectId: string, answer: CardAnswer): string {
  const row = sessionOf(projectId)
    .items.flatMap((item) => item.confirmations)
    .find((c) => c.confirmationId === answer.questionId)
  const card = row?.card
  if (!card) return 'Answered'
  const typed = answer.text?.trim()
  if (row.tool !== QUESTION_TOOL && card.field && typed)
    return `${card.field.label}: ${JSON.stringify(typed)}`
  const chose = `Chose ${JSON.stringify(answer.choice === 0 ? card.primary : (card.secondary ?? NOT_NOW))}`
  return typed ? `${chose} — ${typed}` : chose
}

/** Take the answered question out of the thread — and a restored "Awaiting your approval" row
 *  it was the last of. Returns how to put it back when the answer never reached SOL. */
function takeQuestion(projectId: string, questionId: string): () => void {
  const holds = (item: ChatItem): boolean =>
    item.confirmations.some((c) => c.confirmationId === questionId)
  const before = sessionOf(projectId).items
  const at = before.findIndex(holds)
  const question = before[at]?.confirmations.find((c) => c.confirmationId === questionId)
  if (!question) return () => undefined
  const holder = before[at]
  patchSession(projectId, (session) => ({
    ...session,
    items: session.items.flatMap((item) => {
      if (!holds(item)) return [item]
      const confirmations = item.confirmations.filter((c) => c.confirmationId !== questionId)
      return item.id.startsWith('approvals-') && confirmations.length === 0
        ? []
        : [{ ...item, confirmations }]
    })
  }))
  return () =>
    patchSession(projectId, (session) => {
      // A history load meanwhile may have brought it back already.
      if (session.items.some(holds)) return session
      const items = session.items.some((item) => item.id === holder.id)
        ? session.items.map((item) =>
            item.id === holder.id
              ? { ...item, confirmations: [...item.confirmations, question] }
              : item
          )
        : [
            ...session.items.slice(0, at),
            { ...holder, confirmations: [question] },
            ...session.items.slice(at)
          ]
      return { ...session, items }
    })
}

/** Answer an open question card with a turn — never the decide route, which knows no question.
 *  The server closes the question and writes the stored turn from the button and the text.
 *  Resolves false, with the question back in the thread, when the turn did not go through. */
export function answerQuestion(
  projectId: string,
  answer: CardAnswer,
  settings: TurnSettings,
  /** Called once the answer turn was let through, before it is sent. */
  onAdmitted?: () => void
): Promise<boolean> {
  const start = async (): Promise<boolean> => {
    if (!admitTurn(projectId)) return false
    onAdmitted?.()
    // Drawn as a receipt naming the button (UserRow), the same as the stored turn after a reload.
    const bubble: ChatItem = {
      ...blankItem(`local-answer-${++turnSeq}`, 'user', answerLabel(projectId, answer)),
      kind: 'answer'
    }
    // The question leaves the thread with the press, as a decided card does.
    const putBack = takeQuestion(projectId, answer.questionId)
    const sent = await runTurn(projectId, bubble.content, bubble, {
      projectId,
      content: '',
      actionMode: settings.actionMode,
      answer: {
        question_id: answer.questionId,
        choice: answer.choice,
        ...(answer.text ? { text: answer.text } : {})
      },
      ...force(projectId, settings)
    })
    // ponytail: a turn that failed after the server took the answer also puts it back; the next
    // press is then refused by the server (the question is closed) and says so in the thread.
    if (!sent) putBack()
    return sent
  }
  return afterLiveTurn(projectId, answer.conversationId, start, false)
}

/** A decided card, as the page's slot knows it. With `card`, its server-sent flag is honoured. */
export type DecidedCard = Pick<OpenCard, 'confirmation_id' | 'conversation_id'> & {
  card?: Pick<OpenCard['card'], 'resumes'>
}

/** SOL continues after a card decided outside the thread (the page's slot), in the card's own
 *  conversation, through the store's one resume. The flag that admits it is the server's: the
 *  row's STORED `card.resumes`, which the server checks again; there is no tool list here. */
export async function resumeCard(
  projectId: string,
  card: DecidedCard,
  settings: TurnSettings
): Promise<void> {
  if (card.card && !card.card.resumes) return
  await resumeTurn(
    projectId,
    card.confirmation_id,
    settings.actionMode,
    settings.forceConfirmation,
    card.conversation_id
  )
}
