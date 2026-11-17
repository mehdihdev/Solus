// SOLUSDEV-326 P3: the Hardware page (docs/wireflows/hardware-onboarding.md). Regions keep their
// place and size: the header with the one permanent button, the card slot, the "Done so far" row
// and the parts list. SOL is the shell's sidebar (SolSidebarHost), not a panel of this page; the
// page's chat (the Hardware surface: every turn goes as Build with confirmation) drives the slot
// and is the same session the sidebar shows.
import { useEffect, useRef, useState } from 'react'
import type { OpenCard } from '@solus/shared-types'
import { Button } from '../../components/ui/Button'
import { clearDeviceDismissals } from '../../lib/api/hardware'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSolChat, type SolChat } from '../sol/useSolChat'
import type { CardHandlers } from './cardDecision'
import { CardSlot, type CardSlotHandle } from './CardSlot'
import { isOffer, useDeviceStore } from './deviceStore'
import { DoneSoFar } from './DoneSoFar'
import { PartsList } from './PartsList'
import { usePlugInNotice } from './usePlugInNotice'

/** The page root, with `.hw-page`: the container the parts list's narrow-width rules measure
 *  (partsList.css), so they follow the room left beside the docked SOL sidebar. */
const COLUMN: React.CSSProperties = { flex: 1, minWidth: 0, overflow: 'auto' }
const MAIN: React.CSSProperties = { maxWidth: 980, padding: '24px 28px', boxSizing: 'border-box' }

function Header({ onAddHardware }: { onAddHardware?: () => void }): React.JSX.Element {
  return (
    <header style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600, lineHeight: 1.3 }}>Hardware</h1>
        <p style={{ margin: '4px 0 0', fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.5 }}>
          Robot parts Solus knows about, and whether each one is connected.
        </p>
      </div>
      <Button kind="ghost" size="md" disabled={!onAddHardware} onClick={onAddHardware}>
        + Add hardware
      </Button>
    </header>
  )
}

/** Changes when a frame that can open a card lands (a tool call, a parked card) and when the turn
 *  starts or ends.
 *  ponytail: not every token — the slot also polls every 5 s, so text frames are left to that. */
const framePulse = (chat: SolChat): number =>
  chat.items.reduce((n, item) => n + item.trace.length + item.confirmations.length, 0) * 2 +
  (chat.streaming ? 1 : 0)

function HardwarePage({ projectId }: { projectId: string }): React.JSX.Element {
  const chat = useSolChat(projectId, 'hardware')
  const slot = useRef<CardSlotHandle>(null)
  // The start card: null follows the list (shown while it is empty), true after "+ Add
  // hardware", false once the person has used it.
  const [start, setStart] = useState<boolean | null>(null)
  const [empty, setEmpty] = useState(false)
  const [receipts, setReceipts] = useState<readonly string[]>([])
  const [decided, setDecided] = useState(0)
  const [answering, setAnswering] = useState<ReadonlySet<string>>(() => new Set())
  usePlugInNotice(projectId, chat.sendNotice)

  const pulse = framePulse(chat)
  useEffect(() => {
    slot.current?.refresh()
  }, [pulse])

  // The slot's presses start turns and never wait for them: SOL answers in its sidebar, and the
  // button settles on the press, not on the reply. A press made while SOL is replying is sent
  // after that turn (the Hardware surface queues it). The start card leaves on the press — `send`
  // settles when the turn ends, and a card still on show mid-turn could be pressed twice — and
  // comes back only when its sentence never reached SOL. A send for a card (an edit, "Ask again")
  // goes to that card's conversation and leaves the start card as it is.
  const onSend = (text: string, card?: OpenCard): void => {
    const into = card ? { conversationId: card.conversation_id } : undefined
    const was = start
    if (!card) setStart(false)
    const sending = chat.send(text, 'do', undefined, undefined, undefined, into)
    void sending
      .catch(() => false)
      .then((sent) => {
        if (!sent && !card) setStart((now) => (now === false ? was : now))
      })
  }
  // The answer turn may wait behind a live one, and until it lands the server still lists the
  // question as open: it is kept out of the slot meanwhile, and comes back only if the answer
  // never reached SOL.
  const onAnswer: CardHandlers['onAnswer'] = (card, choice, text, admitted) => {
    const id = card.confirmation_id
    const back = (): void => setAnswering((was) => new Set([...was].filter((q) => q !== id)))
    setAnswering((was) => new Set([...was, id]))
    const answering = chat.answer(id, choice, text, card.conversation_id, undefined, admitted)
    void answering.then((sent) => {
      if (!sent) back()
    }, back)
  }
  const onDecided: CardHandlers['onDecided'] = (card, decision) =>
    chat.cardDecided(card.confirmation_id, decision)
  const onResume = (card: OpenCard): void => {
    setDecided((n) => n + 1)
    void chat.resumeCard(card)
  }
  const onReceipt = (receipt: string): void => {
    setDecided((n) => n + 1)
    setReceipts((was) => [...was, receipt])
  }
  const addHardware = (): void => {
    // ponytail: a failed clear is not shown — a hosted API has no machine to clear (409), and the
    // start card is the answer either way.
    clearDeviceDismissals(projectId).catch(() => undefined)
    // What is plugged in and still unclaimed is announced to SOL again (usePlugInNotice): each
    // was announced once already this session, and the person is asking for its card again.
    const store = useDeviceStore.getState()
    if (store.projectId === projectId)
      store.owe(store.devices.filter(isOffer).map((row) => row.device_ref as string))
    setStart(true)
  }

  return (
    <div className="hw-page" style={COLUMN}>
      <div style={MAIN}>
        <Header onAddHardware={addHardware} />
        <div style={{ marginTop: 20 }}>
          <CardSlot
            ref={slot}
            projectId={projectId}
            working={chat.working}
            showStart={start ?? empty}
            answering={answering}
            onSend={onSend}
            onAnswer={onAnswer}
            onDecided={onDecided}
            onResume={onResume}
            onReceipt={onReceipt}
          />
        </div>
        <DoneSoFar receipts={receipts} />
        {/* Read again after a decision and when a SOL turn ends: either may have added parts. */}
        <PartsList
          projectId={projectId}
          refreshKey={`${decided}:${chat.streaming}`}
          onRead={setEmpty}
        />
      </div>
    </div>
  )
}

export function HardwareScreen(): React.JSX.Element {
  const projectId = useWorkspaceStore((state) => state.project?.id ?? null)
  if (projectId) return <HardwarePage key={projectId} projectId={projectId} />
  return (
    <div className="hw-page" style={COLUMN}>
      <div style={MAIN}>
        <Header />
      </div>
    </div>
  )
}
