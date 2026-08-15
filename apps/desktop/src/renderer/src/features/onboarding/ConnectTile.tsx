// Connect tile for the real connectors (SOLUSDEV-103/-100, de-simulated in
// SOLUSDEV-152): a busy state carries the live `label` from the flow, a picker
// over whatever the source can track (`selectable`, one or many per the
// connector's own `selectionMode`), the connector's `configFields` when it is
// configured by plain values instead, or an `error` phase; the done state shows
// the real `result` string. No copy here is ever fabricated, and nothing here
// knows what a selectable item IS — so a new connector needs no change.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'
import type { IntegrationAccessModes, SelectableItem } from '../../lib/api/resources'
import { SelectionPicker, PICKER_FIELD_STYLE } from './SelectionPicker'
import type { Integration } from './integrations.constants'
import type { ConnectionState } from './onboardingStore'

interface ConnectTileProps {
  integration: Integration
  state?: ConnectionState
  onConnect: () => void
  /** Resolve the picker (null cancels). */
  onSelect?: (items: SelectableItem[] | null) => void
  /** Resolve the connector-details form (every other OAuth provider). */
  onSubmitConfig?: (values: Record<string, string>) => void
  /** Resolve the connect-time grant choice (null cancels). */
  onChooseAccess?: (mode: string | null) => void
  /** Retry after an error. */
  onRetry?: () => void
}

function TileIndicator({ state }: { state?: ConnectionState }): React.JSX.Element {
  if (!state)
    return <span style={{ color: 'var(--acc)', fontSize: 12, fontWeight: 500 }}>Connect</span>
  if (state.phase === 'busy') return <Spinner />
  if (state.phase === 'error')
    return <span style={{ color: 'var(--err)', fontSize: 12, fontWeight: 500 }}>Retry</span>
  return (
    <span style={{ color: 'var(--ok)' }}>
      <Icons.check size={15} />
    </span>
  )
}

const MONO = { fontFamily: 'var(--font-mono)', fontSize: 10.5 } as const

function TileFooter({ state }: { state?: ConnectionState }): React.JSX.Element {
  if (!state) return <span style={{ fontSize: 11, color: 'var(--mut)' }}>Not connected</span>
  if (state.phase === 'busy') {
    return <span style={{ ...MONO, color: 'var(--acc)' }}>{state.label ?? 'Connecting…'}</span>
  }
  if (state.phase === 'error') {
    return <span style={{ ...MONO, color: 'var(--err)' }}>{state.error}</span>
  }
  return <span style={{ ...MONO, color: 'var(--ok)' }}>{state.result ?? 'Connected'}</span>
}

/** `document_id` → `Document id`. The registry names the fields; we only make
 * them readable, so a connector we have never seen still gets sane labels. */
