// Billing › Credits (SOLUSDEV-325): where SOL's "Add credits" lands. Balance
// (GET /users/me/credits) + this cycle's meter (GET /users/me/usage, the same
// numbers SOL shows), the Top up packs, a "from SOL" strip with the way back,
// and the post-checkout confirmation. Wireflow: docs/wireflows/billing.md.
import { forwardRef } from 'react'
import type { CreditPack, UsageApi } from '../../lib/api/resources'
import { Mono } from '../../components/ui/Mono'
import { formatDate } from '../settings/billingFormat'
import { CreditPacks } from './CreditPacks'
import { LOW_BALANCE_CREDITS, formatCredits } from './credits.constants'
import type { PackPurchase } from './useBillingData'

export interface CreditsSectionProps {
  credits: number | null
  unlimited: boolean
  usage: UsageApi | null
  packs: readonly CreditPack[]
  packsAvailable: boolean | null
  disabled: boolean
  onBuy: (priceId: string) => void
  /** Arrived via SOL's Add credits: highlight + strip + Back to SOL. */
  fromSol: boolean
  /** Back to SOL; null = no shell navigation here, so no button. */
  onBackToSol: (() => void) | null
  onComparePlans: () => void
  /** The last in-app pack checkout that succeeded; null = none this visit. */
  purchase: PackPurchase | null
  /** Refetch now (the purchase banner's Refresh while credits are landing). */
  onRefresh: () => void
}

const LINK = {
  padding: 0,
  background: 'transparent',
  border: 0,
  color: 'var(--acc)',
  cursor: 'pointer',
  fontFamily: 'var(--font-ui)',
  fontSize: 11.5
} as const

export const CreditsSection = forwardRef<HTMLElement, CreditsSectionProps>(
  function CreditsSection(props, ref) {
    const { credits, usage, fromSol, purchase } = props
    const highlighted = fromSol && !purchase
    return (
      <section
        ref={ref}
        aria-label="Credits"
        style={{
          marginTop: 22,
          scrollMarginTop: 16,
          border: `1px solid ${highlighted ? 'var(--acc)' : 'var(--bd)'}`,
          borderRadius: 4,
          background: 'var(--sur)',
          padding: '20px 22px',
          boxShadow: highlighted
            ? '0 0 0 4px color-mix(in srgb, var(--acc) 18%, transparent)'
            : undefined
        }}
      >
        {purchase ? (
          <PurchaseStatus
            purchase={purchase}
            credits={credits}
            fromSol={fromSol}
            onBackToSol={fromSol ? props.onBackToSol : null}
            onRefresh={props.onRefresh}
          />
        ) : (
          fromSol && <FromSolStrip onBackToSol={props.onBackToSol} />
        )}
        <BalanceHeader credits={credits} unlimited={props.unlimited} usage={usage} />
        <CreditPacks
          packs={props.packs}
          packsAvailable={props.packsAvailable}
          disabled={props.disabled}
          balance={props.unlimited ? null : credits}
          refillText={refillText(usage)}
          onBuy={props.onBuy}
          onComparePlans={props.onComparePlans}
        />
      </section>
    )
  }
)

function refillText(usage: UsageApi | null): string | null {
  if (!usage || usage.allowance === null || usage.allowance <= 0) return null
  return `Your next ${formatCredits(usage.allowance)} credits arrive ${formatDate(usage.cycle_end)}.`
}

function FromSolStrip({ onBackToSol }: { onBackToSol: (() => void) | null }): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 10px',
        margin: '-6px -8px 16px',
        borderRadius: 4,
        background: 'color-mix(in srgb, var(--acc) 10%, var(--sur2))'
      }}
    >
      <span style={{ fontSize: 12 }}>Adding credits for SOL</span>
      {onBackToSol && (
        <button type="button" className="interactive" onClick={onBackToSol} style={LINK}>
          ← Back to SOL
        </button>
      )}
    </div>
  )
}

