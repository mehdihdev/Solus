// Onboarding step 4 — Access (SOLUSDEV-323, docs/wireflows/onboarding.md §4).
// Every switch starts off. "See your screen" is the real screenIntelligence
// setting (main is the source of truth, sol-window §D); its permission is asked
// at the row with main's own pane. The summon practice listens for a REAL
// double-Ctrl. Mouse-and-keyboard (ADR-041) joins when the drive bridge ships.
import { useMemo } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Icons } from '../../components/ui/icons.constants'
import { Switch } from '../../components/ui/Switch'
import { getDesktopSolBridge } from '../../lib/desktopBridge'
import { useDesktopSol, type DesktopSol } from '../settings/useDesktopSol'
import type { CaptureCapability } from '../../../../main/capture/screenCapture'
import type { SolState } from '../../../../main/sol-window/solWindow'
import { EyeGlyph, GlyphTile, KeyboardGlyph } from './onboardingIcons'
import { StepFooter } from './StepFooter'
import { useSummonPractice } from './useSummonPractice'

interface AccessStepProps {
  onNext: () => void
  onBack: () => void
}

export function AccessStep({ onNext, onBack }: AccessStepProps): React.JSX.Element {
  const bridge = useMemo(() => getDesktopSolBridge(), [])
  const sol = useDesktopSol(bridge)
  const { summons } = useSummonPractice(bridge)
  const screenOn = sol.state?.screenIntelligence ?? false
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        gap: 12,
        flex: 1
      }}
    >
      {sol.available ? (
        <>
          <ScreenRow sol={sol} />
          <SummonRow sol={sol} summons={summons} onShowMe={() => sol.apply((b) => b.open())} />
          {sol.error && (
            <p role="alert" style={{ margin: 0, fontSize: 12, color: 'var(--err)' }}>
              {sol.error}
            </p>
          )}
        </>
      ) : (
        <Card pad={0} className="ob-rise ob-d2">
          <div
            style={{ padding: '18px 20px', fontSize: 13, color: 'var(--mut)', lineHeight: 1.55 }}
          >
            Screen access and the Ctrl summon live in the Solus desktop app — you’ll find them there
            in Settings › SOL.
          </div>
        </Card>
      )}
      <StepFooter onBack={onBack} className="ob-rise ob-d5">
        <span style={{ fontSize: 12, color: 'var(--mut)' }}>
          Change any of this in Settings › SOL
        </span>
        <Button kind="primary" size="lg" onClick={onNext}>
          {screenOn ? 'Continue' : 'Not now — continue'} <Icons.arrowR size={14} />
        </Button>
      </StepFooter>
    </div>
  )
}

function Row({
  icon,
  title,
  on,
  delay,
  children,
  control
}: {
  icon: React.ReactNode
  title: string
  on: boolean
  delay: string
  children: React.ReactNode
  control?: React.ReactNode
}): React.JSX.Element {
  return (
    <Card pad={0} className={`ob-cap ob-rise ${delay}`} data-on={on}>
      <div style={{ padding: '18px 20px', display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        <GlyphTile>{icon}</GlyphTile>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
          {children}
        </div>
        {control}
      </div>
    </Card>
  )
}

const BODY = { fontSize: 13, color: 'var(--mut)', marginTop: 4, lineHeight: 1.55 } as const
const NOTE = {
  marginTop: 12,
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  flexWrap: 'wrap',
  fontSize: 12,
  color: 'var(--mut)'
} as const

function ScreenRow({ sol }: { sol: DesktopSol }): React.JSX.Element {
  const on = sol.state?.screenIntelligence ?? false
  const capture = sol.state?.capture
  return (
    <Row
      icon={<EyeGlyph />}
      title="See your screen"
      on={on}
      delay="ob-d2"
      control={
        <Switch
          checked={on}
          ariaLabel="See your screen"
          disabled={!sol.state}
          onChange={(next) => sol.apply((b) => b.setScreenIntelligence(next))}
        />
      }
    >
      <div style={BODY}>
        When you summon me, I can take one picture of your screen for that question, then discard
        it. Nothing is saved unless you file it.
      </div>
      {on && capture && <CaptureNote sol={sol} capture={capture} />}
    </Row>
  )
}

function CaptureNote({
  sol,
  capture
}: {
  sol: DesktopSol
  capture: CaptureCapability
}): React.JSX.Element {
  if (capture.mode === 'available')
    return (
      <div className="ob-rise" style={{ ...NOTE, color: 'var(--ok)' }}>
        <Icons.check size={13} /> Screen access granted
      </div>
    )
  return (
    <div className="ob-rise" style={NOTE}>
      <span>{capture.message}</span>
      {capture.mode === 'needs-permission' && (
        <Button kind="ghost" size="sm" onClick={sol.openCaptureSettings}>
          Open System Settings
        </Button>
      )}
      <Button kind="bare" size="sm" onClick={sol.recheck}>
        Recheck
      </Button>
    </div>
  )
}

/** Why the double-tap may not work right now, or null when it should. */
function hotkeyNote(state: SolState | null): string | null {
  if (!state) return null
  if (!state.hotkeysEnabled)
    return 'SOL’s hotkeys are off — turn them on in Settings › SOL to summon me.'
  const hook = state.hotkeys?.hook
  return hook && hook.status !== 'available' ? (state.hotkeys?.summary ?? null) : null
}

function SummonRow({
  sol,
  summons,
  onShowMe
}: {
  sol: DesktopSol
  summons: number
  onShowMe: () => void
}): React.JSX.Element {
  const practiced = summons > 0
  const note = hotkeyNote(sol.state)
  return (
    <Row icon={<KeyboardGlyph />} title="Summon me from anywhere" on={practiced} delay="ob-d3">
      <div style={BODY}>
        {practiced
          ? 'That’s it — I’m one double-tap away, in any app.'
          : note
            ? 'Double-tap Ctrl in any app.'
            : 'Double-tap Ctrl in any app. Try it now.'}
      </div>
      {note && <div style={NOTE}>{note}</div>}
      <div
        style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}
      >
        {/* The practice needs a working hook; keyed by summon count so each real summon replays the press. */}
        {!note && (
          <span key={summons} style={{ display: 'inline-flex', gap: 8, marginRight: 8 }}>
            <span className="ob-key" data-pressed={practiced}>
              ctrl
            </span>
            <span className="ob-key" data-pressed={practiced}>
              ctrl
            </span>
          </span>
        )}
        <Button kind="ghost" size="sm" onClick={onShowMe}>
          Show me
        </Button>
      </div>
    </Row>
  )
}
