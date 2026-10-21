// Plans section: interval toggle + Basic / Pro / Enterprise cards. Prices come
// from the summary only; actions follow the wireflow state table.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import type { PlanType } from '../../lib/api/resources'
import type {
  BillingInterval,
  BillingSubscription,
  BillingSummary,
  PortalFlow
} from '../../lib/api/resources.billing'
import { formatPlanPrice, intervalLabel, limitLabel, planLabel } from '../settings/billingFormat'
import type { BillingView } from './billingState'
import { ContactSalesButton } from './ContactSalesButton'
import { IntervalToggle } from './IntervalToggle'
import { PLAN_CARDS, type PlanCardDef } from './planCardDefs'

export interface PlanCardsProps {
  subscription: BillingSubscription | null
  summary: BillingSummary | null
  view: BillingView
  busy: boolean
  onSubscribe: (plan: PlanType, interval: BillingInterval) => void
  onPortal: (flow: PortalFlow) => void
}

export function PlanCards(props: PlanCardsProps): React.JSX.Element {
  const { subscription, summary, view } = props
  const [choice, setChoice] = useState<BillingInterval | null>(null)
  const interval = choice ?? view.defaultInterval
  const currentInterval = subscription?.billing_interval ?? summary?.billing_interval ?? null
  return (
    <>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginTop: 18,
          marginBottom: 10
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600 }}>Plans</div>
        <IntervalToggle value={interval} onChange={setChoice} />
      </div>
      {view.cancelPending && (
        <div style={{ fontSize: 11.5, color: 'var(--mut)', marginBottom: 10 }}>
          Resume in Manage billing to change plans.
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        {PLAN_CARDS.map((def) => {
          const isCurrent =
            !def.contactSales &&
            subscription?.plan === def.plan &&
            subscription.status !== 'canceled' &&
            currentInterval === interval
          return (
            <PlanCard
              key={def.plan}
              def={def}
              {...props}
              interval={interval}
              isCurrent={isCurrent}
            />
          )
        })}
      </div>
    </>
  )
}

interface PlanCardProps extends PlanCardsProps {
  def: PlanCardDef
  interval: BillingInterval
  isCurrent: boolean
}

function PlanCard(props: PlanCardProps): React.JSX.Element {
  const { def, interval, isCurrent, summary } = props
  return (
    <Card
      pad={16}
      role="group"
      aria-label={planLabel(def.plan)}
      style={{
        borderColor: isCurrent ? 'var(--acc)' : 'var(--bd)',
        display: 'flex',
        flexDirection: 'column'
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600 }}>{planLabel(def.plan)}</div>
      <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 2, lineHeight: 1.4 }}>
        {def.tagline}
      </div>
      <PlanPrice def={def} interval={interval} summary={summary} />
      <div style={{ marginTop: 8 }}>
        {def.features.map((feature) => (
          <div key={feature} style={{ fontSize: 11.5, lineHeight: 1.5, padding: '2px 0' }}>
            {feature}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 8, flex: 1 }}>
        {def.limits.map(([label, value]) => (
          <div
            key={label}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 11.5,
              padding: '3px 0'
            }}
          >
            <span style={{ color: 'var(--mut)' }}>{label}</span>
            <span style={{ fontFamily: 'var(--font-mono)' }}>
              {value === undefined ? 'Custom' : limitLabel(value)}
            </span>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 12 }}>
        <PlanAction {...props} />
      </div>
    </Card>
  )
}

function PlanPrice({
  def,
  interval,
  summary
}: {
  def: PlanCardDef
  interval: BillingInterval
  summary: BillingSummary | null
}): React.JSX.Element {
  const price = summary?.prices?.find((p) => p.plan === def.plan && p.interval === interval)
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 10 }}>
      {def.contactSales ? (
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--mut)' }}>Custom</span>
      ) : price ? (
        <>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 600 }}>
            {formatPlanPrice(price.amount_cents, price.currency)}
          </span>
          <span style={{ fontSize: 11, color: 'var(--mut)' }}>/ {interval}</span>
        </>
      ) : (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 22, color: 'var(--mut)' }}>—</span>
      )}
    </div>
  )
}

function PlanAction(props: PlanCardProps): React.JSX.Element {
  const { def, interval, isCurrent, view, busy, onSubscribe, onPortal } = props
  if (def.contactSales) return <ContactSalesButton />
  if (isCurrent) {
    return (
      <Mono size={9} color="var(--acc)">
        CURRENT PLAN
      </Mono>
    )
  }
  const disabled = busy || view.purchasesDisabled || view.cancelPending
  if (view.isLive) {
    return (
      <Button kind="soft" size="sm" disabled={disabled} onClick={() => onPortal('update')}>
        Change plan
      </Button>
    )
  }
  return (
    <Button
      kind="primary"
      size="sm"
      disabled={disabled}
      onClick={() => onSubscribe(def.plan, interval)}
    >
      {busy ? (
        <Spinner size={11} color="var(--acc-ink)" />
      ) : (
        `Subscribe · ${intervalLabel(interval)}`
      )}
    </Button>
  )
}
