// Buy credits. The section is never hidden: when packs are unavailable (server
// flag false or empty list) it says so explicitly (wireflow state 13).
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import type { CreditPack } from '../../lib/api/resources'

export interface CreditPacksProps {
  packs: readonly CreditPack[]
  /** `summary.packs_available`; null when the summary failed (treated as true). */
  packsAvailable: boolean | null
  /** Busy or Stripe degraded: packs are listed but not purchasable. */
  disabled: boolean
  onBuy: (priceId: string) => void
}

export function CreditPacks({
  packs,
  packsAvailable,
  disabled,
  onBuy
}: CreditPacksProps): React.JSX.Element {
  const unavailable = packsAvailable === false || packs.length === 0
  return (
    <>
      <div style={{ marginTop: 22, marginBottom: 10, fontSize: 13, fontWeight: 600 }}>
        Buy credits
      </div>
      {unavailable ? (
        <div style={{ fontSize: 12.5, color: 'var(--mut)' }}>
          Credit packs aren&apos;t available right now.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {packs.map((pack) => (
            <PackCard key={pack.price_id} pack={pack} disabled={disabled} onBuy={onBuy} />
          ))}
        </div>
      )}
    </>
  )
}

function PackCard({
  pack,
  disabled,
  onBuy
}: {
  pack: CreditPack
  disabled: boolean
  onBuy: (priceId: string) => void
}): React.JSX.Element {
  return (
    <Card pad={14} style={{ display: 'flex', flexDirection: 'column' }}>
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
        <Button kind="soft" size="sm" disabled={disabled} onClick={() => onBuy(pack.price_id)}>
          Buy
        </Button>
        {pack.usd != null && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600 }}>
            ${pack.usd}
          </span>
        )}
      </div>
    </Card>
  )
}
