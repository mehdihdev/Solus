// SOL chat screen, ported from SolScreen in TestDesign/app/sol.jsx: scripted
// diagnoses with the cross-domain evidence chain, Guide/Expert answer modes
// (ADR-016), followup chips, free-text routing, and the apply-&-flash flow.
// Chat lives in the shell store so the transcript survives screen switches.
import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { DomainChip } from '../../components/ui/DomainChip'
import { Mono } from '../../components/ui/Mono'
import { Segmented } from '../../components/ui/Segmented'
import { SolOrb } from '../../components/ui/SolOrb'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import { useSettingsStore, type SolMode } from '../../store/settingsStore'
import { SOL_SCRIPTS, type SolScript } from '../workspace/workspaceData.constants'
import { useShellStore, type ChatMessage } from '../workspace/shellStore'

const THINK_MS = 1700
const FOLLOWUP_THINK_MS = 1400
const FLASH_STEP_MS = 1100
const FLASH_DONE_MS = 3 * FLASH_STEP_MS + 600
const FLASH_STEPS = [
  'Compiling firmware (gcc-arm, -O2)…',
  'Flashing STM32H743 over SWD…',
  'Verifying — watching τ_FL_knee…'
] as const

type FlashState = 'idle' | 'busy' | 'done'

interface SolScreenProps {
  onOpenAlert: (id: string) => void
  onStartTour: () => void
}

/** Route free text to the script it most plausibly asks about. Pure. */
export function routeQuestion(q: string): string {
  const lower = q.toLowerCase()
  if (/oscill|4\.2|knee|anomal|ripple|vibrat/.test(lower)) return 'anomaly'
  if (/u4|drv|driver|alert|swap|pin/.test(lower)) return 'alertq'
  return 'hello'
}

export function SolScreen({ onOpenAlert, onStartTour }: SolScreenProps): React.JSX.Element {
  const solMode = useSettingsStore((s) => s.solMode)
  const setSolMode = useSettingsStore((s) => s.setSolMode)
  const chat = useShellStore((s) => s.chat)
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const [flashState, setFlashState] = useState<FlashState>('idle')
  const [flashStep, setFlashStep] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [chat, thinking, flashState])

  const send = (key: string, text: string): void => {
    if (thinking) return
    useShellStore.getState().appendChat({ role: 'user', text })
    setThinking(true)
    setTimeout(() => {
      setThinking(false)
      useShellStore.getState().appendChat({ role: 'sol', scriptKey: key })
    }, THINK_MS)
    setInput('')
  }
  const sendFollowup = (scriptKey: string, followupIndex: number, q: string): void => {
    if (thinking) return
    useShellStore.getState().appendChat({ role: 'user', text: q })
    setThinking(true)
    setTimeout(() => {
      setThinking(false)
      useShellStore.getState().appendChat({ role: 'sol', followupOf: scriptKey, followupIndex })
    }, FOLLOWUP_THINK_MS)
  }
  const sendFree = (): void => {
    const q = input.trim()
    if (!q) return
    send(routeQuestion(q), q)
  }
  const flash = (): void => {
    setFlashState('busy')
    ;[1, 2].forEach((i) => setTimeout(() => setFlashStep(i), i * FLASH_STEP_MS))
    setTimeout(() => {
      setFlashState('done')
      const shell = useShellStore.getState()
      shell.resolveAlert('a1')
      shell.setAnomaly('resolved')
    }, FLASH_DONE_MS)
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0 }}>
      <SolHeader thinking={thinking} solMode={solMode} setSolMode={setSolMode} />
      <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        <div
          style={{
            maxWidth: 800,
            margin: '0 auto',
            padding: '8px 24px 16px',
            display: 'flex',
            flexDirection: 'column',
            gap: 16
          }}
        >
          {chat.length === 0 && !thinking && <EmptyState />}
          {chat.map((m, i) => (
            <MessageView
              key={i}
              message={m}
              solMode={solMode}
              flashState={flashState}
              flashStep={flashStep}
              onFlash={flash}
              onOpenAlert={onOpenAlert}
            />
          ))}
          {thinking && <ThinkingRow />}
        </div>
      </div>
      <InputBar
        input={input}
        setInput={setInput}
        onSend={sendFree}
        chat={chat}
        onSendScript={send}
        onSendFollowup={sendFollowup}
        onStartTour={onStartTour}
      />
    </div>
  )
}