function PurchaseStatus({
  purchase,
  credits,
  fromSol,
  onBackToSol,
  onRefresh
}: {
  purchase: PackPurchase
  credits: number | null
  fromSol: boolean
  onBackToSol: (() => void) | null
  onRefresh: () => void
}): React.JSX.Element {
  // The webhook grants the credits moments after Stripe confirms payment. With
  // no balance before (it hadn't loaded), any loaded balance counts as landed.
  const landed =
    credits !== null &&
    (purchase.balanceBefore === null || credits >= purchase.balanceBefore + purchase.credits)
  return (
    <div
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        padding: '12px 14px',
        margin: '-6px -8px 18px',
        borderRadius: 4,
        border: '1px solid color-mix(in srgb, var(--ok) 45%, var(--bd))',
        background: 'color-mix(in srgb, var(--ok) 10%, var(--sur2))'
      }}
    >
      <div>
        <div style={{ fontWeight: 600, fontSize: 12.5 }}>
          {landed
            ? `+${formatCredits(purchase.credits)} credits added`
            : 'Payment received — adding your credits…'}
        </div>
        {landed && (
          <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 2 }}>
            {fromSol ? 'Payment received. SOL can keep going.' : 'Payment received.'}
          </div>
        )}
        {!landed && (
          <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 2 }}>
            This usually takes a few seconds.{' '}
            <button type="button" className="interactive" onClick={onRefresh} style={LINK}>
              Refresh
            </button>
          </div>
        )}
      </div>
      {landed && onBackToSol && (
        <button
          type="button"
          className="interactive"
          onClick={onBackToSol}
          style={{
            flex: 'none',
            height: 32,
            padding: '0 14px',
            borderRadius: 4,
            border: 0,
            background: 'var(--acc)',
            color: 'var(--acc-ink)',
            fontFamily: 'var(--font-ui)',
            fontWeight: 600,
            fontSize: 12,
            cursor: 'pointer'
          }}
        >
          Back to SOL →
        </button>
      )}
    </div>
  )
}

function BalanceHeader({
  credits,
  unlimited,
  usage
}: {
  credits: number | null
  unlimited: boolean
  usage: UsageApi | null
}): React.JSX.Element {
  const low = !unlimited && credits !== null && credits <= LOW_BALANCE_CREDITS
  return (
    <div
      style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 24 }}
    >
      <div>
        <Mono size={10} ls="0.08em">
          CREDITS
        </Mono>
        <div style={{ marginTop: 6, display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span
            style={{
              fontSize: unlimited ? 18 : 30,
              fontWeight: 600,
              fontFamily: 'var(--font-mono)',
              color: low ? 'var(--warn)' : 'var(--tx)'
            }}
          >
            {unlimited
              ? 'Unlimited (development)'
              : credits === null
                ? '—'
                : formatCredits(credits)}
          </span>
          {!unlimited && (
            <span style={{ fontSize: 13, color: 'var(--mut)' }}>credits available</span>
          )}
        </div>
      </div>
      {!unlimited && usage && <CycleMeter usage={usage} />}
    </div>
  )
}

function CycleMeter({ usage }: { usage: UsageApi }): React.JSX.Element | null {
  if (usage.allowance === null || usage.allowance <= 0) return null
  const pct = Math.max(0, Math.min(1, usage.used / usage.allowance))
  return (
    <div style={{ width: 300, maxWidth: '45%' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: 8,
          fontSize: 11,
          color: 'var(--mut)'
        }}
      >
        <span>
          {formatCredits(usage.used)} of {formatCredits(usage.allowance)} used this cycle
        </span>
        <span>Resets {formatDate(usage.cycle_end)}</span>
      </div>
      <div
        role="progressbar"
        aria-label="Credits used this cycle"
        aria-valuenow={Math.round(pct * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        style={{
          marginTop: 6,
          height: 4,
          borderRadius: 99,
          background: 'var(--sur2)',
          overflow: 'hidden'
        }}
      >
        <div
          style={{
            width: `${pct * 100}%`,
            height: '100%',
            background: pct >= 0.9 ? 'var(--err)' : pct >= 0.7 ? 'var(--warn)' : 'var(--acc)'
          }}
        />
      </div>
    </div>
  )
}
