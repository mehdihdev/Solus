// SOLUSDEV-233: the SOL page's usage meter + top-up card. Credit-denominated
// per ADR-018 (raw token metering was rejected): "This cycle used / allowance"
// from GET /users/me/usage, and the ADR-024 credit packs through the same
// Stripe flow the Billing screen uses (useBillingData). SOLUSDEV-325: the
// accent + navigates to the Billing screen; the low/out-of-credits card keeps
// its inline packs and links there too.
import { useEffect, useState } from 'react'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { getUsage, type UsageApi } from '../../lib/api/resources'
import { useBillingData } from '../billing/useBillingData'
import { SOL_REASONER_NAME } from './reasoner'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

/** Below this balance the top-up card shows even without a 402 (provisional). */
const LOW_BALANCE_CREDITS = 100

function formatCredits(n: number): string {
  return n.toLocaleString('en-US')
}

function MeterBar({ fraction }: { fraction: number }): React.JSX.Element {
  const pct = Math.max(0, Math.min(1, fraction))
  return (
    <div
      role="progressbar"
      aria-label="Credits used this cycle"
      aria-valuenow={Math.round(pct * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      style={{
        marginTop: 10,
        height: 3,
        borderRadius: 99,
        background: 'var(--sur2)',
        overflow: 'hidden'
      }}
    >
      <div
        className="sol-meter-fill"
        style={{
          width: `${pct * 100}%`,
          height: '100%',
          borderRadius: 99,
          background: pct >= 0.9 ? 'var(--err)' : pct >= 0.7 ? 'var(--warn)' : 'var(--acc)'
        }}
      />
    </div>
  )
}

function TopUpCard({
  exhausted,
  onOpenBilling
}: {
  exhausted: boolean
  onOpenBilling: () => void
}): React.JSX.Element {
  const billing = useBillingData()
  return (
    <Card
      pad={12}
      className="sol-panel-in"
      style={{
        marginTop: 10,
        borderColor: 'color-mix(in srgb, var(--warn) 45%, var(--bd))'
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--warn)' }}>
        {exhausted ? 'Out of credits' : 'Running low on credits'}
      </div>
      <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 3 }}>
        Top up to keep SOL grounded.
      </div>
      {billing.notice && (
        <div style={{ fontSize: 10.5, color: 'var(--err)', marginTop: 6 }}>{billing.notice}</div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
        {billing.packs.map((pack) => (
          <button
            key={pack.price_id}
            type="button"
            className="interactive"
            disabled={billing.busy}
            onClick={() => void billing.buyPack(pack.price_id)}
            title={`${formatCredits(pack.credits)} credits`}
            style={{
              background: 'transparent',
              border: '1px solid var(--bd)',
              borderRadius: 4,
              color: 'var(--warn)',
              cursor: billing.busy ? 'wait' : 'pointer',
              fontFamily: 'var(--font-ui)',
              fontSize: 12,
              fontWeight: 600,
              padding: '6px 12px',
              opacity: billing.busy ? 0.6 : 1
            }}
          >
            {pack.usd != null ? `$${pack.usd}` : `${formatCredits(pack.credits)} cr`}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="interactive"
        onClick={onOpenBilling}
        style={{
          marginTop: 8,
          padding: 0,
          background: 'transparent',
          border: 0,
          color: 'var(--acc)',
          cursor: 'pointer',
          fontFamily: 'var(--font-ui)',
          fontSize: 11
        }}
      >
        Open Billing
      </button>
    </Card>
  )
}

type UsageStatus = 'loading' | 'ready' | 'offline'

export interface UsagePanelProps {
  creditsExhausted: boolean
  /** Navigate to the Billing screen (the + and the top-up card's link). */
  onOpenBilling: () => void
}

export function UsagePanel({
  creditsExhausted,
  onOpenBilling
}: UsagePanelProps): React.JSX.Element {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [usage, setUsage] = useState<UsageApi | null>(null)
  const [fetched, setStatus] = useState<UsageStatus>('loading')
  // Offline is derived, not stored: the effect below must never set state
  // synchronously (react-hooks/set-state-in-effect).
  const status: UsageStatus = fetchEnabled ? fetched : 'offline'

  // Refetch on a 402 (the balance just proved stale) — and on mount. A failed
  // fetch is surfaced honestly, never a forever-"Loading…" (review M2).
  useEffect(() => {
    if (!fetchEnabled) return
    let stale = false
    getUsage()
      .then((u) => {
        if (stale) return
        setUsage(u)
        setStatus('ready')
      })
      .catch(() => {
        if (!stale) setStatus('offline')
      })
    return () => {
      stale = true
    }
  }, [fetchEnabled, creditsExhausted])

  const unlimited = usage?.unlimited === true
  const lowOnCredits = lowCredits(usage, unlimited, creditsExhausted)

  return (
    <div style={{ margin: 12 }}>
      <Card pad={12} className="sol-panel-in">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Mono size={10} ls="0.08em">
              SOL USAGE
            </Mono>
            <UsageBody usage={usage} status={status} unlimited={unlimited} />
          </div>
          {!unlimited && <AddCreditsButton onClick={onOpenBilling} />}
        </div>
      </Card>
      {lowOnCredits && <TopUpCard exhausted={creditsExhausted} onOpenBilling={onOpenBilling} />}
    </div>
  )
}

function lowCredits(usage: UsageApi | null, unlimited: boolean, exhausted: boolean): boolean {
  return !unlimited && (exhausted || (usage !== null && usage.balance <= LOW_BALANCE_CREDITS))
}

function UsageBody({
  usage,
  status,
  unlimited
}: {
  usage: UsageApi | null
  status: UsageStatus
  unlimited: boolean
}): React.JSX.Element {
  if (usage === null)
    return (
      <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 6 }}>
        {status === 'loading' ? 'Loading usage…' : 'Usage unavailable offline.'}
      </div>
    )
  return <UsageSummary usage={usage} unlimited={unlimited} />
}

/** The design's accent "+": goes to the Billing screen (SOLUSDEV-325). */
function AddCreditsButton({ onClick }: { onClick: () => void }): React.JSX.Element {
  return (
    <button
      type="button"
      aria-label="Add credits"
      title="Add credits"
      className="interactive"
      onClick={onClick}
      style={{
        width: 32,
        height: 32,
        flex: 'none',
        borderRadius: 4,
        border: 0,
        background: 'var(--acc)',
        color: 'var(--acc-ink)',
        fontSize: 18,
        lineHeight: 1,
        cursor: 'pointer'
      }}
    >
      +
    </button>
  )
}

function UsageSummary({
  usage,
  unlimited
}: {
  usage: UsageApi
  unlimited: boolean
}): React.JSX.Element {
  return (
    <>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 6
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600 }}>This cycle</span>
        <Mono size={10} style={{ textTransform: 'none' }}>
          {formatCredits(usage.used)}
          {!unlimited && usage.allowance !== null
            ? ` / ${formatCredits(usage.allowance)}`
            : ' credits'}
        </Mono>
      </div>
      {!unlimited && usage.allowance !== null && usage.allowance > 0 && (
        <MeterBar fraction={usage.used / usage.allowance} />
      )}
      <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 8 }}>
        {unlimited ? 'Unlimited (development)' : `Balance: ${formatCredits(usage.balance)} credits`}
      </div>
      <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 4 }}>
        Reasoner · {SOL_REASONER_NAME}
      </div>
    </>
  )
}
