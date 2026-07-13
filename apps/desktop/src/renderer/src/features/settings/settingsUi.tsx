// Shared presentational primitives for the Settings surfaces (SOLUSDEV-86).
// A `Section` is a titled Card; a `Row` is a label/control pair; `InlineError`
// renders an accessible, envelope-sourced error under a form.
import type { ReactNode } from 'react'
import { Card } from '../../components/ui/Card'

export interface SectionProps {
  title: string
  sub?: string
  children: ReactNode
}

export function Section({ title, sub, children }: SectionProps): React.JSX.Element {
  return (
    <Card pad={20} style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
      {sub && (
        <div style={{ fontSize: 11.5, color: 'var(--mut)', marginTop: 3, lineHeight: 1.5 }}>
          {sub}
        </div>
      )}
      <div style={{ marginTop: 14 }}>{children}</div>
    </Card>
  )
}

export interface RowProps {
  label: ReactNode
  children: ReactNode
}

export function Row({ label, children }: RowProps): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 16,
        padding: '9px 0',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <span style={{ fontSize: 12.5 }}>{label}</span>
      <div>{children}</div>
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
