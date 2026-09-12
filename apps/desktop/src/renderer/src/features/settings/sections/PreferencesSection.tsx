// Preferences: SOL answer-mode (backend-persisted, ADR-016 universal setting),
// the desktop SOL window rows (action mode, sees-your-screen, hold-Ctrl
// gestures — main-owned ~/.solus/config.json over window.solus.sol, SOLUSDEV-252
// S3) and appearance (theme / accent / density — local, no backend field exists).
import { useCallback, useEffect, useState } from 'react'
import { Segmented } from '../../../components/ui/Segmented'
import { Switch } from '../../../components/ui/Switch'
import { getDesktopSolBridge, type SolBridge } from '../../../lib/desktopBridge'
import type { SolState } from '../../../../../main/sol-window/solWindow'
import {
  SOLUS_ACCENTS,
  SOLUS_THEMES,
  type AccentId,
  type ThemeId
} from '../../../theme/tokens.constants'
import { useSettingsStore, type SolMode } from '../../../store/settingsStore'
import { Section, Row, InlineError } from '../settingsUi'
import type { SettingsData } from '../useSettingsData'

const THEME_IDS = Object.keys(SOLUS_THEMES) as readonly ThemeId[]
const ACCENT_IDS = Object.keys(SOLUS_ACCENTS) as readonly AccentId[]
const SOL_MODES = ['Guide', 'Expert'] as const
const DENSITIES = ['compact', 'regular'] as const
const ACTION_MODES = ['Guide', 'Build'] as const
type ActionModeLabel = (typeof ACTION_MODES)[number]
const SEES_SCREEN_COPY =
  'When on, SOL can take a picture of your screen when you summon it or circle something, uses it for that one question, and then discards it. Nothing is saved unless you file it. Off means SOL never captures.'
const GESTURES_COPY =
  'Lets SOL notice a double-tap of Ctrl and a Ctrl-held circle anywhere on screen. Off keeps only the keyboard shortcuts.'
const SOL_LOAD_ERROR = "SOL settings didn't load from the desktop app — reopen Settings to retry."
const SOL_APPLY_ERROR = "The desktop app didn't accept that change."

function SolRow({ data }: { data: SettingsData }): React.JSX.Element {
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
      <Row label="Answer mode">
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

function Note({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5, padding: '6px 0 2px' }}>
      {children}
    </div>
  )
}

interface DesktopSol {
  state: SolState | null
  error: string | null
  /** Run a bridge call and adopt the state it returns (main is the source of truth). */
  apply: (call: (bridge: SolBridge) => Promise<SolState | null>) => void
}

/** window.solus.sol: getState on mount, then every sol:state push. */
function useDesktopSol(bridge: SolBridge | null): DesktopSol {
  const [state, setState] = useState<SolState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const adopt = useCallback((next: SolState | null, failure: string): void => {
    if (next) setState(next)
    setError(next ? null : failure)
  }, [])
  // A refused or rejected call reads the same to the user: the plain line below.
  const run = useCallback(
    (p: Promise<SolState | null>, failure: string): void => {
      void p.then(
        (s) => adopt(s, failure),
        () => adopt(null, failure)
      )
    },
    [adopt]
  )
  useEffect(() => {
    if (!bridge) return
    run(bridge.getState(), SOL_LOAD_ERROR)
    return bridge.onState((s) => adopt(s, SOL_LOAD_ERROR))
  }, [bridge, run, adopt])
  return {
    state,
    error,
    apply: (call) => {
      if (bridge) run(call(bridge), SOL_APPLY_ERROR)
    }
  }
}

/** The platform note when capture is degraded. The settings URL is plain text:
 *  ponytail: no IPC channel opens OS panes yet; add one when a user asks. */
function CaptureNote({ capture }: { capture: SolState['capture'] }): React.JSX.Element | null {
  if (capture.mode === 'available') return null
  return (
    <Note>
      {capture.message}
      {capture.settingsUrl ? ` Open: ${capture.settingsUrl}` : ''}
    </Note>
  )
}

