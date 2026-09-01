// UNWIRED since SOLUSDEV-152 removed the scripted chat composer: no production
// caller until SOLUSDEV-132/134 rebuilds the real SOL chat input around it.
// MO-04: the subtle pre-flight routing indicator. Deliberately quiet — small
// muted text the user can ignore (`standard · code · claude-sonnet-5`).
// Clicking opens a small popover to override tier/type FOR THIS CALL ONLY;
// non-viable options are dimmed with the endpoint's short reason rendered as a
// tiny muted line (a quiet fact, not an error). Never a banner, toast, or modal.
import { useState } from 'react'
import type { ClassifyOption, ClassifyPreview } from '../../lib/api/resources'
import type { OverrideState } from './useClassifyPreview'

interface ClassifyIndicatorProps {
  preview: ClassifyPreview | null
  override: OverrideState
  onOverride: (patch: Partial<OverrideState>) => void
  onReset: () => void
}

const MUTED: React.CSSProperties = { fontSize: 11, color: 'var(--mut)' }

function OptionRow({
  option,
  selected,
  onPick
}: {
  option: ClassifyOption
  selected: boolean
  onPick: () => void
}): React.JSX.Element {
  return (
    <div>
      <button
        type="button"
        disabled={!option.viable}
        onClick={onPick}
        style={{
          display: 'flex',
          gap: 8,
          width: '100%',
          alignItems: 'baseline',
          background: selected ? 'color-mix(in srgb, var(--acc) 12%, transparent)' : 'transparent',
          border: 'none',
          borderRadius: 3,
          padding: '4px 8px',
          cursor: option.viable ? 'pointer' : 'not-allowed',
          opacity: option.viable ? 1 : 0.45,
          color: 'var(--tx)',
          fontSize: 12,
          textAlign: 'left'
        }}
      >
        <span style={{ minWidth: 84 }}>{option.value}</span>
        <span style={{ ...MUTED, flex: 1 }}>{option.model}</span>
        <span style={MUTED}>{option.cost_tier}</span>
      </button>
      {!option.viable && option.reason && (
        <div style={{ ...MUTED, padding: '0 8px 4px' }}>{option.reason}</div>
      )}
    </div>
  )
}

export function ClassifyIndicator({
  preview,
  override,
  onOverride,
  onReset
}: ClassifyIndicatorProps): React.JSX.Element | null {
  const [open, setOpen] = useState(false)
  if (!preview) {
    // Always-visible (SOLUSDEV-233): the row is a stable part of the composer,
    // never popping in mid-typing. Without a classification (empty input, or
    // the debounce/endpoint hasn't answered) it shows an honest idle line in
    // the same spot — no invented tier/model, no layout shift.
    return (
      <div style={{ ...MUTED, marginTop: 6, textAlign: 'right', userSelect: 'none' }}>
        auto routing · sizes each message to the cheapest capable model
      </div>
    )
  }
  const overridden = override.complexity !== null || override.type !== null
  const tierLabel = `${preview.complexity}${override.complexity ? ' (you)' : ''}`
  const typeLabel = `${preview.type}${override.type ? ' (you)' : ''}`
  return (
    <div style={{ position: 'relative' }}>
      {open && (
        <div
          data-testid="classify-popover"
          style={{
            position: 'absolute',
            bottom: 24,
            right: 0,
            width: 320,
            background: 'var(--sur)',
            border: '1px solid var(--bd)',
            borderRadius: 4,
            padding: 10,
            boxShadow: '0 8px 24px rgba(0,0,0,.25)',
            zIndex: 20
          }}
        >
          <div style={{ ...MUTED, marginBottom: 4 }}>Tier — this message only</div>
          {preview.options.complexities.map((option) => (
            <OptionRow
              key={option.value}
              option={option}
              selected={option.value === preview.complexity}
              onPick={() => {
                onOverride({ complexity: option.value })
                setOpen(false)
              }}
            />
          ))}
          <div style={{ ...MUTED, margin: '8px 0 4px' }}>Type</div>
          {preview.options.types.map((option) => (
            <OptionRow
              key={option.value}
              option={option}
              selected={option.value === preview.type}
              onPick={() => {
                onOverride({ type: option.value })
                setOpen(false)
              }}
            />
          ))}
          {overridden && (
            <button
              type="button"
              onClick={() => {
                onReset()
                setOpen(false)
              }}
              style={{
                ...MUTED,
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                padding: '6px 8px 2px',
                textDecoration: 'underline'
              }}
            >
              reset to estimate
            </button>
          )}
        </div>
      )}
      <div
        data-testid="classify-indicator"
        role="button"
        tabIndex={0}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen((v) => !v)
          }
        }}
        aria-expanded={open}
        aria-label="Pre-flight routing — open to override for this message"
        title="Pre-flight routing — click to override for this message"
        style={{
          ...MUTED,
          marginTop: 6,
          textAlign: 'right',
          cursor: 'pointer',
          userSelect: 'none'
        }}
      >
        {tierLabel} · {typeLabel} · {preview.model.name}
        {!preview.viable && preview.reason ? ` — ${preview.reason}` : ''}
      </div>
    </div>
  )
}