function SolHeader({
  thinking,
  solMode,
  setSolMode
}: {
  thinking: boolean
  solMode: SolMode
  setSolMode: (m: SolMode) => void
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '16px 24px 10px',
        maxWidth: 800,
        width: '100%',
        margin: '0 auto',
        boxSizing: 'border-box'
      }}
    >
      <SolOrb size={56} pulse={thinking} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>SOL</div>
        <Mono size={9.5} color={thinking ? 'var(--acc)' : 'var(--mut)'}>
          {thinking ? 'REASONING OVER THE GRAPH…' : 'GROUNDED IN 247 NODES · 31 CROSS-DOMAIN LINKS'}
        </Mono>
      </div>
      <div style={{ textAlign: 'right' }}>
        <Segmented options={['Guide', 'Expert']} value={solMode} onChange={setSolMode} />
        <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 5 }}>
          {solMode === 'Guide' ? 'explains and teaches' : 'terse, direct'}
        </div>
      </div>
    </div>
  )
}

function EmptyState(): React.JSX.Element {
  return (
    <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--mut)' }}>
      <div style={{ fontSize: 13.5, lineHeight: 1.6 }}>
        Ask SOL anything about your robot.
        <br />
        It answers with the cross-domain chain of evidence.
      </div>
    </div>
  )
}

function ThinkingRow(): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
      <SolOrb size={26} pulse />
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--mut)' }}>
        tracing FL knee through 4 domains…
      </span>
    </div>
  )
}

function MessageView({
  message,
  solMode,
  flashState,
  flashStep,
  onFlash,
  onOpenAlert
}: {
  message: ChatMessage
  solMode: SolMode
  flashState: FlashState
  flashStep: number
  onFlash: () => void
  onOpenAlert: (id: string) => void
}): React.JSX.Element | null {
  if (message.role === 'user') {
    return (
      <div
        style={{
          alignSelf: 'flex-end',
          maxWidth: '78%',
          background: 'var(--sur2)',
          border: '1px solid var(--bd)',
          borderRadius: '10px 10px 2px 10px',
          padding: '10px 14px',
          fontSize: 13,
          lineHeight: 1.55
        }}
      >
        {message.text}
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', gap: 12, maxWidth: '94%' }}>
      <span style={{ marginTop: 2, flexShrink: 0 }}>
        <SolOrb size={26} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <SolAnswer
          message={message}
          solMode={solMode}
          flashState={flashState}
          flashStep={flashStep}
          onFlash={onFlash}
          onOpenAlert={onOpenAlert}
        />
      </div>
    </div>
  )
}

function SolAnswer({
  message,
  solMode,
  flashState,
  flashStep,
  onFlash,
  onOpenAlert
}: {
  message: ChatMessage
  solMode: SolMode
  flashState: FlashState
  flashStep: number
  onFlash: () => void
  onOpenAlert: (id: string) => void
}): React.JSX.Element | null {
  if (message.role !== 'sol') return null
  if ('followupOf' in message) {
    const followup = SOL_SCRIPTS[message.followupOf]?.followups[message.followupIndex]
    if (!followup) return null
    return <AnswerText guide={followup.guide} expert={followup.expert} solMode={solMode} />
  }
  const script = SOL_SCRIPTS[message.scriptKey]
  if (!script) return null
  const isAnomaly = message.scriptKey === 'anomaly'
  return (
    <DiagnosisCard
      script={script}
      solMode={solMode}
      onFlash={isAnomaly ? onFlash : undefined}
      flashState={isAnomaly ? flashState : 'idle'}
      flashStep={flashStep}
      onOpenAlert={onOpenAlert}
    />
  )
}

function AnswerText({
  guide,
  expert,
  solMode
}: {
  guide: string
  expert: string
  solMode: SolMode
}): React.JSX.Element {
  const isExpert = solMode === 'Expert'
  return (
    <div
      style={{
        fontSize: isExpert ? 12 : 12.8,
        lineHeight: 1.7,
        color: 'var(--tx)',
        fontFamily: isExpert ? 'var(--font-mono)' : 'var(--font-ui)',
        whiteSpace: 'pre-wrap'
      }}
    >
      {isExpert ? expert : guide}
    </div>
  )
}

function DiagnosisCard({
  script,
  solMode,
  onFlash,
  flashState,
  flashStep,
  onOpenAlert
}: {
  script: SolScript
  solMode: SolMode
  onFlash?: () => void
  flashState: FlashState
  flashStep: number
  onOpenAlert: (id: string) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {script.likely && (
        <Card pad={14} style={{ background: 'var(--sur)' }}>
          <Mono size={9} color="var(--acc)">
            DIAGNOSIS
          </Mono>
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 11.5, color: 'var(--mut)', padding: '2px 0' }}>
              Likely cause
            </div>
            <div
              style={{
                fontSize: 12.5,
                lineHeight: 1.55,
                padding: '4px 0 8px',
                borderBottom: '1px solid var(--bd)'
              }}
            >
              {script.likely}
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--mut)', padding: '8px 0 2px' }}>
              Root cause
            </div>
            <div style={{ fontSize: 12.5, lineHeight: 1.55 }}>{script.root}</div>
          </div>
          {script.evidence && <EvidenceList evidence={script.evidence} />}
          {script.fixDesc && (
            <SuggestedFix
              fixDesc={script.fixDesc}
              onFlash={onFlash}
              flashState={flashState}
              flashStep={flashStep}
              onOpenAlert={onOpenAlert}
            />
          )}
        </Card>
      )}
      <AnswerText guide={script.guide} expert={script.expert} solMode={solMode} />
    </div>
  )
}

