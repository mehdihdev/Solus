// SOLUSDEV-326 P3: the card of the Hardware page's slot (docs/wireflows/hardware-onboarding.md,
// docs/contracts/action-gate.md §Cards). Presentation only: the slot decides what a press does.
// Every string of a Card is model- or tool-authored and untrusted: it is printed as text, never
// as HTML, and a backtick span becomes a <code> chip by splitting the text.
import { useLayoutEffect, useRef, useState } from 'react'
import type { Card, CardKind } from '@solus/shared-types'
import { Button } from '../../components/ui/Button'
import { splitChips } from '../../lib/api/card'
import './hwCard.css'

export type CardButton = 'primary' | 'secondary'

export interface HwCardProps {
  card: Card
  /** A step's live line. The Card contract carries none yet, so card data alone draws none. */
  status?: string | null
  /** 0 to 1, beside the status line. */
  progress?: number | null
  /** The field as the person has it; the card's own value when not given. */
  fieldValue?: string
  onFieldChange?: (value: string) => void
  onPrimary?: () => void
  onSecondary?: () => void
  /** The answered button and the word it shows; the other button is disabled meanwhile. */
  pressed?: { button: CardButton; word: string } | null
  leaving?: boolean
  error?: string | null
}

/** About what the 220 px field shows at once; past it the value's length is said beside it. */
const FIELD_FITS = 24

const KICKERS: Partial<Record<CardKind, string>> = {
  approval: 'APPROVAL · THIS CHANGES THE HARDWARE',
  step: 'YOUR STEP',
  problem: 'PROBLEM'
}

function Body({ card }: { card: Card }): React.JSX.Element {
  const ref = useRef<HTMLParagraphElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [clamped, setClamped] = useState(false)
  useLayoutEffect(() => {
    const el = ref.current
    if (el && !expanded) setClamped(el.scrollHeight > el.clientHeight + 1)
  }, [card.body, expanded])
  return (
    <>
      <p ref={ref} className="hw-card__body" data-expanded={expanded}>
        {/* Odd pieces are the insides of `backtick` pairs; a lone backtick stays text. */}
        {splitChips(card.body).map((piece, index) =>
          index % 2 ? (
            <code key={index} className="hw-card__code">
              {piece}
            </code>
          ) : (
            piece
          )
        )}
      </p>
      {expanded && card.more ? <p className="hw-card__body">{card.more}</p> : null}
      {clamped || expanded || card.more ? (
        <button
          type="button"
          className="hw-card__more interactive"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'less' : 'more'}
        </button>
      ) : null}
    </>
  )
}

function Status({ status, progress }: Pick<HwCardProps, 'status' | 'progress'>): React.JSX.Element {
  const percent = Math.round(Math.min(1, Math.max(0, progress ?? 0)) * 100)
  return (
    <div className="hw-card__status">
      <span>
        <span className="hw-card__dot sol-pulse" aria-hidden="true" />
        {status}
      </span>
      {typeof progress === 'number' ? (
        <span
          className="hw-card__progress"
          role="progressbar"
          aria-label="Progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
        >
          <span style={{ width: `${percent}%` }} />
        </span>
      ) : null}
    </div>
  )
}

type Pressed = NonNullable<HwCardProps['pressed']> | null

interface FieldProps {
  field: NonNullable<Card['field']>
  value: string
  disabled: boolean
  onFieldChange?: (value: string) => void
}

function Field({ field, value, disabled, onFieldChange }: FieldProps): React.JSX.Element {
  return (
    <div className="hw-card__field">
      {/* The length sits outside the label, so the field keeps its own name. */}
      <label style={{ display: 'contents' }}>
        <span>{field.label}</span>
        <input
          value={value}
          title={value}
          maxLength={500}
          readOnly={!onFieldChange}
          disabled={disabled}
          onChange={(event) => onFieldChange?.(event.target.value)}
        />
      </label>
      {/* The box shows the start of a long value only: say how much there is. */}
      {value.length > FIELD_FITS ? (
        <span data-testid="field-length">{value.length} characters</span>
      ) : null}
    </div>
  )
}

interface ActionsProps extends Pick<HwCardProps, 'card' | 'onPrimary' | 'onSecondary' | 'error'> {
  pressed: Pressed
  /** The field as it stands; '' when the card has none. */
  value: string
}

function Actions(props: ActionsProps): React.JSX.Element {
  const { card, pressed, value } = props
  const label = (button: CardButton, own: string): string =>
    pressed?.button === button ? pressed.word : own
  // An emptied field has no answer to give: the person fills it in or says "Not now".
  const primaryOff = pressed?.button === 'secondary' || (card.field !== null && !value.trim())
  return (
    <div className="hw-card__actions">
      <Button
        kind="primary"
        size="md"
        data-primary=""
        disabled={primaryOff}
        onClick={props.onPrimary}
      >
        {label('primary', card.primary)}
      </Button>
      {card.secondary ? (
        <Button
          kind="ghost"
          size="md"
          disabled={pressed?.button === 'primary'}
          onClick={props.onSecondary}
        >
          {label('secondary', card.secondary)}
        </Button>
      ) : null}
      {props.error ? (
        <p className="hw-card__error" role="alert">
          {props.error}
        </p>
      ) : null}
    </div>
  )
}

export function HwCard(props: HwCardProps): React.JSX.Element {
  const { card, pressed = null, onFieldChange } = props
  const value = props.fieldValue ?? card.field?.value ?? ''
  return (
    <section
      className="hw-card"
      aria-label={card.title}
      tabIndex={-1}
      data-kind={card.kind}
      data-leaving={props.leaving ? 'true' : undefined}
    >
      <span className="hw-card__edge" aria-hidden="true" />
      <div className="hw-card__content">
        {KICKERS[card.kind] ? <span className="hw-card__kicker">{KICKERS[card.kind]}</span> : null}
        <h3 className="hw-card__title">{card.title}</h3>
        <Body card={card} />
        {card.field ? (
          <Field
            field={card.field}
            value={value}
            disabled={pressed !== null}
            onFieldChange={onFieldChange}
          />
        ) : null}
        {props.status ? <Status status={props.status} progress={props.progress} /> : null}
      </div>
      <Actions
        card={card}
        pressed={pressed}
        value={value}
        onPrimary={props.onPrimary}
        onSecondary={props.onSecondary}
        error={props.error}
      />
    </section>
  )
}
