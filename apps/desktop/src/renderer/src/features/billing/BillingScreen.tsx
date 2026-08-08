// Billing screen (SOLUSDEV-83 follow-up): a first-class rail surface for the
// current plan, real Stripe Checkout, credit packs, and the billing portal.
// Reads the live subscription + credit balance; "Subscribe" opens Stripe
// Checkout in the browser and the plan is applied by the webhook on payment.
// Enterprise stays contact-sales. When Stripe isn't configured yet, actions
// surface a notice rather than failing silently.
import { useState } from 'react'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Row } from '../settings/settingsUi'
import { planLabel, statusLabel, trialDaysLeft, limitLabel } from '../settings/billingFormat'
import type { CheckoutInterval, CreditPack, PlanType, Subscription } from '../../lib/api/resources'
import { useOfflineReason } from '../workspace/workspaceOnline'
import { useBillingData, type BillingData } from './useBillingData'

/** Self-serve plans: prices, features, and limits (mirrors ADR-023/024 and the
 *  server's models.PLAN_LIMITS / plan_credit_grants config — keep in step when
 *  those change). Enterprise is inbound-only this cycle: per-seat pricing on the
 *  organization's wallet, no self-serve checkout. */
interface PlanCardDef {
  plan: PlanType
  tagline: string
  /** Whole-dollar price per interval; absent ⇒ custom (contact sales). */
  price?: { month: number; year: number }
  /** Headline capabilities shown above the limit rows. */
  features: readonly string[]
  /** Ordered [label, limit] pairs; null limit ⇒ Unlimited. `undefined` ⇒ Custom. */
  limits: readonly (readonly [string, number | null | undefined])[]
  contactSales?: boolean
}

const PLAN_CARDS: readonly PlanCardDef[] = [
  {
    plan: 'basic',
    tagline: 'For getting started',
    price: { month: 25, year: 200 },
    features: ['All capabilities', 'Starts with 2,500 credits'],
    limits: [
      ['Projects', 3],
      ['Teams', 2],
      ['Integrations', 4]
    ]
  },
  {
    plan: 'pro',
    tagline: 'For full-stack teams',
    price: { month: 35, year: 300 },
    features: ['All capabilities', 'Starts with 10,000 credits'],
    limits: [
      ['Projects', null],
      ['Teams', null],
      ['Integrations', null]
    ]
  },
  {
    plan: 'enterprise',
    tagline: 'Custom limits, SSO, and support',
    features: [
      'Per-seat pricing, set per agreement',
      "Billed to your organization's wallet — one subscription covers every seat"
    ],
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
          Your plan, credits, and payment — managed securely through Stripe.
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
  const { subscription, credits, packs, busy, notice, startCheckout, buyPack, openPortal } = data
  const [interval, setInterval] = useState<CheckoutInterval>('month')
  // A live Stripe subscriber changes plans in the portal, never via a new Checkout
  // (which would double-bill). A canceled subscription is not "live".
  const hasLiveStripeSub =
    !!subscription?.stripe_subscription_id && subscription.status !== 'canceled'
  return (
    <>
      {notice && (
        <Card pad={14} style={{ marginTop: 16, borderColor: 'var(--warn, var(--bd))' }}>
          <div style={{ fontSize: 12.5, color: 'var(--mut)' }} role="alert">
            {notice}
          </div>
        </Card>
      )}
      <CancellationBar sub={subscription} />
      <CurrentPlanCard sub={subscription} credits={credits} busy={busy} onManage={openPortal} />

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
        <IntervalToggle value={interval} onChange={setInterval} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        {PLAN_CARDS.map((def) => (
          <PlanCard
            key={def.plan}
            def={def}
            interval={interval}
            current={subscription?.plan === def.plan && subscription?.status !== 'canceled'}
            manageInPortal={hasLiveStripeSub}
            busy={busy}
            onSubscribe={() => void startCheckout(def.plan, interval)}
            onManage={() => void openPortal()}
          />
        ))}
      </div>

      {packs.length > 0 && <CreditPacks packs={packs} busy={busy} onBuy={buyPack} />}
    </>
  )
}

function IntervalToggle({
  value,
  onChange
}: {
  value: CheckoutInterval
  onChange: (v: CheckoutInterval) => void
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
          {opt === 'month' ? 'Monthly' : 'Yearly'}
        </button>
      ))}
    </div>
  )
}

/** Persistent while a cancellation is pending: the plan stays live until
 *  `cancel_at`, so say exactly when it ends. The webhook clears `cancel_at`
 *  on resume or once the term ends, which removes the bar. */
