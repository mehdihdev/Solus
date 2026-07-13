// Billing summary: the current user's live subscription (plan, trial state,
// seats, plan limits) from GET /users/me/subscription. Read-only this cycle —
// the provider-facing checkout/portal routes are deferred (API.md §2.14).
import { Mono } from '../../../components/ui/Mono'
import { Section, Row } from '../settingsUi'
import { planLabel, statusLabel, trialDaysLeft, limitLabel } from '../billingFormat'
import type { SettingsData } from '../useSettingsData'
import type { Subscription } from '../../../lib/api/resources'

const LIMIT_ROWS: readonly (readonly [string, string])[] = [
  ['max_integrations', 'Integrations'],
  ['max_projects', 'Projects'],
  ['max_teams', 'Teams']
]

function SubscriptionSummary({ sub, now }: { sub: Subscription; now: number }): React.JSX.Element {
  const days = sub.status === 'trialing' ? trialDaysLeft(sub.expires_at, now) : null
  return (
    <>
      <Row label="Plan">
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>{planLabel(sub.plan)}</span>
          <Mono size={9} color="var(--mut)">
            {statusLabel(sub.status).toUpperCase()}
          </Mono>
        </span>
      </Row>
      {days !== null && (
        <Row label="Trial ends">
          <span style={{ fontSize: 12.5 }}>
            {days === 0 ? 'today' : `in ${days} ${days === 1 ? 'day' : 'days'}`}
          </span>
        </Row>
      )}
      <Row label="Seats">
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{sub.seat_count ?? 1}</span>
      </Row>
      {LIMIT_ROWS.filter(([key]) => key in sub.limits).map(([key, label]) => (
        <Row key={key} label={label}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            {limitLabel(sub.limits[key])}
          </span>
        </Row>
      ))}
    </>
  )
}

export function BillingSection({
  data,
  now = Date.now()
}: {
  data: SettingsData
  now?: number
}): React.JSX.Element {
  const { subscription } = data
  return (
    <Section title="Billing" sub="Your plan and its limits. Manage payment in the billing portal.">
      {subscription ? (
        <SubscriptionSummary sub={subscription} now={now} />
      ) : (
        <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>
          No active subscription on this account yet.
        </div>
      )}
    </Section>
  )
}
