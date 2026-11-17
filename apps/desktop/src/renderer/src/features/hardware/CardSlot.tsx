// SOLUSDEV-326 P3: the Hardware page's card slot (docs/wireflows/hardware-onboarding.md). A fixed
// 132 px region that is never blank: the caller's one open card, else what SOL or the plug-in
// inspection is doing, else the start card when the page asks for it, else the idle line.
import { useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import { prefersReducedMotion } from '../settings/settingsMotion'
import { isQuestion, pressOf, shownCard, type CardHandlers } from './cardDecision'
import { useDeviceStore } from './deviceStore'
import { HwCard, type CardButton } from './HwCard'
import { useOpenCard } from './useOpenCard'

/** Motion step 1: how long the pressed button shows its result word. */
const RESULT_MS = 600
/** How long a refused card shows the server's words before it leaves: long enough to read a
 *  sentence. ponytail: a fixed time, not one that grows with the sentence. */
const REFUSED_MS = 2400
/** Motion step 2, matching `.hw-card[data-leaving]` in hwCard.css (and its reduced-motion twin). */
const LEAVE_MS = 160
const REDUCED_LEAVE_MS = 120
/** How long a server card must be on show before a press counts: a click aimed at whatever it
 *  replaced (the start card, the expired card, another card) must never decide it unread. */
const ARRIVAL_GUARD_MS = 450
const SLOT_HEIGHT = 132
const IDLE = 'Nothing needs you right now. Anything you plug in shows up here.'
const FAILED = 'That did not go through. Try again.'

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

export interface CardSlotHandle {
  /** Read the open card again; the page calls it on every SOL stream frame. */
  refresh: () => void
}

export interface CardSlotProps extends CardHandlers {
  projectId: string
  /** What SOL is doing now, from the latest tool_call frame's `working`; null when idle. */
  working: string | null
  /** Offer the local start card while nothing else fills the slot. The page turns it off again
   *  once the person has used it. */
  showStart: boolean
  /** Questions the page is still answering (the answer turn may wait behind a live one, and the
   *  server lists the question as open until it lands): kept out of the slot, so none can be
   *  answered twice. */
  answering?: ReadonlySet<string>
  ref?: React.Ref<CardSlotHandle>
}

/** The plug-in inspection that is running, if any. A device dismissed while its inspection
 *  waited keeps `inspecting` on the server, so a dismissed row never counts. */
function useIdentifying(projectId: string): string | null {
  return useDeviceStore((store) => {
    if (store.projectId !== projectId) return null
    const row = store.devices.find((d) => d.state === 'inspecting' && d.dismissed !== true)
    return row ? `Identifying ${row.headline ?? 'a device'}` : null
  })
}

const LINE_STYLE: React.CSSProperties = {
  boxSizing: 'border-box',
  height: '100%',
  margin: 0,
  padding: '0 16px 0 17px',
  display: 'flex',
  alignItems: 'center',
  gap: 9,
  borderRadius: 6,
  border: '1px dashed var(--bd)',
  fontSize: 12,
  color: 'var(--mut)'
}

function WorkingLine({ text }: { text: string }): React.JSX.Element {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [])
  return (
    <p data-testid="slot-working" style={LINE_STYLE}>
      <span
        className="sol-pulse"
        aria-hidden="true"
        style={{ flex: 'none', width: 7, height: 7, borderRadius: '50%', background: 'var(--acc)' }}
      />
      <span
        style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {text}
      </span>
      {/* Not announced: a live region that ticks every second would never stop talking. */}
      <span aria-hidden="true" style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5 }}>
        · {seconds} s
      </span>
    </p>
  )
}

/** The person's focus is nowhere else: on the page itself, or still in the slot. */
function focusIsFree(slot: HTMLElement): boolean {
  const active = document.activeElement
  return active === null || active === document.body || slot.contains(active)
}

type Shown = ReturnType<typeof shownCard>
type OpenRead = ReturnType<typeof useOpenCard>['open']

/** The open card the slot may show. A card stays through its own press; after that an answered
 *  question is not shown again. */
function unanswered(
  read: OpenRead,
  pressed: unknown,
  answering: ReadonlySet<string> | undefined
): OpenRead {
  return read && !pressed && answering?.has(read.confirmation_id) ? null : read
}

/** The field as the person has it, else as the card gives it. */
function fieldOf(shown: Shown, edit: { key: string; value: string } | null): string | undefined {
  return shown && edit?.key === shown.key ? edit.value : shown?.card.field?.value
}

