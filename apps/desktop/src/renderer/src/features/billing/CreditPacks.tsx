// "Top up" inside Billing › Credits. Each pack says what it adds and the balance
// after buying it. Never a dead end: with no packs (server flag false or an
// empty list) it explains the allowance refill and offers Compare plans
// (wireflow state 13, SOLUSDEV-325).
import { Button } from '../../components/ui/Button'
import type { CreditPack } from '../../lib/api/resources'

export interface CreditPacksProps {
  packs: readonly CreditPack[]
  /** `summary.packs_available`; null when the summary failed (treated as true). */
  packsAvailable: boolean | null
  /** Busy or Stripe degraded: packs are listed but not purchasable. */
  disabled: boolean
  /** Current balance, for the "→ N after purchase" line; null hides it. */
  balance: number | null
  /** "Your next 10,000 credits arrive …" for the no-packs notice; null omits it. */
  refillText: string | null
  onBuy: (priceId: string) => void
  onComparePlans: () => void
}

import { formatCredits } from './credits.constants'

export function CreditPacks(props: CreditPacksProps): React.JSX.Element {
  const { packs, packsAvailable, disabled, balance, onBuy } = props
  const unavailable = packsAvailable === false || packs.length === 0
  return (
    <>
      <div style={{ marginTop: 22, marginBottom: 10, fontSize: 13, fontWeight: 600 }}>Top up</div>
      {unavailable ? (
        <NoPacks refillText={props.refillText} onComparePlans={props.onComparePlans} />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12 }}>
          {packs.map((pack) => (
            <PackCard
              key={pack.price_id}
              pack={pack}
              balance={balance}
              disabled={disabled}
              onBuy={onBuy}
            />
          ))}
        </div>
      )}
    </>
  )
}

function NoPacks({
  refillText,
  onComparePlans
}: {
  refillText: string | null
  onComparePlans: () => void
}): React.JSX.Element {
  return (
    <div
      style={{
        border: '1px dashed var(--bd)',
        borderRadius: 4,
        padding: 18,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 24,
        background: 'var(--bg)'
      }}
    >
      <div>
        <div style={{ fontSize: 12.5 }}>Credit packs aren&apos;t available right now.</div>
        <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 4 }}>
          You can still raise your monthly allowance by changing plan.
          {refillText ? ` ${refillText}` : ''}
        </div>
      </div>
      <Button kind="primary" size="sm" onClick={onComparePlans} style={{ flex: 'none' }}>
        Compare plans ↑
      </Button>
    </div>
  )
}

function PackCard({
  pack,
  balance,
  disabled,
  onBuy
}: {
  pack: CreditPack
  balance: number | null
  disabled: boolean
  onBuy: (priceId: string) => void
}): React.JSX.Element {
  return (
    <div
      style={{
        border: '1px solid var(--bd)',
        borderRadius: 4,
        background: 'var(--bg)',
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        gap: 4
      }}
    >
      {pack.usd != null && (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 600 }}>
          ${pack.usd}
        </span>
      )}
      <div style={{ fontSize: 12 }}>+{formatCredits(pack.credits)} credits</div>
      {balance !== null && (
        <div style={{ fontSize: 11, color: 'var(--mut)' }}>
          → {formatCredits(balance + pack.credits)} after purchase
        </div>
      )}
      <Button
        kind="soft"
        size="sm"
        disabled={disabled}
        onClick={() => onBuy(pack.price_id)}
        style={{ marginTop: 10 }}
      >
        Buy
      </Button>
    </div>
  )
}
