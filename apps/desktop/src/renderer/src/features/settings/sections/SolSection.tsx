// Settings › SOL (SOLUSDEV-318, from the SOLUSDEV-252 Preferences rows): the
// ADR-016 answer mode (backend-persisted) and the desktop SOL window rows —
// action mode, sees-your-screen, hold-Ctrl gestures — over window.solus.sol.
// A blocked capture is tagged here; the fix itself is the Needs-attention card.
import { Segmented } from '../../../components/ui/Segmented'
import { Switch } from '../../../components/ui/Switch'
import { useSettingsStore, type SolMode } from '../../../store/settingsStore'
import { Section, Row, InlineError, StatusTag } from '../settingsUi'
import type { SettingsData } from '../useSettingsData'
import type { DesktopSol } from '../useDesktopSol'

const SOL_MODES = ['Guide', 'Expert'] as const
const ACTION_MODES = ['Guide', 'Build'] as const
type ActionModeLabel = (typeof ACTION_MODES)[number]

const ANSWER_COPY =
  'Guide explains its reasoning and links fundamentals. Expert leads with the answer.'
const ACTION_COPY =
  'Guide walks you through each step. Build lets SOL make changes after you confirm them.'
// Wireflow sol-window §D, verbatim.
const SEES_SCREEN_COPY =
  'When on, SOL can take a picture of your screen when you summon it or circle something, uses it for that one question, and then discards it. Nothing is saved unless you file it. Off means SOL never captures.'
const GESTURES_COPY =
  'Lets SOL notice a double-tap of Ctrl and a Ctrl-held circle anywhere on screen. Off keeps only the keyboard shortcuts.'

function AnswerModeRow({ data }: { data: SettingsData }): React.JSX.Element {
  const solMode = useSettingsStore((s) => s.solMode)
  const setStoreSolMode = useSettingsStore((s) => s.setSolMode)
  // Online: persist through the backend (reconciled app-wide). Offline (dev
  // bypass): keep it a local-only preference so the toggle still works.
  const onChange =
    data.status === 'ready'
      ? (mode: SolMode) => void data.actions.setSolMode(mode)
      : (mode: SolMode) => setStoreSolMode(mode)
  return (
    <>
      <Row label="Answer mode" description={ANSWER_COPY}>
        <Segmented
          size="sm"
          ariaLabel="Answer mode"
          options={SOL_MODES}
          value={solMode}
          onChange={onChange}
        />
      </Row>
      <InlineError message={data.errors.sol_mode} />
    </>
  )
}

function SeesScreenLabel({
  blocked,
  onFix
}: {
  blocked: boolean
  onFix: () => void
}): React.JSX.Element {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      SOL sees your screen
      {blocked && (
        <span
          className="settings-row-in"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
        >
          <StatusTag tone="warn">Permission needed</StatusTag>
          <button type="button" onClick={onFix} className="interactive" style={FIX_LINK}>
            How to fix
          </button>
        </span>
      )}
    </span>
  )
}

const FIX_LINK: React.CSSProperties = {
  background: 'none',
  border: 'none',
  padding: 0,
  color: 'var(--acc)',
  fontSize: 11.5,
  fontFamily: 'var(--font-ui)'
}

function DesktopRows({
  sol,
  onFix
}: {
  sol: DesktopSol
  onFix: () => void
}): React.JSX.Element | null {
  const { state, apply } = sol
  if (!state) return null
  const mode: ActionModeLabel = state.actionMode === 'do' ? 'Build' : 'Guide'
  const blocked = state.screenIntelligence && state.capture.mode !== 'available'
  return (
    <>
      <Row label="Action mode" description={ACTION_COPY}>
        <Segmented
          size="sm"
          ariaLabel="Action mode"
          options={ACTION_MODES}
          value={mode}
          onChange={(next) => apply((b) => b.setMode(next === 'Build' ? 'do' : 'guide'))}
        />
      </Row>
      <Row
        label={<SeesScreenLabel blocked={blocked} onFix={onFix} />}
        description={SEES_SCREEN_COPY}
      >
        <Switch
          ariaLabel="SOL sees your screen"
          checked={state.screenIntelligence}
          onChange={(on) => apply((b) => b.setScreenIntelligence(on))}
        />
      </Row>
      <Row label="Hold-Ctrl gestures" description={GESTURES_COPY}>
        <Switch
          ariaLabel="Hold-Ctrl gestures"
          checked={state.hotkeysEnabled}
          onChange={(on) => apply((b) => b.setHotkeys(on))}
        />
      </Row>
    </>
  )
}

export interface SolSectionProps {
  data: SettingsData
  sol: DesktopSol
  /** Scroll to the capture fix in Needs attention. */
  onFixCapture: () => void
}

export function SolSection({ data, sol, onFixCapture }: SolSectionProps): React.JSX.Element {
  return (
    <Section
      id="sol"
      title="SOL"
      sub="How the agent talks to you and what it may do — applies everywhere SOL explains itself."
    >
      <AnswerModeRow data={data} />
      {sol.available ? (
        <>
          <DesktopRows sol={sol} onFix={onFixCapture} />
          <InlineError message={sol.error} />
        </>
      ) : (
        <div style={{ fontSize: 11.5, color: 'var(--mut)', padding: '10px 0 2px' }}>
          Action mode, screen capture and gestures: Available in the desktop app.
        </div>
      )}
    </Section>
  )
}