/** The pressed button's own label. */
const ownLabel = (card: NonNullable<Shown>['card'], button: CardButton): string =>
  button === 'primary' ? card.primary : (card.secondary ?? '')

const leaveMs = (): number => (prefersReducedMotion() ? REDUCED_LEAVE_MS : LEAVE_MS)

/** A server card's arrival: when it took the slot (the press guard reads it), and the focus the
 *  card after the person's own press takes. */
function useArrival(
  slot: React.RefObject<HTMLDivElement | null>,
  shown: Shown
): { answered: React.RefObject<boolean>; arrivedAt: React.RefObject<number> } {
  const answered = useRef(false)
  const arrived = shown?.type === 'open' ? shown.key : null
  const gated = shown?.type === 'open' && !isQuestion(shown.open)
  const arrivedAt = useRef(0)
  // Stamped before the browser paints the card (a passive effect runs after it, and a click in
  // that gap would pass the guard): the guard is up by the time the card can be pressed.
  useLayoutEffect(() => {
    if (arrived) arrivedAt.current = Date.now()
  }, [arrived])
  useEffect(() => {
    const el = slot.current
    if (!arrived || !el || !answered.current) return
    // Motion step 4, narrowed (CLAUDE.md §7): only the card that follows the person's own press
    // takes the focus, once. A card that arrives on its own never does, so a stray Space or Enter
    // cannot decide it. A gated card is focused itself, one Tab from its buttons, never on the
    // button that decides it; a question's primary only writes an answer turn.
    answered.current = false
    if (focusIsFree(el))
      el.querySelector<HTMLElement>(gated ? '.hw-card' : '[data-primary]')?.focus()
  }, [slot, arrived, gated])
  return { answered, arrivedAt }
}

export function CardSlot(props: CardSlotProps): React.JSX.Element {
  const { projectId, working, showStart, answering, ref } = props
  const { open: read, expired, reload, hold, release } = useOpenCard(projectId)
  const identifying = useIdentifying(projectId)
  const slot = useRef<HTMLDivElement>(null)
  const [pressed, setPressed] = useState<{ button: CardButton; word: string } | null>(null)
  const [leaving, setLeaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [edit, setEdit] = useState<{ key: string; value: string } | null>(null)
  useImperativeHandle(ref, () => ({ refresh: reload }), [reload])

  const busy = working ?? identifying
  const shown = shownCard(unanswered(read, pressed, answering), expired, showStart && busy === null)
  const { answered, arrivedAt } = useArrival(slot, shown)
  const fieldValue = fieldOf(shown, edit)

  async function press(button: CardButton): Promise<void> {
    if (!shown || pressed) return
    // CLAUDE.md §7: a card that only just took this place has not been read; the click was for
    // the button it replaced. Every arrival is guarded, the one after a press included.
    if (shown.type === 'open' && Date.now() - arrivedAt.current < ARRIVAL_GUARD_MS) return
    const { word, run } = pressOf(projectId, shown, button, fieldValue ?? '', props)
    const own = ownLabel(shown.card, button)
    setError(null)
    // The button keeps its own label until the press went through: a success word is never
    // shown for a decision the server may still refuse.
    setPressed({ button, word: own })
    answered.current = true
    hold()
    let refusal: string | null
    try {
      refusal = await run()
    } catch {
      // Nothing was decided: the card is still parked, so it stays and can be pressed again.
      answered.current = false
      setPressed(null)
      setError(FAILED)
      release(true)
      return
    }
    // Refused: the card is over, and says why in the server's words before it leaves.
    if (refusal === null) setPressed({ button, word })
    else setError(refusal)
    await sleep(refusal === null ? RESULT_MS : REFUSED_MS)
    setLeaving(true)
    await sleep(leaveMs())
    setPressed(null)
    setLeaving(false)
    setError(null)
    release(false)
  }

  return (
    <div
      ref={slot}
      className="hw-slot"
      data-testid="card-slot"
      aria-live="polite"
      style={{ position: 'relative', height: SLOT_HEIGHT }}
    >
      {shown ? (
        <HwCard
          key={shown.key}
          card={shown.card}
          fieldValue={fieldValue}
          onFieldChange={(value) => setEdit({ key: shown.key, value })}
          onPrimary={() => void press('primary')}
          onSecondary={() => void press('secondary')}
          pressed={pressed}
          leaving={leaving}
          error={error}
        />
      ) : busy !== null ? (
        <WorkingLine key={busy} text={busy} />
      ) : (
        <p style={LINE_STYLE}>{IDLE}</p>
      )}
    </div>
  )
}
