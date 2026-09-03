// SOLUSDEV-235 — detail › Settings: per-project enablement and run frequency.
// Team-wide defaults are an owner setting that does not exist yet; the footnote
// says so rather than offering a control that does nothing.
import { Switch } from '../../../components/ui/Switch'
import { RUN_FREQUENCY_OPTIONS } from '../extensionLogic'
import type { ExtensionView, RunFrequency } from '../extension.types'
import type { ExtensionActions } from '../useExtensions'

const SELECT_STYLE: React.CSSProperties = {
  background: 'var(--bg)',
  color: 'var(--tx)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  padding: '6px 10px',
  fontSize: 12,
  fontFamily: 'var(--font-ui)',
  outline: 'none'
}

export function SettingsTab({
  view,
  actions
}: {
  view: ExtensionView
  actions: ExtensionActions
}): React.JSX.Element {
  const { manifest, state } = view
  const locked = !state.installed
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
          onChange={(on) => actions.setEnabled(manifest.id, on)}
        />
      </SettingRow>
      <SettingRow title="Run frequency" sub="When this extension re-evaluates.">
        <select
          aria-label="Run frequency"
          value={state.runFrequency}
          disabled={locked}
          onChange={(e) => actions.setRunFrequency(manifest.id, e.target.value as RunFrequency)}
          style={{ ...SELECT_STYLE, opacity: locked ? 0.45 : 1 }}
        >
          {RUN_FREQUENCY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </SettingRow>
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
