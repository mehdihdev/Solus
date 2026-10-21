// Current-plan card: plan + status chip, state-dependent rows from the
// wireflow (§Element rules), and the portal actions.
import type { ReactNode } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import type {
  BillingSubscription,
  BillingSummary,
  PortalFlow
} from '../../lib/api/resources.billing'
import { Row } from '../settings/settingsUi'
import {
  formatDate,
  formatMoney,
  planLabel,
  statusChip,
  trialEndsLabel
} from '../settings/billingFormat'
import type { BillingView } from './billingState'

export interface CurrentPlanCardProps {
  subscription: BillingSubscription | null
  summary: BillingSummary | null
  view: BillingView
  credits: number | null
  unlimited: boolean
  busy: boolean
  /** `undefined` = the general portal (Manage billing). */
  onPortal: (flow?: PortalFlow) => void
}

const UNAVAILABLE = 'Unavailable right now'
const MONO_VALUE = { fontFamily: 'var(--font-mono)', fontSize: 12 } as const

function Value({ children }: { children: ReactNode }): React.JSX.Element {
  return <span style={{ fontSize: 12.5 }}>{children}</span>
}

function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text
}

function nextChargeText(
  sub: BillingSubscription,
  summary: BillingSummary | null,
  view: BillingView
): string {
  if (view.degraded !== 'ok') return UNAVAILABLE
  if (view.cancelPending) return `None — plan ends ${formatDate(sub.cancel_at)}`
  const invoice = summary?.next_invoice
  if (!invoice) return '—'
  return `${formatMoney(invoice.amount_cents, invoice.currency)} on ${formatDate(invoice.date)}`
}

function cardText(summary: BillingSummary | null, view: BillingView): string {
  if (view.degraded !== 'ok') return UNAVAILABLE
  const card = summary?.payment_method
  return card ? `${capitalize(card.brand)} •••• ${card.last4}` : 'No card on file'
}

function TimelineRow({
  sub,
  summary,
  view
}: {
  sub: BillingSubscription
  summary: BillingSummary | null
  view: BillingView
}): React.JSX.Element | null {
  const periodEnd = sub.current_period_end ?? summary?.current_period_end ?? null
  switch (view.kind) {
    case 'local_trial_active':
      return (
        <Row label="Trial ends">
          <Value>{trialEndsLabel(view.trial.days)}</Value>
        </Row>
      )
    case 'local_trial_expired':
      return (
        <Row label="Trial ended">
          <Value>{formatDate(view.trial.endsAt)}</Value>
        </Row>
      )
    case 'stripe_trialing': {
      const invoice = summary?.next_invoice
      const then = invoice
        ? `${formatMoney(invoice.amount_cents, invoice.currency)} on ${formatDate(invoice.date)}`
        : '—'
      return (
        <Row label="Trial ends">
          <Value>{`${formatDate(view.trial.endsAt)}, then ${then}`}</Value>
        </Row>
      )
    }
    case 'cancel_pending':
      return (
        <Row label="Ends">
          <Value>{formatDate(sub.cancel_at)}</Value>
        </Row>
      )
    case 'active':
      return (
        <Row label="Renews">
          <Value>{formatDate(periodEnd)}</Value>
        </Row>
      )
    default:
      return null
  }
}

export function CurrentPlanCard(props: CurrentPlanCardProps): React.JSX.Element {
  const { subscription: sub, summary, view, credits, unlimited, busy, onPortal } = props
  if (!sub) {
    return (
      <Card pad={20} style={{ marginTop: 20 }}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
          {unlimited
            ? 'Unlimited (development)'
            : 'No active subscription on this account yet. Choose a plan below to start.'}
        </div>
      </Card>
    )
  }
  const canceled = view.kind === 'canceled'
  const disabled = busy || view.purchasesDisabled
  return (
    <Card pad={20} style={{ marginTop: 20 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          {canceled ? (
            <div style={{ fontSize: 18, fontWeight: 600 }}>No active plan</div>
          ) : (
            <>
              <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>You&apos;re on the</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
                <span style={{ fontSize: 18, fontWeight: 600 }}>{planLabel(sub.plan)} plan</span>
                <Mono size={9} color="var(--mut)">
                  {statusChip(sub.status)}
                </Mono>
              </div>
            </>
          )}
        </div>
        <Button kind="ghost" size="sm" disabled={disabled} onClick={() => onPortal(undefined)}>
          Manage billing
        </Button>
      </div>
      <div style={{ marginTop: 12 }}>
        {canceled ? (
          <PlanEndedLine sub={sub} summary={summary} />
        ) : (
          <>
            <TimelineRow sub={sub} summary={summary} view={view} />
            <Row label="Next charge">
              <Value>{nextChargeText(sub, summary, view)}</Value>
            </Row>
          </>
        )}
        <Row label="Card">
          <Value>{cardText(summary, view)}</Value>
        </Row>
        <Row label="Credits">
          <span style={MONO_VALUE}>
            {unlimited
              ? 'Unlimited (development)'
              : credits === null
                ? '—'
                : credits.toLocaleString()}
          </span>
        </Row>
        <Row label="Seats">
          <span style={MONO_VALUE}>{sub.seat_count ?? 1}</span>
        </Row>
      </div>
      <PlanActions view={view} disabled={disabled} onPortal={onPortal} />
    </Card>
  )
}

function PlanEndedLine({
  sub,
  summary
}: {
  sub: BillingSubscription
  summary: BillingSummary | null
}): React.JSX.Element {
  const ended = sub.current_period_end ?? summary?.current_period_end ?? null
  return (
    <div style={{ fontSize: 12.5, color: 'var(--mut)', padding: '9px 0' }}>
      {ended ? `Your plan ended ${formatDate(ended)}` : 'Your plan ended'}
    </div>
  )
}

function PlanActions({
  view,
  disabled,
  onPortal
}: {
  view: BillingView
  disabled: boolean
  onPortal: (flow?: PortalFlow) => void
}): React.JSX.Element | null {
  if (view.cancelPending) {
    return (
      <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 10 }}>
        Resume in Manage billing
      </div>
    )
  }
  if (!view.showPlanActions) return null
  return (
    <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
      <Button kind="soft" size="sm" disabled={disabled} onClick={() => onPortal('update')}>
        Change plan
      </Button>
      <Button kind="ghost" size="sm" disabled={disabled} onClick={() => onPortal('cancel')}>
        Cancel plan
      </Button>
    </div>
  )
}
