// SOLUSDEV-326 P3: a parked row that carries a Solus-authored card, in the SOL thread
// (docs/wireflows/sol-page.md "Cards in the thread"). Same copy and same result as the Hardware
// page's slot, drawn with the existing .confirmation-card: the card's title, its body with
// `backtick` spans as code chips, and its own button labels. A gated card is decided (primary
// approves, secondary rejects — a decision and nothing else); a question (`ask_user`) is answered
// with a turn and never reaches the decide route. Nor does an edit: a gated card whose field the
// person changed is answered with the new value (contract §Cards 5), and the server expires it.
//
// The card's text is built from model-proposed arguments: it renders as text nodes only.
import { useState } from 'react'
import { QUESTION_TOOL, fieldEdit, splitChips } from '../../lib/api/card'
import type { PendingConfirmation } from '../../lib/api/solStream'
import './ConfirmationCard.css'
import { DecisionFailure, type ConfirmationDecision } from './ConfirmationCard'
import { useConfirmationDecision } from './useConfirmationDecision'

export interface ChatCardProps {
  /** A row whose `card` is set. */
  readonly pending: PendingConfirmation & { card: NonNullable<PendingConfirmation['card']> }
  readonly onDecide: (decision: ConfirmationDecision) => Promise<void>
  /** A question's answer: 0 is the primary button; `text` only when the person typed their own. */
  /** Resolves false when the answer turn did not go through: the card then says so. */
  readonly onAnswer: (choice: 0 | 1, text?: string) => Promise<boolean>
}

type Card = ChatCardProps['pending']['card']

/** Odd pieces are the insides of `backtick` pairs; a lone backtick stays text. */
function CardBody({ body }: { body: string }): React.JSX.Element {
  return (
    <p className="confirmation-card__summary">
      {splitChips(body).map((piece, index) =>
        index % 2 === 1 ? (
          <code key={index} className="confirmation-card__chip">
            {piece}
          </code>
        ) : (
          piece
        )
      )}
    </p>
  )
}

/** What is typed here is never an argument of the parked call (contract §Cards 1): it goes as the
 *  person's answer turn. */
function CardField(props: {
  field: Card['field']
  value: string
  disabled: boolean
  onChange: (value: string) => void
}): React.JSX.Element | null {
  const { field, onChange } = props
  if (!field) return null
  return (
    <label className="confirmation-card__field">
      {field.label}
      <input
        value={props.value}
        disabled={props.disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

/** A press: a question's is always an answer, a gated card's only its primary over an edited
 *  field; every other one is a decision. */
function usePress(
  { pending, onDecide, onAnswer }: ChatCardProps,
  edit: string | undefined
): ReturnType<typeof useConfirmationDecision> {
  const question = pending.tool === QUESTION_TOOL
  return useConfirmationDecision((decision) => {
    const primary = decision === 'approve'
    if (!question && !(primary && edit)) return onDecide(decision)
    return onAnswer(primary ? 0 : 1, edit).then((sent) => {
      if (!sent) throw new Error('SOL did not get your answer. Try again.')
    })
  })
}

export function ChatCard(props: ChatCardProps): React.JSX.Element {
  const { card } = props.pending
  const [value, setValue] = useState(card.field?.value ?? '')
  const { busy, failed, decide } = usePress(props, fieldEdit(card.field, value) ?? undefined)
  const spent = busy !== null || failed?.terminal === true
  const approval = card.kind === 'approval'
  return (
    <section
      aria-label={card.title}
      data-kind={card.kind}
      className={`confirmation-card${approval ? ' confirmation-card--approval' : ''}`}
    >
      <header className="confirmation-card__header">
        <h3>{card.title}</h3>
      </header>
      <CardBody body={card.body} />
      {card.more && <p className="confirmation-card__summary">{card.more}</p>}
      <CardField field={card.field} value={value} disabled={spent} onChange={setValue} />
      <div className="confirmation-card__actions">
        <button
          className="confirmation-card__approve"
          type="button"
          onClick={() => void decide('approve')}
          disabled={spent}
        >
          {card.primary}
        </button>
        {card.secondary && (
          <button type="button" onClick={() => void decide('reject')} disabled={spent}>
            {card.secondary}
          </button>
        )}
      </div>
      {failed && (
        <div role="alert">
          <DecisionFailure failed={failed} />
        </div>
      )}
    </section>
  )
}
