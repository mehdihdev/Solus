// SOLUSDEV-235 / EXT-13 — what an ExtensionFrame shows when it is NOT showing
// the extension: the skeleton that holds the slot while a download or handshake
// is genuinely in flight, and the honest cards for error / blocked / disabled
// (wireflow §2 states, architecture §8 copy). Everything here is host text;
// the only extension-authored string is the manifest name, rendered as text.
import type { ReactNode } from 'react'
import { Button } from '../../../components/ui/Button'
import { Mono } from '../../../components/ui/Mono'
import { Spinner } from '../../../components/ui/Spinner'

const FILL: React.CSSProperties = {
  flex: 1,
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 10,
  padding: 24,
  textAlign: 'center',
  background: 'var(--sur)',
  color: 'var(--tx)',
  boxSizing: 'border-box'
}

export function FrameSkeleton({ text }: { text: string }): React.JSX.Element {
  return (
    <div
      className="screen-in"
      data-testid="frame-skeleton"
      aria-busy="true"
      style={{ ...FILL, background: 'var(--sur2)', color: 'var(--mut)', fontSize: 12.5 }}
    >
      <Spinner size={16} />
      <span>{text}</span>
    </div>
  )
}

export type FrameCardTone = 'error' | 'blocked' | 'disabled'

export interface FrameCardProps {
  readonly tone: FrameCardTone
  readonly title: string
  readonly detail?: string
  /** Dev registrations see the request that failed (wireflow §2). */
  readonly requestPath?: string
  readonly onRetry?: () => void
  readonly retryLabel?: string
  readonly actions?: ReactNode
}

const TONE_LABEL: Readonly<Record<FrameCardTone, string>> = {
  error: 'ERROR',
  blocked: 'BLOCKED',
  disabled: 'DISABLED'
}

export function FrameCard({
  tone,
  title,
  detail,
  requestPath,
  onRetry,
  retryLabel = 'Retry',
  actions
}: FrameCardProps): React.JSX.Element {
  return (
    <div className="screen-in" role="alert" data-testid={`frame-${tone}`} style={FILL}>
      <Mono size={9.5} color={tone === 'error' ? 'var(--err)' : 'var(--warn)'}>
        {TONE_LABEL[tone]}
      </Mono>
      <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
      {detail && <div style={{ fontSize: 12.5, color: 'var(--mut)', maxWidth: 420 }}>{detail}</div>}
      {requestPath && (
        <Mono size={9.5} style={{ textTransform: 'none', wordBreak: 'break-all' }}>
          {requestPath}
        </Mono>
      )}
      {(onRetry || actions) && (
        <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
          {onRetry && (
            <Button size="sm" kind="soft" onClick={onRetry}>
              {retryLabel}
            </Button>
          )}
          {actions}
        </div>
      )}
    </div>
  )
}
