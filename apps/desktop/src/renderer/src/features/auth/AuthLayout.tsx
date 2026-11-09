// Auth form card (SOLUSDEV-323): the content of a compact signed-out screen.
// AuthShell owns the window chrome and SOL's orb; this is the caption, the
// title, the form and its footer, with Back to the starter.
import type { CSSProperties, ReactNode } from 'react'
import { Button } from '../../components/ui/Button'
import { Mono } from '../../components/ui/Mono'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'

interface AuthCardProps {
  /** SOL's mono caption above the title, e.g. `SOL · WELCOME BACK`. */
  caption?: string
  title: string
  sub: string
  children: ReactNode
  footer: ReactNode
  onBack?: () => void
}

export function AuthCard({
  caption = 'SOL',
  title,
  sub,
  children,
  footer,
  onBack
}: AuthCardProps): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {onBack && (
        <button
          type="button"
          aria-label="Back"
          onClick={onBack}
          className="interactive"
          style={{
            alignSelf: 'flex-start',
            marginBottom: 14,
            background: 'none',
            border: 'none',
            padding: 0,
            fontSize: 12.5,
            color: 'var(--mut)',
            cursor: 'pointer'
          }}
        >
          ← Back
        </button>
      )}
      <div style={{ textAlign: 'center', marginBottom: 22 }}>
        <Mono size={9.5} color="var(--acc)">
          {caption}
        </Mono>
        <h1 style={{ margin: '8px 0 0', fontSize: 22, fontWeight: 600, letterSpacing: '-0.02em' }}>
          {title}
        </h1>
        <div style={{ fontSize: 13, color: 'var(--mut)', marginTop: 6, lineHeight: 1.55 }}>
          {sub}
        </div>
      </div>
      {children}
      <div style={{ textAlign: 'center', marginTop: 18, fontSize: 12.5, color: 'var(--mut)' }}>
        {footer}
      </div>
    </div>
  )
}

interface AuthFooterLinkProps {
  prompt: string
  action: string
  onClick: () => void
}

/** Footer prompt with an inline keyboard-accessible link, shared by the auth screens. */
export function AuthFooterLink({
  prompt,
  action,
  onClick
}: AuthFooterLinkProps): React.JSX.Element {
  return (
    <span>
      {prompt}{' '}
      <span
        role="link"
        tabIndex={0}
        onClick={onClick}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onClick()
        }}
        style={{ color: 'var(--acc)', cursor: 'pointer' }}
      >
        {action}
      </span>
    </span>
  )
}

interface BusySubmitProps {
  busy: boolean
  label: string
  busyLabel: string
  onClick: () => void
  style?: CSSProperties
}

/** Full-width primary submit that shows a spinner + busy label while working. */
export function BusySubmit({
  busy,
  label,
  busyLabel,
  onClick,
  style
}: BusySubmitProps): React.JSX.Element {
  return (
    <Button
      kind="primary"
      onClick={onClick}
      disabled={busy}
      style={{ width: '100%', padding: '11px 0', ...style }}
    >
      {busy ? (
        <>
          <Spinner color="var(--acc-ink)" /> {busyLabel}
        </>
      ) : (
        label
      )}
    </Button>
  )
}

/** Green inline confirmation row with a check icon (e.g. "magic link sent"). */
export function InlineSuccess({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <div
      style={{
        fontSize: 12,
        color: 'var(--ok)',
        marginTop: 12,
        display: 'flex',
        gap: 7,
        alignItems: 'center',
        justifyContent: 'center'
      }}
    >
      <Icons.check size={14} /> {children}
    </div>
  )
}

/** "OR" divider used between OAuth and email/password. */
export function OrDivider(): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '18px 0' }}>
      <div style={{ flex: 1, height: 1, background: 'var(--bd)' }} />
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          letterSpacing: '0.1em',
          color: 'var(--mut)'
        }}
      >
        OR
      </span>
      <div style={{ flex: 1, height: 1, background: 'var(--bd)' }} />
    </div>
  )
}