function DesktopSolRows({ sol }: { sol: DesktopSol }): React.JSX.Element | null {
  const { state, apply } = sol
  if (!state) return null
  const mode: ActionModeLabel = state.actionMode === 'do' ? 'Build' : 'Guide'
  return (
    <>
      <Row label="Action mode">
        <Segmented
          size="sm"
          ariaLabel="Action mode"
          options={ACTION_MODES}
          value={mode}
          onChange={(next) => apply((b) => b.setMode(next === 'Build' ? 'do' : 'guide'))}
        />
      </Row>
      <Row label="SOL sees your screen">
        <Switch
          ariaLabel="SOL sees your screen"
          checked={state.screenIntelligence}
          onChange={(on) => apply((b) => b.setScreenIntelligence(on))}
        />
      </Row>
      <Note>{SEES_SCREEN_COPY}</Note>
      <CaptureNote capture={state.capture} />
      <Row label="Hold-Ctrl gestures">
        <Switch
          ariaLabel="Hold-Ctrl gestures"
          checked={state.hotkeysEnabled}
          onChange={(on) => apply((b) => b.setHotkeys(on))}
        />
      </Row>
      <Note>{GESTURES_COPY}</Note>
    </>
  )
}

/** The SOL window rows, or one line saying where they live. */
function DesktopSolSection(): React.JSX.Element {
  const [bridge] = useState(getDesktopSolBridge)
  const sol = useDesktopSol(bridge)
  if (!bridge) {
    return <Note>Action mode, screen capture and gestures: Available in the desktop app.</Note>
  }
  return (
    <>
      <DesktopSolRows sol={sol} />
      <InlineError message={sol.error} />
    </>
  )
}

function AppearanceRows(): React.JSX.Element {
  const theme = useSettingsStore((s) => s.theme)
  const accent = useSettingsStore((s) => s.accent)
  const density = useSettingsStore((s) => s.density)
  const setTheme = useSettingsStore((s) => s.setTheme)
  const setAccent = useSettingsStore((s) => s.setAccent)
  const setDensity = useSettingsStore((s) => s.setDensity)
  return (
    <>
      <Row label="Theme">
        <select
          aria-label="Theme"
          value={theme}
          onChange={(e) => setTheme(e.target.value as ThemeId)}
          style={{
            background: 'var(--bg)',
            color: 'var(--tx)',
            border: '1px solid var(--bd)',
            borderRadius: 3,
            padding: '6px 10px',
            fontSize: 12,
            fontFamily: 'var(--font-ui)',
            outline: 'none'
          }}
        >
          {THEME_IDS.map((k) => (
            <option key={k} value={k}>
              {SOLUS_THEMES[k].name}
            </option>
          ))}
        </select>
      </Row>
      <Row label="Accent">
        <div style={{ display: 'flex', gap: 8 }}>
          {ACCENT_IDS.map((k) => (
            <button
              key={k}
              type="button"
              aria-label={`Accent ${k}`}
              onClick={() => setAccent(k)}
              style={{
                width: 22,
                height: 22,
                borderRadius: 99,
                background: SOLUS_ACCENTS[k].c,
                cursor: 'pointer',
                border: accent === k ? '2px solid var(--tx)' : '2px solid transparent',
                boxSizing: 'border-box',
                padding: 0
              }}
            ></button>
          ))}
        </div>
      </Row>
      <Row label="Density">
        <Segmented
          size="sm"
          ariaLabel="Density"
          options={DENSITIES}
          value={density}
          onChange={setDensity}
        />
      </Row>
    </>
  )
}

export function PreferencesSection({ data }: { data: SettingsData }): React.JSX.Element {
  return (
    <>
      <Section
        title="SOL"
        sub="How the agent talks to you — applies everywhere SOL explains itself."
      >
        <SolRow data={data} />
        <DesktopSolSection />
      </Section>
      <Section
        title="Appearance"
        sub="Theme presets include editor schemes — set Solus to match your IDE."
      >
        <AppearanceRows />
      </Section>
    </>
  )
}
