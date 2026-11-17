// SOLUSDEV-326 P3: what a press on the slot's card does (docs/contracts/action-gate.md §Cards).
// A gated card is decided, and the decision body is a decision and nothing else. A question card
// (`ask_user`) is answered with a user turn. An edited field is never an argument, and never a
// decision: it answers its card with the new value (§Cards 5), and the server expires the card
// and writes the turn, the value quoted as data. Answers carry the OpenCard, so the page posts
// them to the conversation the card was asked in.
import type { Card, OpenCard } from '@solus/shared-types'
import { QUESTION_TOOL, fieldEdit } from '../../lib/api/card'
import { decideSolConfirmation } from '../../lib/api/resources'
import type { CardButton } from './HwCard'

export const START_CARD: Card = {
  kind: 'offer',
  title: 'Plug in your hardware',
  body: 'Anything plugged into this computer shows up here on its own. There is nothing to import: your CAD, schematic and code are already in the Workspace.',
  more: null,
  field: null,
  primary: 'Connect a robot computer',
  secondary: null,
  receipt: '',
  resumes: false
}
export const EXPIRED_CARD: Card = {
  ...START_CARD,
  kind: 'problem',
  title: 'This card expired',
  body: 'SOL asked something you did not answer in time.',
  primary: 'Ask again'
}
const ASK_AGAIN = 'Please ask me again about the card that expired.'

/** A question is answered with a turn; every other open card decides a parked call. */
export const isQuestion = (open: OpenCard): boolean => open.tool === QUESTION_TOOL

/** What the pressed button reads for 600 ms. A secondary keeps its own label. */
export function resultWord(card: Card, button: CardButton): string {
  if (button === 'secondary') return card.secondary ?? ''
  if (card.kind === 'approval') return 'Approved'
  return /^add/i.test(card.primary) ? 'Added' : 'Done'
}

/** What the slot shows: the local start card, or the caller's open card (expired or not). */
export type ShownCard =
  | { type: 'start'; key: string; card: Card }
  | { type: 'expired' | 'open'; key: string; card: Card; open: OpenCard }

export function shownCard(
  open: OpenCard | null,
  expired: boolean,
  startWanted: boolean
): ShownCard | null {
  if (open && expired)
    return { type: 'expired', key: `expired:${open.confirmation_id}`, card: EXPIRED_CARD, open }
  if (open) return { type: 'open', key: open.confirmation_id, card: open.card, open }
  return startWanted ? { type: 'start', key: 'start', card: START_CARD } : null
}

type MaybeAsync = void | Promise<void>
export interface CardHandlers {
  /** `card` is given for "Ask again": the page sends it in that card's own conversation. */
  onSend: (text: string, card?: OpenCard) => MaybeAsync
  /** The page posts the answer to `card.conversation_id`, the only place the server takes it,
   *  and calls `admitted` once the answer turn was let through (it may wait behind a live one). */
  onAnswer: (
    card: OpenCard,
    choice: 0 | 1,
    text: string | undefined,
    admitted: () => void
  ) => MaybeAsync
  /** The card is over on the server: the chat drops its row from the thread too. `null` is a
   *  refusal (expired, stale, already decided, the tool failed): over, with nothing approved. */
  onDecided: (card: OpenCard, decision: 'approve' | 'reject' | null) => void
  onResume: (card: OpenCard) => void
  onReceipt: (receipt: string) => void
}

export interface Press {
  /** What the pressed button reads once the press went through; never before. */
  word: string
  /** Resolves with the server's own words when it refused (the card is over and the button never
   *  reads `word`), else null. Rejects when nothing was decided: the card stays. */
  run: () => Promise<string | null>
}

/** The server's final word on a card (resources.ts). By name: the class crosses a module
 *  boundary, and a second copy of it would make `instanceof` silently false. */
const isRefusal = (error: unknown): error is Error =>
  error instanceof Error && error.name === 'ConfirmationRefused'

async function decide(
  projectId: string,
  open: OpenCard,
  approve: boolean,
  handlers: CardHandlers
): Promise<string | null> {
  let refusal: string | null = null
  try {
    await decideSolConfirmation(projectId, open.confirmation_id, approve ? 'approve' : 'reject')
  } catch (error) {
    // Refused is the server's final word (expired, stale, already decided, the tool failed): the
    // card is over and SOL may still continue. Anything else never reached a decision and is the
    // caller's to show.
    if (!isRefusal(error)) throw error
    refusal = error.message
  }
  handlers.onDecided(open, refusal === null ? (approve ? 'approve' : 'reject') : null)
  if (approve && refusal === null && open.card.receipt) handlers.onReceipt(open.card.receipt)
  if (open.card.resumes) handlers.onResume(open)
  return refusal
}

function openPress(
  projectId: string,
  open: OpenCard,
  button: CardButton,
  edit: string | null,
  handlers: CardHandlers
): Press {
  const { card } = open
  const primary = button === 'primary'
  const word = resultWord(card, button)
  if (isQuestion(open))
    return {
      word,
      run: async () => {
        // The receipt waits for the page's word that the answer turn was admitted.
        await handlers.onAnswer(open, primary ? 0 : 1, edit ?? undefined, () => {
          if (primary && card.receipt) handlers.onReceipt(card.receipt)
        })
        return null
      }
    }
  if (primary && edit)
    return {
      // An edit answers its card: nothing was approved, so the button keeps its own label and
      // nothing is filed. No decision and no resume: SOL continues from the answer turn.
      word: card.primary,
      run: async () => {
        await handlers.onAnswer(open, 0, edit, () => undefined)
        return null
      }
    }
  return { word, run: () => decide(projectId, open, primary, handlers) }
}

export function pressOf(
  projectId: string,
  shown: ShownCard,
  button: CardButton,
  fieldValue: string,
  handlers: CardHandlers
): Press {
  if (shown.type === 'open')
    return openPress(
      projectId,
      shown.open,
      button,
      fieldEdit(shown.card.field, fieldValue),
      handlers
    )
  // "Ask again" goes where the expired card was asked; the start card to the open conversation.
  const { onSend } = handlers
  const run = async (): Promise<null> => {
    await (shown.type === 'expired' ? onSend(ASK_AGAIN, shown.open) : onSend(START_CARD.primary))
    return null
  }
  return { word: resultWord(shown.card, button), run }
}
