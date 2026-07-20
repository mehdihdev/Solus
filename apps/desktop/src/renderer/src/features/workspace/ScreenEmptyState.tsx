// Honest empty state for workspace screens whose live surfaces are future
// tickets (SOLUSDEV-152): says what the screen WILL show and what action
// populates it. Production builds render these until real data flows —
// never placeholder robot data.
import { Mono } from '../../components/ui/Mono'

export interface ScreenEmptyStateProps {
  /** Muted leading glyph (an Icons.* element or the SolOrb). */
  icon?: React.ReactNode
  title: string
  body: React.ReactNode
  /** Small mono status line under the body, e.g. "NO DEVICE CONNECTED". */
  status?: string
  /** Optional actions rendered below the copy. */
  children?: React.ReactNode
}

export function ScreenEmptyState({
  icon,
  title,
  body,
  status,
  children
}: ScreenEmptyStateProps): React.JSX.Element {
  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        padding: '48px 24px',
        textAlign: 'center'
      }}
    >
      {icon && <span style={{ color: 'var(--mut)', opacity: 0.7 }}>{icon}</span>}
      <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--tx)' }}>{title}</div>
      <div style={{ fontSize: 12.5, color: 'var(--mut)', maxWidth: 440, lineHeight: 1.65 }}>
        {body}
      </div>
      {status && (
        <Mono size={9.5} color="var(--mut)" style={{ letterSpacing: '0.08em' }}>
          {status}
        </Mono>
      )}
      {children}
    </div>
  )
}
