// Settings › Plan & usage (SOLUSDEV-318, replaces the SOLUSDEV-86 Billing
// summary): the plan, its trial or status, the credit balance and the plan's
// limits — then one way out to the Billing page, which owns card, invoices,
// credit packs and plan changes. Read-only by design.
import { Button } from '../../../components/ui/Button'
import { Section, StatusTag } from '../settingsUi'
import { formatDate, planLabel, statusLabel, trialEndsLabel, trialState } from '../billingFormat'
import type { Subscription } from '../../../lib/api/resources'
import type { CreditsView } from '../useCredits'

const LIMITS: readonly (readonly [string, string])[] = [
  ['max_projects', 'Projects'],
  ['max_integrations', 'Integrations'],
  ['max_teams', 'Teams']
]

function limitText(value: number | null): string {
  return value === null ? 'Unlimited' : `Up to ${value.toLocaleString('en-US')}`
}

function creditsText(credits: CreditsView): string {
  if (credits.unlimited) return 'Unlimited'
  return credits.balance === null ? '—' : credits.balance.toLocaleString('en-US')
}

function Tile({ label, value }: { label: string; value: string }): React.JSX.Element {
  return (
    <div
      style={{
        background: 'var(--bg)',
        border: '1px solid var(--bd)',
        borderRadius: 4,
        padding: '10px 12px'
      }}
    >
      <div style={{ fontSize: 11.5, color: 'var(--mut)' }}>{label}</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, marginTop: 4 }}>{value}</div>
    </div>
  )
}

function statusLine(sub: Subscription, now?: number): string {
  const trial = trialState(sub, now)
  if (trial.kind === 'active') return `Trial ends ${trialEndsLabel(trial.days)}`
  if (trial.kind === 'ended') return `Trial ended ${formatDate(trial.endsAt)}`
  return statusLabel(sub.status)
}

export interface PlanSectionProps {
  subscription: Subscription | null
  credits: CreditsView
  onOpenBilling: () => void
  now?: number
}

export function PlanSection({
  subscription: sub,
  credits,
  onOpenBilling,
  now
}: PlanSectionProps): React.JSX.Element {
  return (
    <Section
      id="plan"
      title="Plan & usage"
      action={
        <Button kind="ghost" size="sm" onClick={onOpenBilling}>
          Open Billing →
        </Button>
      }
    >
      {sub ? (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 18, fontWeight: 600 }}>{planLabel(sub.plan)}</span>
            <StatusTag tone="acc">{statusLine(sub, now)}</StatusTag>
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
              gap: 10,
              marginTop: 14
            }}
          >
            <Tile label="Credits" value={creditsText(credits)} />
            {LIMITS.filter(([key]) => key in sub.limits).map(([key, label]) => (
              <Tile key={key} label={label} value={limitText(sub.limits[key])} />
            ))}
          </div>
        </>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
          No active subscription on this account yet.
        </div>
      )}
      <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 12 }}>
        Card, invoices, credit packs and plan changes are on the Billing page.
      </div>
    </Section>
  )
}
