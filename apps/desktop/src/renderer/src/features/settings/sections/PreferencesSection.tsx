// Preferences: SOL answer-mode (backend-persisted, ADR-016 universal setting)
// and appearance (theme / accent / density — local, no backend field exists).
import { Segmented } from '../../../components/ui/Segmented'
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