function CancellationBar({ sub }: { sub: Subscription | null }): React.JSX.Element | null {
  if (!sub?.cancel_at || sub.status === 'canceled') return null
  const ends = new Date(sub.cancel_at).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC'
  })
  return (
    <Card pad={14} style={{ marginTop: 16, borderColor: 'var(--warn, var(--bd))' }}>
      <div style={{ fontSize: 12.5, lineHeight: 1.5 }} role="status">
        Your{' '}
        <strong>
          {planLabel(sub.plan)} plan ends on {ends}
        </strong>{' '}
        — you keep full access until then. Changed your mind? Resume it in{' '}
        <span style={{ whiteSpace: 'nowrap' }}>Manage billing</span>.
      </div>
    </Card>
  )
}

function CurrentPlanCard({
  sub,
  credits,
  busy,
  onManage
}: {
  sub: Subscription | null
  credits: number | null
  busy: boolean
  onManage: () => void
}): React.JSX.Element {
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
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>You&apos;re on the</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
            <span style={{ fontSize: 18, fontWeight: 600 }}>{planLabel(sub.plan)} plan</span>
            <Mono size={9} color="var(--mut)">
              {statusLabel(sub.status).toUpperCase()}
            </Mono>
          </div>
        </div>
        <Button kind="ghost" size="sm" disabled={busy} onClick={onManage}>
          Manage billing
        </Button>
      </div>
      <div style={{ marginTop: 12 }}>
        {days !== null && (
          <Row label="Trial ends">
            <span style={{ fontSize: 12.5 }}>
              {days === 0 ? 'today' : `in ${days} ${days === 1 ? 'day' : 'days'}`}
            </span>
          </Row>
        )}
        <Row label="Credits">
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            {credits === null ? '—' : credits.toLocaleString()}
          </span>
        </Row>
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
  interval,
  current,
  manageInPortal,
  busy,
  onSubscribe,
  onManage
}: {
  def: PlanCardDef
  interval: CheckoutInterval
  current: boolean
  manageInPortal: boolean
  busy: boolean
  onSubscribe: () => void
  onManage: () => void
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
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginTop: 10 }}>
        {def.price ? (
          <>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 600 }}>
              ${interval === 'year' ? def.price.year : def.price.month}
            </span>
            <span style={{ fontSize: 11, color: 'var(--mut)' }}>
              {interval === 'year' ? '/year' : '/month'}
            </span>
          </>
        ) : (
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--mut)' }}>Custom pricing</span>
        )}
      </div>
      <div style={{ marginTop: 8 }}>
        {def.features.map((feature) => (
          <div
            key={feature}
            style={{ fontSize: 11.5, lineHeight: 1.5, padding: '2px 0', color: 'var(--fg)' }}
          >
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
        <PlanAction
          def={def}
          interval={interval}
          current={current}
          manageInPortal={manageInPortal}
          busy={busy}
          onSubscribe={onSubscribe}
          onManage={onManage}
        />
      </div>
    </Card>
  )
}

function PlanAction({
  def,
  interval,
  current,
  manageInPortal,
  busy,
  onSubscribe,
  onManage
}: {
  def: PlanCardDef
  interval: CheckoutInterval
  current: boolean
  manageInPortal: boolean
  busy: boolean
  onSubscribe: () => void
  onManage: () => void
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
      <a href="mailto:sales@solus.dev?subject=Enterprise%20plan" style={{ textDecoration: 'none' }}>
        <Mono size={9} color="var(--mut)">
          CONTACT SALES
        </Mono>
      </a>
    )
  }
  // An existing live Stripe subscriber switches plans through the portal, not a
  // second Checkout (double-billing guard — the backend also enforces this).
  if (manageInPortal) {
    return (
      <Button kind="soft" size="sm" disabled={busy} onClick={onManage}>
        Switch in portal
      </Button>
    )
  }
  return (
    <Button kind="primary" size="sm" disabled={busy} onClick={onSubscribe}>
      {busy ? (
        <Spinner size={11} color="var(--acc-ink)" />
      ) : (
        `Subscribe · ${interval === 'year' ? 'Yearly' : 'Monthly'}`
      )}
    </Button>
  )
}

function CreditPacks({
  packs,
  busy,
  onBuy
}: {
  packs: readonly CreditPack[]
  busy: boolean
  onBuy: (priceId: string) => void
}): React.JSX.Element {
  return (
    <>
      <div style={{ marginTop: 22, marginBottom: 10, fontSize: 13, fontWeight: 600 }}>
        Buy credits
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        {packs.map((pack) => (
          <Card key={pack.price_id} pad={14} style={{ display: 'flex', flexDirection: 'column' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 600 }}>
              {pack.credits.toLocaleString()}
            </div>
            <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 2, flex: 1 }}>credits</div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginTop: 10
              }}
            >
              <Button kind="soft" size="sm" disabled={busy} onClick={() => onBuy(pack.price_id)}>
                Buy
              </Button>
              {pack.usd != null && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600 }}>
                  ${pack.usd}
                </span>
              )}
            </div>
          </Card>
        ))}
      </div>
    </>
  )
}