function EvidenceList({
  evidence
}: {
  evidence: NonNullable<SolScript['evidence']>
}): React.JSX.Element {
  return (
    <div style={{ marginTop: 12 }}>
      <Mono size={9}>EVIDENCE FROM THE GRAPH</Mono>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 8 }}>
        {evidence.map((ev) => (
          <div key={ev.l} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <DomainChip d={ev.d} small />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{ev.l}</span>
            <span style={{ fontSize: 10.5, color: 'var(--mut)' }}>— {ev.n}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function SuggestedFix({
  fixDesc,
  onFlash,
  flashState,
  flashStep,
  onOpenAlert
}: {
  fixDesc: string
  onFlash?: () => void
  flashState: FlashState
  flashStep: number
  onOpenAlert: (id: string) => void
}): React.JSX.Element {
  return (
    <div style={{ marginTop: 12, borderTop: '1px solid var(--bd)', paddingTop: 12 }}>
      <Mono size={9} color="var(--acc)">
        SUGGESTED FIX
      </Mono>
      <div style={{ fontSize: 12.5, lineHeight: 1.55, marginTop: 6 }}>{fixDesc}</div>
      {onFlash && flashState === 'idle' && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <Button kind="primary" size="sm" onClick={onFlash}>
            Apply & flash to robot
          </Button>
          <Button kind="ghost" size="sm" onClick={() => onOpenAlert('a1')}>
            Review diff
          </Button>
        </div>
      )}
      {flashState === 'busy' && <FlashProgress flashStep={flashStep} />}
      {flashState === 'done' && (
        <div
          style={{
            marginTop: 10,
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            fontSize: 12,
            color: 'var(--ok)'
          }}
        >
          <Icons.check size={14} /> Flashed · τ_FL_knee stable for 30 s · alert resolved
        </div>
      )}
    </div>
  )
}

function FlashProgress({ flashStep }: { flashStep: number }): React.JSX.Element {
  return (
    <div style={{ marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 10.5 }}>
      {FLASH_STEPS.map((s, i) => (
        <div
          key={s}
          style={{
            display: 'flex',
            gap: 9,
            alignItems: 'center',
            padding: '3px 0',
            color: i < flashStep ? 'var(--ok)' : i === flashStep ? 'var(--acc)' : 'var(--mut)',
            opacity: i > flashStep ? 0.45 : 1
          }}
        >
          {i < flashStep ? (
            <span>✓</span>
          ) : i === flashStep ? (
            <Spinner size={10} />
          ) : (
            <span style={{ width: 10 }} />
          )}
          {s}
        </div>
      ))}
    </div>
  )
}

interface Chip {
  label: string
  fn: () => void
  tour?: boolean
}

/** Suggestion chips: unasked scripts first, then unasked followups of the last
 * scripted answer, capped at two, plus the tour entry. Pure. */
export function buildChips(
  chat: readonly ChatMessage[],
  onSendScript: (key: string, text: string) => void,
  onSendFollowup: (scriptKey: string, followupIndex: number, q: string) => void,
  onStartTour: () => void
): Chip[] {
  const asked = new Set(
    chat
      .filter((m) => m.role === 'sol' && 'scriptKey' in m)
      .map((m) => (m as { scriptKey: string }).scriptKey)
  )
  const chips: Chip[] = []
  for (const key of ['anomaly', 'alertq', 'hello']) {
    if (!asked.has(key)) {
      const q = SOL_SCRIPTS[key].q
      chips.push({ label: q, fn: () => onSendScript(key, q) })
    }
  }
  const lastScripted = [...chat]
    .reverse()
    .find((m): m is { role: 'sol'; scriptKey: string } => m.role === 'sol' && 'scriptKey' in m)
  if (lastScripted) {
    SOL_SCRIPTS[lastScripted.scriptKey]?.followups.forEach((f, i) => {
      if (!chat.some((m) => m.role === 'user' && m.text === f.q)) {
        chips.push({ label: f.q, fn: () => onSendFollowup(lastScripted.scriptKey, i, f.q) })
      }
    })
  }
  const shown = chips.slice(0, 2)
  shown.push({ label: 'Show me how to investigate the U4 alert', fn: onStartTour, tour: true })
  return shown
}

function InputBar({
  input,
  setInput,
  onSend,
  chat,
  onSendScript,
  onSendFollowup,
  onStartTour
}: {
  input: string
  setInput: (v: string) => void
  onSend: () => void
  chat: readonly ChatMessage[]
  onSendScript: (key: string, text: string) => void
  onSendFollowup: (scriptKey: string, followupIndex: number, q: string) => void
  onStartTour: () => void
}): React.JSX.Element {
  const chips = buildChips(chat, onSendScript, onSendFollowup, onStartTour)
  return (
    <div style={{ borderTop: '1px solid var(--bd)', background: 'var(--sur)' }}>
      <div style={{ maxWidth: 800, margin: '0 auto', padding: '12px 24px 16px' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          {chips.map((c) => (
            <span
              key={c.label}
              onClick={c.fn}
              style={{
                fontSize: 11.5,
                color: c.tour ? 'var(--acc)' : 'var(--tx)',
                background: 'var(--bg)',
                border: `1px solid ${c.tour ? 'color-mix(in srgb, var(--acc) 45%, transparent)' : 'var(--bd)'}`,
                borderRadius: 99,
                padding: '6px 12px',
                cursor: 'pointer',
                userSelect: 'none'
              }}
            >
              {c.tour && '✦ '}
              {c.label}
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSend()}
            placeholder="Ask about a signal, a change, a part…"
            style={{
              flex: 1,
              background: 'var(--bg)',
              color: 'var(--tx)',
              border: '1px solid var(--bd)',
              borderRadius: 3,
              padding: '10px 14px',
              fontSize: 13,
              fontFamily: 'var(--font-ui)',
              outline: 'none'
            }}
          />
          <Button kind="primary" onClick={onSend}>
            Send
          </Button>
        </div>
      </div>
    </div>
  )
}
