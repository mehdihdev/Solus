// Segmented Monthly | Yearly control (role=group, aria-pressed buttons).
import type { BillingInterval } from '../../lib/api/resources.billing'
import { intervalLabel } from '../settings/billingFormat'

export function IntervalToggle({
  value,
  onChange
}: {
  value: BillingInterval
  onChange: (v: BillingInterval) => void
}): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 6 }} role="group" aria-label="Billing interval">
      {(['month', 'year'] as const).map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          aria-pressed={value === opt}
          style={{
            fontSize: 11,
            padding: '3px 10px',
            borderRadius: 6,
            border: `1px solid ${value === opt ? 'var(--acc)' : 'var(--bd)'}`,
            background: value === opt ? 'var(--acc)' : 'transparent',
            color: value === opt ? 'var(--acc-ink)' : 'var(--mut)',
            cursor: 'pointer'
          }}
        >
          {intervalLabel(opt)}
        </button>
      ))}
    </div>
  )
}
