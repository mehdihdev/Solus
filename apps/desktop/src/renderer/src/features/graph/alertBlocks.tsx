// Presentational blocks for the alert detail screen, ported pixel-faithfully
// from SevBadge, CodeBlock, and BeforeAfter in TestDesign/app/alert.jsx.
// The prototype's dual-mode CodeBlock is split into CodeBlock (plain source
// with hot-line highlights) and DiffBlock (unified diff) for type safety.
import type { CSSProperties } from 'react'
import { Mono } from '../../components/ui/Mono'
import { Icons } from '../../components/ui/icons.constants'
import type {
  Alert,
  AlertSeverity,
  AlertState,
  DiffLine
} from '../workspace/workspaceData.constants'

interface SevBadgeProps {
  sev: AlertSeverity
  state: AlertState
}

export function SevBadge({ sev, state }: SevBadgeProps): React.JSX.Element {
  const c = state === 'resolved' ? 'var(--ok)' : sev === 'critical' ? 'var(--err)' : 'var(--warn)'
  const label = state === 'resolved' ? 'RESOLVED' : sev.toUpperCase()
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 9.5,
        letterSpacing: '0.1em',
        color: c,
        border: `1px solid color-mix(in srgb, ${c} 45%, transparent)`,
        background: `color-mix(in srgb, ${c} 9%, transparent)`,
        borderRadius: 99,
        padding: '4px 10px'
      }}
    >
      {label}
    </span>
  )
}

const CODE_WRAP: CSSProperties = {
  background: 'var(--bg)',
  border: '1px solid var(--bd)',
  borderRadius: 3,
  overflow: 'hidden',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  lineHeight: 1.75
}

interface CodeBlockProps {
  lines: readonly string[]
  hot?: readonly number[]
}

export function CodeBlock({ lines, hot }: CodeBlockProps): React.JSX.Element {
  return (
    <div style={CODE_WRAP}>
      {lines.map((s, i) => {
        const isHot = hot?.includes(i) ?? false
        return (
          <div
            key={i}
            style={{
              padding: '0 12px',
              whiteSpace: 'pre',
              background: isHot
                ? 'color-mix(in srgb, var(--warn) 10%, transparent)'
                : 'transparent',
              color: isHot ? 'var(--tx)' : 'var(--mut)',
              borderLeft: isHot ? '2px solid var(--warn)' : '2px solid transparent'
            }}
          >
            {s || ' '}
          </div>
        )
      })}
    </div>
  )
}

function diffBackground(t: DiffLine['t']): string {
  if (t === 'del') return 'color-mix(in srgb, var(--err) 11%, transparent)'
  if (t === 'add') return 'color-mix(in srgb, var(--ok) 11%, transparent)'
  return 'transparent'
}

function diffColor(t: DiffLine['t']): string {
  if (t === 'del') return 'color-mix(in srgb, var(--err) 70%, var(--tx))'
  if (t === 'add') return 'color-mix(in srgb, var(--ok) 70%, var(--tx))'
  return 'var(--mut)'
}

function diffSign(t: DiffLine['t']): string {
  if (t === 'del') return '−'
  if (t === 'add') return '+'
  return ' '
}

interface DiffBlockProps {
  lines: readonly DiffLine[]
}

export function DiffBlock({ lines }: DiffBlockProps): React.JSX.Element {
  return (
    <div style={CODE_WRAP}>
      {lines.map((d, i) => (
        <div
          key={i}
          style={{
            padding: '0 12px',
            whiteSpace: 'pre',
            background: diffBackground(d.t),
            color: diffColor(d.t)
          }}
        >
          <span style={{ display: 'inline-block', width: 14, opacity: 0.7 }}>{diffSign(d.t)}</span>
          {d.s}
        </div>
      ))}
    </div>
  )
}

interface BeforeAfterProps {
  change: Alert['change']
}

function RevColumn({
  title,
  rows,
  accent
}: {
  title: string
  rows: readonly (readonly [string, string])[]
  accent: boolean
}): React.JSX.Element {
  return (
    <div style={{ flex: 1 }}>
      <Mono size={9} color={accent ? 'var(--acc)' : 'var(--mut)'}>
        {title}
      </Mono>
      <div style={{ marginTop: 8 }}>
        {rows.map(([k, v]) => (
          <div
            key={k}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              gap: 8,
              padding: '5px 0',
              borderBottom: '1px solid var(--bd)'
            }}
          >
            <span style={{ fontSize: 11, color: 'var(--mut)' }}>{k}</span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10.5,
                color: accent ? 'var(--tx)' : 'var(--mut)',
                textAlign: 'right'
              }}
            >
              {v}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function BeforeAfter({ change }: BeforeAfterProps): React.JSX.Element {
  return (
    <div style={{ display: 'flex', gap: 18, alignItems: 'stretch' }}>
      <RevColumn title="BEFORE · REV 41" rows={change.before} accent={false} />
      <div style={{ display: 'flex', alignItems: 'center', color: 'var(--acc)' }}>
        <Icons.arrowR size={16} />
      </div>
      <RevColumn title="AFTER · REV 42" rows={change.after} accent={true} />
    </div>
  )
}
