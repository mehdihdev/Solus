// Auth doorway chrome, ported from AuthChrome + AuthCard in TestDesign/app/auth.jsx.
import type { CSSProperties, ReactNode } from 'react'
import { Card } from '../../components/ui/Card'
import { Wordmark } from '../../components/ui/Wordmark'
import { Button } from '../../components/ui/Button'
import { Spinner } from '../../components/ui/Spinner'
import { Icons } from '../../components/ui/icons.constants'

const APP_VERSION = 'v0.9'

export function AuthChrome({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'var(--bg)',
        color: 'var(--tx)',
        fontFamily: 'var(--font-ui)',
        display: 'flex',
        flexDirection: 'column'
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9.5,
          letterSpacing: '0.14em',
          color: 'var(--mut)',
          borderBottom: '1px solid var(--bd)',
          padding: '7px 28px',
          display: 'flex',
          justifyContent: 'space-between'
        }}
      >
        <span>SOLUS // CROSS-DOMAIN INTEGRITY FOR ROBOTICS TEAMS</span>
        <span>{APP_VERSION}</span>
      </div>
      {children}
    </div>
  )
}

interface AuthCardProps {
  title: string
  sub: string
  children: ReactNode
  footer: ReactNode
  onWordmarkClick?: () => void
}

export function AuthCard({
  title,
  sub,
  children,
  footer,
  onWordmarkClick
}: AuthCardProps): React.JSX.Element {
  return (
    <AuthChrome>
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24
        }}
      >
        <div style={{ width: 380 }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 28 }}>
            <Wordmark onClick={onWordmarkClick} />
          </div>
          <Card pad={28}>
            <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>{title}</div>
            <div
              style={{
                fontSize: 12.5,
                color: 'var(--mut)',
                marginTop: 4,
                marginBottom: 22,
                lineHeight: 1.5
              }}
            >
              {sub}
            </div>
            {children}
          </Card>
          <div style={{ textAlign: 'center', marginTop: 16, fontSize: 12.5, color: 'var(--mut)' }}>
            {footer}
          </div>
        </div>
      </div>
    </AuthChrome>
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
