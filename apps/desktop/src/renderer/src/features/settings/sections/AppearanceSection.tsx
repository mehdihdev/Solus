// Settings › Appearance (SOLUSDEV-318): theme tiles that preview each preset
// with its own tokens, and the accent swatches. Local only — no backend field.
// Density was removed: nothing ever read it.
import {
  SOLUS_ACCENTS,
  SOLUS_THEMES,
  type AccentId,
  type ThemeId
} from '../../../theme/tokens.constants'
import { useSettingsStore } from '../../../store/settingsStore'
import { Section, Row } from '../settingsUi'

const THEME_IDS = Object.keys(SOLUS_THEMES) as readonly ThemeId[]
const ACCENT_IDS = Object.keys(SOLUS_ACCENTS) as readonly AccentId[]

function ThemeTile({
  id,
  selected,
  onPick
}: {
  id: ThemeId
  selected: boolean
  onPick: (id: ThemeId) => void
}): React.JSX.Element {
  const t = SOLUS_THEMES[id]
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={() => onPick(id)}
      className="interactive settings-tile"
      style={{
        display: 'block',
        padding: 0,
        textAlign: 'left',
        borderRadius: 4,
        overflow: 'hidden',
        background: 'var(--bg)',
        color: 'var(--tx)',
        border: selected ? '2px solid var(--acc)' : '1px solid var(--bd)',
        fontFamily: 'var(--font-ui)'
      }}
    >
      {/* A swatch drawn in the preset's own tokens — data, not a hardcoded colour. */}
      <span
        aria-hidden="true"
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          height: 46,
          padding: 8,
          boxSizing: 'border-box',
          background: t.bg
        }}
      >
        <span style={{ height: 8, width: '70%', borderRadius: 2, background: t.sur2 }} />
        <span
          style={{ height: 4, width: '45%', borderRadius: 2, background: t.tx, opacity: 0.8 }}
        />
      </span>
      <span style={{ display: 'block', padding: '7px 8px', fontSize: 11.5 }}>{t.name}</span>
    </button>
  )
}

export function AppearanceSection(): React.JSX.Element {
  const theme = useSettingsStore((s) => s.theme)
  const accent = useSettingsStore((s) => s.accent)
  const setTheme = useSettingsStore((s) => s.setTheme)
  const setAccent = useSettingsStore((s) => s.setAccent)
  return (
    <Section
      id="appearance"
      title="Appearance"
      sub="Editor presets let you match Solus to your IDE."
    >
      <div
        role="group"
        aria-label="Theme"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(124px, 1fr))',
          gap: 10,
          paddingBottom: 12,
          borderBottom: '1px solid var(--bd)'
        }}
      >
        {THEME_IDS.map((id) => (
          <ThemeTile key={id} id={id} selected={theme === id} onPick={setTheme} />
        ))}
      </div>
      <Row label="Accent">
        <div style={{ display: 'flex', gap: 8 }}>
          {ACCENT_IDS.map((k) => (
            <button
              key={k}
              type="button"
              aria-label={`Accent ${k}`}
              aria-pressed={accent === k}
              onClick={() => setAccent(k)}
              className="settings-tile"
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
    </Section>
  )
}
