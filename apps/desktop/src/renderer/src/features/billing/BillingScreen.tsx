// Billing screen (SOLUSDEV-236): a first-class rail surface for the current
// plan, Stripe Checkout, credit packs and the billing portal. State logic lives
// in billingState.ts (wireflow docs/wireflows/billing.md); data in
// useBillingData. Plan prices come from GET /billing/summary only.
import { Card } from '../../components/ui/Card'
import { Spinner } from '../../components/ui/Spinner'
import { useOfflineReason } from '../workspace/workspaceOnline'
import { ActionNotice, BillingBanner, CancellationBar } from './BillingBanner'
import { classifyBilling, type BillingView } from './billingState'
import { CreditPacks } from './CreditPacks'
import { CurrentPlanCard } from './CurrentPlanCard'
import { PlanCards } from './PlanCards'
import { useBillingData, type BillingData } from './useBillingData'

export function BillingScreen(): React.JSX.Element {
  const data = useBillingData()
  const view = classifyBilling({
    status: data.status,
    subscription: data.subscription,
    summary: data.summary,
    now: data.asOf
  })
  if (view.kind === 'loading') {
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
        {view.kind === 'offline' ? <BillingOffline /> : <BillingLive data={data} view={view} />}
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

function BillingLive({ data, view }: { data: BillingData; view: BillingView }): React.JSX.Element {
  const { subscription, summary, busy } = data
  return (
    <>
      <ActionNotice notice={data.notice} />
      <BillingBanner banner={view.banner} />
      <CancellationBar sub={subscription} />
      <CurrentPlanCard
        subscription={subscription}
        summary={summary}
        view={view}
        credits={data.credits}
        unlimited={data.unlimited}
        busy={busy}
        onPortal={(flow) => void data.openPortalFlow(flow)}
      />
      <PlanCards
        subscription={subscription}
        summary={summary}
        view={view}
        busy={busy}
        onSubscribe={(plan, interval) => void data.startCheckout(plan, interval)}
        onPortal={(flow) => void data.openPortalFlow(flow)}
      />
      <CreditPacks
        packs={data.packs}
        packsAvailable={summary ? summary.packs_available : null}
        disabled={busy || view.purchasesDisabled}
        onBuy={(priceId) => void data.buyPack(priceId)}
      />
    </>
  )
}
