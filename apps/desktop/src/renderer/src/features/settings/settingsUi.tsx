// Shared presentational primitives for the Settings surfaces (SOLUSDEV-86,
// restyled for design A in SOLUSDEV-318). A `Section` is a titled Card the
// sidebar scrolls to; a `Row` is a label (+ description) / control pair; a
// `Callout` is an action card for something the user must do; `InlineError`
// renders an accessible, envelope-sourced error under a form.
import { useId, type ReactNode } from 'react'
import { Card } from '../../components/ui/Card'
import { Icons } from '../../components/ui/icons.constants'
import { sectionAnchor, type SectionId } from './settingsSections.constants'

export interface SectionProps {
  title: string
  sub?: string
  /** Sidebar anchor; omitted for a section that is never a nav target. */
  id?: SectionId
  /** A control on the title line (e.g. "Open Billing →"). */
  action?: ReactNode
  children: ReactNode
}

export function Section({ title, sub, id, action, children }: SectionProps): React.JSX.Element {
  const titleId = useId()
  return (
    <section
      id={id ? sectionAnchor(id) : undefined}
      aria-labelledby={titleId}
      style={{ scrollMarginTop: 16 }}
    >
      <Card pad={20}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 id={titleId} style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
              {title}
            </h2>
            {sub && (
              <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 3, lineHeight: 1.5 }}>
                {sub}
              </div>
            )}
          </div>
          {action}
        </div>
        <div style={{ marginTop: 12 }}>{children}</div>
      </Card>
    </section>
  )
}

export interface RowProps {
  label: ReactNode
  /** Help text under the label — never a full-width line under the control. */
  description?: ReactNode
  children: ReactNode
}

export function Row({ label, description, children }: RowProps): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 24,
        padding: '11px 0',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      {description ? (
        <div style={{ minWidth: 0, maxWidth: 480 }}>
          <div style={{ fontSize: 12.5, fontWeight: 500 }}>{label}</div>
          <div style={{ fontSize: 11.5, color: 'var(--mut)', lineHeight: 1.5, marginTop: 2 }}>
            {description}
          </div>
        </div>
      ) : (
        // Flat label/value siblings, as Billing's CurrentPlanCard rows rely on.
        <span style={{ fontSize: 12.5 }}>{label}</span>
      )}
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  )
}

export type Tone = 'ok' | 'warn' | 'err' | 'acc' | 'mut'

const TONE_VAR: Record<Tone, string> = {
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  err: 'var(--err)',
  acc: 'var(--acc)',
  mut: 'var(--mut)'
}

export interface CalloutProps {
  tone: 'warn' | 'acc'
  title: string
  actions?: ReactNode
  children?: ReactNode
}

/** Something the user has to do, with the buttons that do it. */
export function Callout({ tone, title, actions, children }: CalloutProps): React.JSX.Element {
  const titleId = useId()
  const color = TONE_VAR[tone]
  const Icon = tone === 'warn' ? Icons.warn : Icons.bell
  return (
    <div
      role="group"
      aria-labelledby={titleId}
      style={{
        display: 'flex',
        gap: 12,
        padding: '14px 16px',
        borderRadius: 4,
        background: `color-mix(in srgb, ${color} 9%, var(--sur))`,
        border: `1px solid color-mix(in srgb, ${color} 45%, var(--bd))`
      }}
    >
      <span style={{ color, flexShrink: 0, marginTop: 1 }} aria-hidden="true">
        <Icon size={15} />
      </span>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div id={titleId} style={{ fontSize: 12.5, fontWeight: 600 }}>
          {title}
        </div>
        {children && (
          <div style={{ fontSize: 12, color: 'var(--mut)', lineHeight: 1.5 }}>{children}</div>
        )}
        {actions && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{actions}</div>}
      </div>
    </div>
  )
}

/** A key cap: `<Kbd>Ctrl</Kbd>`. */
export function Kbd({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <kbd
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 10.5,
        color: 'var(--tx)',
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        borderBottomWidth: 2,
        borderRadius: 3,
        padding: '0 5px'
      }}
    >
      {children}
    </kbd>
  )
}

/** A small mono status word beside a label or at the end of a row. */
export function StatusTag({
  tone,
  children
}: {
  tone: Tone
  children: ReactNode
}): React.JSX.Element {
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 9.5,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        color: TONE_VAR[tone]
      }}
    >
      {children}
    </span>
  )
}

/** A monospace path/command line the user may need to follow or copy. */
export function CodeLine({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <div
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--tx)',
        background: 'var(--bg)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        padding: '6px 10px',
        overflowX: 'auto',
        whiteSpace: 'nowrap'
      }}
    >
      {children}
    </div>
  )
}

/** Inline error line for a form/section — sourced from the API error envelope. */
export function InlineError({ message }: { message: string | null }): React.JSX.Element | null {
  if (!message) return null
  return (
    <div role="alert" style={{ marginTop: 8, fontSize: 11.5, color: 'var(--err)' }}>
      {message}
    </div>
  )
}
