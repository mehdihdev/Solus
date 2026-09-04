// SOLUSDEV-235 — detail › Settings: per-project enablement, then the fields the
// PINNED manifest declares, rendered by type and saved (debounced, as one
// object) through the install PATCH. Team-wide defaults are an owner setting;
// the footnote says so rather than offering a control that does nothing.
import { useEffect, useRef, useState } from 'react'
import { Switch } from '../../../components/ui/Switch'
import { settingValuesOf } from '../extensionLogic'
import type { ExtensionSettings, ExtensionView } from '../extension.types'
import type { ExtensionActions } from '../extensionActions'
import { SettingControl } from './SettingControl'

/** Typing pauses this long before the settings object is PUT. */
export const SETTINGS_SAVE_DEBOUNCE_MS = 400

interface SettingsDraft {
  readonly values: ExtensionSettings
  readonly error: string | null
  readonly change: (key: string, value: ExtensionSettings[string]) => void
}

/** Local edits over the server values, saved as ONE object once typing pauses. */
function useSettingsDraft(view: ExtensionView, actions: ExtensionActions): SettingsDraft {
  const { manifest, state, catalog } = view
  const stored = manifest ? settingValuesOf(manifest, state.settings) : {}
  const [draft, setDraft] = useState<ExtensionSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [seen, setSeen] = useState(state.settings)
  const timer = useRef<number | undefined>(undefined)

  // A fresh server row supersedes the local draft (ours after a save, or a
  // teammate's) — adjusted during render, the React-sanctioned way.
  if (seen !== state.settings) {
    setSeen(state.settings)
    setDraft(null)
  }
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const values = draft ?? stored
  const change = (key: string, value: ExtensionSettings[string]): void => {
    const next = { ...values, [key]: value }
    setDraft(next)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      void actions.setSettings(catalog.slug, next).then((result) => {
        setError(result.ok ? null : result.message)
      })
    }, SETTINGS_SAVE_DEBOUNCE_MS)
  }
  return { values, error, change }
}

export function SettingsTab({
  view,
  actions
}: {
  view: ExtensionView
  actions: ExtensionActions
}): React.JSX.Element {
  const { manifest, state, catalog } = view
  const locked = !state.installed
  const fields = manifest?.settings.fields ?? []
  const { values, error, change } = useSettingsDraft(view, actions)

  return (
    <div style={{ maxWidth: 640, paddingTop: 12 }}>
      <SettingRow
        title="Enable in this project"
        sub="Turn this extension’s widgets and checks on or off here."
      >
        <Switch
          checked={state.installed && state.enabled}
          disabled={locked}
          ariaLabel="Enable in this project"
          onChange={(on) => void actions.setEnabled(catalog.slug, on)}
        />
      </SettingRow>
      {fields.map((field) => (
        <SettingRow key={field.key} title={field.label} sub={field.key}>
          <SettingControl
            field={field}
            value={values[field.key]}
            disabled={locked}
            onChange={(value) => change(field.key, value)}
          />
        </SettingRow>
      ))}
      {manifest && fields.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--mut)', padding: '14px 0' }}>
          This extension has no settings of its own.
        </div>
      )}
      {error && (
        <div role="alert" style={{ fontSize: 12, color: 'var(--warn)', marginTop: 12 }}>
          {error}
        </div>
      )}
      <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 14, lineHeight: 1.5 }}>
        {locked
          ? 'Install this extension to change its settings.'
          : 'Settings apply to this project only. Team defaults are set by an owner.'}
      </div>
    </div>
  )
}

function SettingRow({
  title,
  sub,
  children
}: {
  title: string
  sub: string
  children: React.ReactNode
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 16,
        padding: '14px 0',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <div>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--mut)', marginTop: 2 }}>{sub}</div>
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  )
}