function fieldLabel(field: string): string {
  const words = field.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * The generic connector-details form: one input per live `config_field`. Used by
 * every OAuth provider that has nothing to pick.
 */
function ConfigForm({
  fields,
  onSubmitConfig
}: {
  fields: readonly string[]
  onSubmitConfig?: (values: Record<string, string>) => void
}): React.JSX.Element {
  const [values, setValues] = useState<Record<string, string>>({})
  const complete = fields.every((field) => values[field]?.trim())

  return (
    <div onClick={(e) => e.stopPropagation()} style={{ marginTop: 8, display: 'grid', gap: 6 }}>
      {fields.map((field) => (
        <input
          key={field}
          aria-label={fieldLabel(field)}
          placeholder={fieldLabel(field)}
          value={values[field] ?? ''}
          onChange={(e) => setValues((prev) => ({ ...prev, [field]: e.target.value }))}
          style={PICKER_FIELD_STYLE}
        />
      ))}
      <Button
        kind="primary"
        size="sm"
        disabled={!complete}
        onClick={() => onSubmitConfig?.(values)}
      >
        Connect
      </Button>
    </div>
  )
}

/**
 * The connect-time grant choice. Generic over whatever the connector declares:
 * it renders labels and descriptions from the registry and knows nothing about
 * Onshape or scopes. The DESCRIPTION is shown, not just the label — "Read and
 * edit" alone does not tell a user their models can be changed.
 */
function AccessPicker({
  accessModes,
  onChooseAccess
}: {
  accessModes: IntegrationAccessModes
  onChooseAccess?: (mode: string | null) => void
}): React.JSX.Element {
  // Default to the connector's own default, never to the widest grant.
  const [chosen, setChosen] = useState(accessModes.default)

  return (
    <div onClick={(e) => e.stopPropagation()} style={{ marginTop: 8, display: 'grid', gap: 6 }}>
      {accessModes.modes.map((mode) => (
        <label
          key={mode.id}
          style={{ display: 'flex', gap: 8, alignItems: 'flex-start', cursor: 'pointer' }}
        >
          <input
            type="radio"
            name="solus-access-mode"
            aria-label={mode.label}
            checked={chosen === mode.id}
            onChange={() => setChosen(mode.id)}
            style={{ marginTop: 3 }}
          />
          <span>
            <span style={{ fontSize: 12, fontWeight: 600 }}>{mode.label}</span>
            <span style={{ display: 'block', fontSize: 11, color: 'var(--mut)' }}>
              {mode.description}
            </span>
          </span>
        </label>
      ))}
      <Button kind="primary" size="sm" onClick={() => onChooseAccess?.(chosen)}>
        Continue
      </Button>
    </div>
  )
}

function borderFor(state?: ConnectionState): string {
  if (state?.phase === 'done') return 'color-mix(in srgb, var(--ok) 45%, var(--bd))'
  if (state?.phase === 'error') return 'color-mix(in srgb, var(--err) 45%, var(--bd))'
  if (state?.phase === 'busy') return 'var(--acc)'
  return 'var(--bd)'
}

/** Whatever input the live flow is waiting on: a repo picker, the generic
 * connector-details form, or nothing. */
function TileInput({
  state,
  onSelect,
  onSubmitConfig,
  onChooseAccess
}: Pick<
  ConnectTileProps,
  'state' | 'onSelect' | 'onSubmitConfig' | 'onChooseAccess'
>): React.JSX.Element | null {
  if (state?.phase !== 'busy') return null
  if (state.accessModes) {
    return <AccessPicker accessModes={state.accessModes} onChooseAccess={onChooseAccess} />
  }
  if (state.selectable && state.selectable.length > 0) {
    return (
      <SelectionPicker items={state.selectable} mode={state.selectionMode} onSelect={onSelect} />
    )
  }
  if (state.configFields && state.configFields.length > 0) {
    return <ConfigForm fields={state.configFields} onSubmitConfig={onSubmitConfig} />
  }
  return null
}

export function ConnectTile({
  integration,
  state,
  onConnect,
  onSelect,
  onSubmitConfig,
  onChooseAccess,
  onRetry
}: ConnectTileProps): React.JSX.Element {
  const clickable = !state || state.phase === 'error'
  const handleClick = !state ? onConnect : state.phase === 'error' ? onRetry : undefined
  return (
    <Card
      pad={0}
      onClick={clickable ? handleClick : undefined}
      style={{
        cursor: clickable ? 'pointer' : 'default',
        overflow: 'hidden',
        borderColor: borderFor(state),
        transition: 'border-color 0.2s'
      }}
    >
      <div style={{ padding: '16px 16px 14px', display: 'flex', gap: 12, alignItems: 'center' }}>
        <span
          style={{
            width: 38,
            height: 38,
            borderRadius: 3,
            background: 'var(--sur2)',
            border: '1px solid var(--bd)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            fontWeight: 500,
            color: 'var(--tx)',
            flexShrink: 0
          }}
        >
          {integration.mark}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{integration.name}</div>
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>{integration.kind}</div>
        </div>
        <TileIndicator state={state} />
      </div>
      <div
        style={{
          borderTop: '1px solid var(--bd)',
          padding: '9px 16px',
          minHeight: 16,
          background: 'var(--bg)'
        }}
      >
        <TileFooter state={state} />
        <TileInput
          state={state}
          onSelect={onSelect}
          onSubmitConfig={onSubmitConfig}
          onChooseAccess={onChooseAccess}
        />
      </div>
    </Card>
  )
}
