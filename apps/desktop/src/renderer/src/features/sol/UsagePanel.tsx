// SOLUSDEV-233: the SOL page's usage meter + top-up card. Credit-denominated
// per ADR-018 (raw token metering was rejected): "This cycle used / allowance"
// from GET /users/me/usage, and the ADR-024 credit packs through the same
// Stripe flow the Billing screen uses (useBillingData).
import { useEffect, useState } from 'react'
import { Card } from '../../components/ui/Card'
import { Mono } from '../../components/ui/Mono'
import { getUsage, type UsageApi } from '../../lib/api/resources'
import { useBillingData } from '../billing/useBillingData'
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
        height: 5,
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

function TopUpCard({ exhausted }: { exhausted: boolean }): React.JSX.Element {
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
        {billing.packs.length === 0 && (
          <span style={{ fontSize: 11, color: 'var(--mut)' }}>
            Credit packs are managed on the Billing screen.
          </span>
        )}
      </div>
    </Card>
  )
}

export function UsagePanel({ creditsExhausted }: { creditsExhausted: boolean }): React.JSX.Element {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [usage, setUsage] = useState<UsageApi | null>(null)

  // Refetch on a 402 (the balance just proved stale) — and on mount.
  useEffect(() => {
    if (!fetchEnabled) return
    let stale = false
    getUsage()
      .then((u) => {
        if (!stale) setUsage(u)
      })
      .catch(() => undefined)
    return () => {
      stale = true
    }
  }, [fetchEnabled, creditsExhausted])

  const lowOnCredits = creditsExhausted || (usage !== null && usage.balance <= LOW_BALANCE_CREDITS)

  return (
    <div style={{ marginTop: 22 }}>
      <Mono size={9.5}>SOL USAGE</Mono>
      <Card pad={12} className="sol-panel-in" style={{ marginTop: 10 }}>
        {usage === null ? (
          <div style={{ fontSize: 11, color: 'var(--mut)' }}>
            {fetchEnabled ? 'Loading usage…' : 'Usage unavailable offline.'}
          </div>
        ) : (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 12, fontWeight: 600 }}>This cycle</span>
              <Mono size={10} style={{ textTransform: 'none' }}>
                {formatCredits(usage.used)}
                {usage.allowance !== null ? ` / ${formatCredits(usage.allowance)}` : ' credits'}
              </Mono>
            </div>
            {usage.allowance !== null && usage.allowance > 0 && (
              <MeterBar fraction={usage.used / usage.allowance} />
            )}
            <div style={{ fontSize: 10, color: 'var(--mut)', marginTop: 8 }}>
              Balance: {formatCredits(usage.balance)} credits
            </div>
          </>
        )}
      </Card>
      {lowOnCredits && <TopUpCard exhausted={creditsExhausted} />}
    </div>
  )
}
