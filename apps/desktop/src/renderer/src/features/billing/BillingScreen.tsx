// Billing screen (SOLUSDEV-152): a first-class rail surface for the current
// plan and self-serve plan changes. Reads the live subscription (GET
// /users/me/subscription) and switches plans via PATCH — no Stripe call this
// cycle (ADR-032); Enterprise is inbound-only (contact sales). Credit balance
// and checkout are deferred (no public routes yet), so we don't fabricate them.
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Row } from '../settings/settingsUi'
import { planLabel, statusLabel, trialDaysLeft, limitLabel } from '../settings/billingFormat'
import type { PlanType, Subscription } from '../../lib/api/resources'
import { useOfflineReason } from '../workspace/workspaceOnline'
import { useBillingData, type BillingData } from './useBillingData'

/** Self-serve plans and their limits (mirrors models.PLAN_LIMITS). Enterprise is
 *  inbound-only this cycle, so it carries no self-serve switch. */
interface PlanCardDef {
  plan: PlanType
  tagline: string
  /** Ordered [label, limit] pairs; null limit ⇒ Unlimited. `undefined` ⇒ Custom. */
  limits: readonly (readonly [string, number | null | undefined])[]
  contactSales?: boolean
}

const PLAN_CARDS: readonly PlanCardDef[] = [
  {
    plan: 'basic',
    tagline: 'For getting started',
    limits: [
      ['Projects', 3],
      ['Teams', 2],
      ['Integrations', 4]
    ]
  },
  {
    plan: 'pro',
    tagline: 'For full-stack teams',
    limits: [
      ['Projects', null],
      ['Teams', null],
      ['Integrations', null]
    ]
  },
  {
    plan: 'enterprise',
    tagline: 'Custom limits, SSO, and support',
    limits: [
      ['Projects', undefined],
      ['Teams', undefined],
      ['Integrations', undefined]
    ],
    contactSales: true
  }
]

export function BillingScreen(): React.JSX.Element {
  const data = useBillingData()
  if (data.status === 'loading') {
    return (
      <div
        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        data-testid="billing-loading"
      >
        <Spinner size={20} />
      </div>
    )
  }
  return (
    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
      <div style={{ maxWidth: 820, margin: '0 auto', padding: '22px 24px 48px' }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: '-0.015em' }}>
          Billing
        </h1>
        <div style={{ fontSize: 12.5, color: 'var(--mut)', marginTop: 4 }}>
          Your plan and its limits. Payment is managed in the billing portal.
        </div>
        {data.status === 'offline' ? <BillingOffline /> : <BillingLive data={data} />}
      </div>
    </div>
  )
}

function BillingOffline(): React.JSX.Element {
  const reason = useOfflineReason()
  return (
    <Card pad={20} style={{ marginTop: 20 }}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', lineHeight: 1.55 }}>
        {reason === 'api_unreachable'
          ? "You're signed in, but Solus can't reach its API — your plan and limits will appear here once it's back."
          : 'Sign in to Solus to manage billing — your plan, trial, and limits live here.'}
      </div>
    </Card>
  )
}

function BillingLive({ data }: { data: BillingData }): React.JSX.Element {
  const { subscription, changing, changePlan } = data
  return (
    <>
      <CurrentPlanCard sub={subscription} />
      <div style={{ marginTop: 18, marginBottom: 10, fontSize: 13, fontWeight: 600 }}>Plans</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        {PLAN_CARDS.map((def) => (
          <PlanCard
            key={def.plan}
            def={def}
            current={subscription?.plan === def.plan}
            changing={changing}
            onSwitch={() => void changePlan(def.plan)}
          />
        ))}
      </div>
    </>
  )
}

function CurrentPlanCard({ sub }: { sub: Subscription | null }): React.JSX.Element {
  if (!sub) {
    return (
      <Card pad={20} style={{ marginTop: 20 }}>
        <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
          No active subscription on this account yet. Choose a plan below to start.
        </div>
      </Card>
    )
  }
  const days = sub.status === 'trialing' ? trialDaysLeft(sub.expires_at) : null
  return (
    <Card pad={20} style={{ marginTop: 20 }}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>You&apos;re on the</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
        <span style={{ fontSize: 18, fontWeight: 600 }}>{planLabel(sub.plan)} plan</span>
        <Mono size={9} color="var(--mut)">
          {statusLabel(sub.status).toUpperCase()}
        </Mono>
      </div>
      <div style={{ marginTop: 12 }}>
        {days !== null && (
          <Row label="Trial ends">
            <span style={{ fontSize: 12.5 }}>
              {days === 0 ? 'today' : `in ${days} ${days === 1 ? 'day' : 'days'}`}
            </span>
          </Row>
        )}
        <Row label="Seats">
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            {sub.seat_count ?? 1}
          </span>
        </Row>
      </div>
    </Card>
  )
}

function PlanCard({
  def,
  current,
  changing,
  onSwitch
}: {
  def: PlanCardDef
  current: boolean
  changing: boolean
  onSwitch: () => void
}): React.JSX.Element {
  return (
    <Card
      pad={16}
      style={{
        borderColor: current ? 'var(--acc)' : 'var(--bd)',
        display: 'flex',
        flexDirection: 'column'
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600 }}>{planLabel(def.plan)}</div>
      <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 2, lineHeight: 1.4 }}>
        {def.tagline}
      </div>
      <div style={{ marginTop: 10, flex: 1 }}>
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
        <PlanAction def={def} current={current} changing={changing} onSwitch={onSwitch} />
      </div>
    </Card>
  )
}

function PlanAction({
  def,
  current,
  changing,
  onSwitch
}: {
  def: PlanCardDef
  current: boolean
  changing: boolean
  onSwitch: () => void
}): React.JSX.Element {
  if (current) {
    return (
      <Mono size={9} color="var(--acc)">
        CURRENT PLAN
      </Mono>
    )
  }
  if (def.contactSales) {
    return (
      <Mono size={9} color="var(--mut)">
        CONTACT SALES
      </Mono>
    )
  }
  return (
    <Button kind="primary" size="sm" disabled={changing} onClick={onSwitch}>
      {changing ? <Spinner size={11} color="var(--acc-ink)" /> : `Switch to ${planLabel(def.plan)}`}
    </Button>
  )
}
