// Billing summary: the current user's live subscription (plan, trial state,
// seats, plan limits) from GET /users/me/subscription. Read-only this cycle —
// the provider-facing checkout/portal routes are deferred (API.md §2.14).
import { Mono } from '../../../components/ui/Mono'
import { Section, Row } from '../settingsUi'
import {
  formatDate,
  planLabel,
  statusLabel,
  trialEndsLabel,
  trialState,
  limitLabel
} from '../billingFormat'
import type { SettingsData } from '../useSettingsData'
import type { BillingSubscription } from '../../../lib/api/resources.billing'

const LIMIT_ROWS: readonly (readonly [string, string])[] = [
  ['max_integrations', 'Integrations'],
  ['max_projects', 'Projects'],
  ['max_teams', 'Teams']
]

function SubscriptionSummary({
  sub,
  now
}: {
  sub: BillingSubscription
  now?: number
}): React.JSX.Element {
  const trial = trialState(sub, now)
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
      {trial.kind === 'active' && (
        <Row label="Trial ends">
          <span style={{ fontSize: 12.5 }}>{trialEndsLabel(trial.days)}</span>
        </Row>
      )}
      {trial.kind === 'ended' && (
        <Row label="Trial ended">
          <span style={{ fontSize: 12.5 }}>{formatDate(trial.endsAt)}</span>
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
  now
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
