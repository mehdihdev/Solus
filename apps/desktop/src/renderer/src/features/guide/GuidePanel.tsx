// SOLUS-TU-09 — the Guide side-panel: the first genuinely usable Guide.
//
// SOL walks the user through a real task via a compact side panel, sourced
// entirely from KB ladder steps 1-2 (zero overlay). Every step carries
// confidence; a step the KB does not cover degrades to its authored narration
// with an honest "not in the knowledge base yet" note (never a fabricated
// pointer); a low-confidence step renders tentative. Narration follows the
// per-user SOL mode (ADR-016). This is the graceful-degradation target for
// SOLX-03 — the overlay falls back here when KB confidence is low.
import { useState, type CSSProperties } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { useSettingsStore } from '../../store/settingsStore'
import { sendFeedback, type GuideStepView } from './guideApi'
import { useGuide } from './useGuide'
import { useNativeGuideHandoff } from './useNativeGuideHandoff'

const PANEL: CSSProperties = {
  width: 340,
  flexShrink: 0,
  borderLeft: '1px solid var(--bd)',
  background: 'var(--sur)',
  overflowY: 'auto',
  padding: 16,
  display: 'flex',
  flexDirection: 'column',
  gap: 12
}

interface GuidePanelProps {
  guideId: string | null
  tool: string
  version: string
  presentation?: 'browser' | 'native' | 'scriptable'
}

export function GuidePanel({
  guideId,
  version,
  presentation = 'browser'
}: GuidePanelProps): React.JSX.Element {
  const solMode = useSettingsStore((s) => s.solMode)
  const { status, guide } = useGuide(guideId, version)
  const overlay = useNativeGuideHandoff(guide, solMode === 'Expert')

  return (
    <aside style={PANEL} aria-label="Guide">
      {status === 'loading' && <Spinner />}
      {status === 'error' && (
        <p style={{ color: 'var(--mut)', fontSize: 13 }}>
          Couldn&apos;t load this guide. It may be unavailable — try again later.
        </p>
      )}
      {status === 'idle' && (
        <p style={{ color: 'var(--mut)', fontSize: 13 }}>Pick a task to get a walkthrough.</p>
      )}
      {status === 'ready' && guide && (
        <>
          {presentation === 'native' && (
            <>
              <Button onClick={() => void overlay.start()}>Show native overlay</Button>
              {overlay.message && <p role="status">{overlay.message}</p>}
            </>
          )}
          <header style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <h2 style={{ margin: 0, fontSize: 15, color: 'var(--tx)' }}>{guide.title}</h2>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--mut)', lineHeight: 1.4 }}>
              {guide.summary}
            </p>
          </header>
          <ol
            style={{
              margin: 0,
              padding: 0,
              listStyle: 'none',
              display: 'flex',
              flexDirection: 'column',
              gap: 8
            }}
          >
            {guide.steps.map((step) => (
              <StepRow
                key={step.step_number}
                step={step}
                expert={solMode === 'Expert'}
                scriptable={presentation === 'scriptable'}
              />
            ))}
          </ol>
        </>
      )}
    </aside>
  )
}

function StepRow({
  step,
  expert,
  scriptable
}: {
  step: GuideStepView
  expert: boolean
  scriptable: boolean
}): React.JSX.Element {
  const note = expert ? step.note_expert : step.note_guide
  return (
    <li>
      <Card pad={12} style={{ opacity: step.available ? 1 : 0.85 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
          <span style={{ fontSize: 12, color: 'var(--mut)', fontVariantNumeric: 'tabular-nums' }}>
            {step.step_number}.
          </span>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {step.available && step.label ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <strong style={{ fontSize: 13, color: 'var(--tx)' }}>{step.label}</strong>
                <ConfidenceBadge step={step} />
              </div>
            ) : (
              <span style={{ fontSize: 12, color: 'var(--warn)' }}>
                This step isn&apos;t in the knowledge base yet. Not sure where that is in this
                version.
              </span>
            )}
            <span style={{ fontSize: 12, color: 'var(--tx)', lineHeight: 1.4 }}>{note}</span>
            {scriptable && (
              <Button
                kind="bare"
                size="sm"
                onClick={() => void navigator.clipboard?.writeText(note).catch(() => undefined)}
              >
                Copy instruction
              </Button>
            )}
            {step.available && <Invocation step={step} />}
            {step.available && step.entry_id && <StepFeedback entryId={step.entry_id} />}
          </div>
        </div>
      </Card>
    </li>
  )
}

// TU-08: confirm/reject a guidance step. A reject pulls the SHARED entry's
// confidence down for every user, so it reads as a considered correction, not
// a throwaway. One vote per mount; the deterministic recompute lives server-side.
function StepFeedback({ entryId }: { entryId: string }): React.JSX.Element {
  const [sent, setSent] = useState<'confirm' | 'reject' | null>(null)

  if (sent) {
    return (
      <span style={{ fontSize: 11, color: 'var(--mut)' }}>
        {sent === 'confirm' ? 'Thanks — marked helpful.' : 'Thanks — flagged for review.'}
      </span>
    )
  }
  const vote = (verdict: 'confirm' | 'reject'): void => {
    setSent(verdict)
    // Fire-and-forget; the shared confidence updates server-side. A failed
    // request simply means the vote didn't land — no fabricated success state.
    void sendFeedback(entryId, verdict).catch(() => setSent(null))
  }
  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 2 }}>
      <Button kind="bare" size="sm" onClick={() => vote('confirm')}>
        Helpful
      </Button>
      <Button kind="bare" size="sm" onClick={() => vote('reject')}>
        Wrong
      </Button>
    </div>
  )
}

function Invocation({ step }: { step: GuideStepView }): React.JSX.Element | null {
  if (step.shortcut) {
    return (
      <span style={{ fontSize: 11, color: 'var(--mut)' }}>
        Shortcut: <kbd className="font-mono">{step.shortcut}</kbd>
      </span>
    )
  }
  if (step.menu_path && step.menu_path.length > 0) {
    return (
      <span style={{ fontSize: 11, color: 'var(--mut)' }}>Menu: {step.menu_path.join(' › ')}</span>
    )
  }
  return null
}

function ConfidenceBadge({ step }: { step: GuideStepView }): React.JSX.Element {
  // Net-new (no shared badge primitive exists, and components/ui is @shared).
  // Tentative is the load-bearing state — an honest "not sure" over a confident
  // wrong instruction, the property that makes Guide trustworthy.
  if (step.tentative) {
    return (
      <span
        style={{
          fontSize: 10,
          padding: '1px 6px',
          borderRadius: 3,
          background: 'var(--sur2)',
          color: 'var(--warn)',
          border: '1px solid var(--warn)'
        }}
      >
        tentative
      </span>
    )
  }
  const pct = step.confidence == null ? null : Math.round(step.confidence * 100)
  return (
    <span style={{ fontSize: 10, color: 'var(--mut)' }}>
      {pct == null ? '' : `${pct}% confident`}
    </span>
  )
}
