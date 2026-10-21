// Banners above the current-plan card: the state banner (warn = role=alert,
// info = role=status), the persistent cancel bar, and action-failure notices.
import { Card } from '../../components/ui/Card'
import type { BillingSubscription } from '../../lib/api/resources.billing'
import { formatDate, planLabel } from '../settings/billingFormat'
import type { BillingBannerSpec } from './billingState'

const BANNER_STYLE = { marginTop: 16, borderColor: 'var(--warn, var(--bd))' } as const

export function BillingBanner({
  banner
}: {
  banner: BillingBannerSpec | null
}): React.JSX.Element | null {
  if (!banner) return null
  return (
    <Card pad={14} style={BANNER_STYLE}>
      <div
        style={{ fontSize: 12.5, lineHeight: 1.5 }}
        role={banner.level === 'warn' ? 'alert' : 'status'}
      >
        {banner.text}
      </div>
    </Card>
  )
}

/** A failed or canceled action (checkout/portal): role=alert, dismissed by the
 *  next action. */
export function ActionNotice({ notice }: { notice: string | null }): React.JSX.Element | null {
  if (!notice) return null
  return (
    <Card pad={14} style={BANNER_STYLE}>
      <div style={{ fontSize: 12.5, color: 'var(--mut)' }} role="alert">
        {notice}
      </div>
    </Card>
  )
}

/** Persistent while a cancellation is pending: the plan stays live until
 *  `cancel_at`, so say exactly when it ends. */
export function CancellationBar({
  sub
}: {
  sub: BillingSubscription | null
}): React.JSX.Element | null {
  if (!sub?.cancel_at || sub.status === 'canceled') return null
  return (
    <Card pad={14} style={BANNER_STYLE}>
      <div style={{ fontSize: 12.5, lineHeight: 1.5 }} role="status">
        Your{' '}
        <strong>
          {planLabel(sub.plan)} plan ends on {formatDate(sub.cancel_at)}
        </strong>{' '}
        — you keep full access until then. Changed your mind? Resume it in{' '}
        <span style={{ whiteSpace: 'nowrap' }}>Manage billing</span>.
      </div>
    </Card>
  )
}
