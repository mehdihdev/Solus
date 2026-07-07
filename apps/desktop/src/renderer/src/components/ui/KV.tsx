// Key/value row for property lists, ported from KV in TestDesign/app/util.jsx.
interface KVProps {
  k: string
  v: string
  vColor?: string
}

export function KV({ k, v, vColor }: KVProps): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: 12,
        padding: '6px 0',
        borderBottom: '1px solid var(--bd)'
      }}
    >
      <span style={{ fontSize: 11.5, color: 'var(--mut)', flexShrink: 0 }}>{k}</span>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: vColor ?? 'var(--tx)',
          textAlign: 'right',
          whiteSpace: 'nowrap'
        }}
      >
        {v}
      </span>
    </div>
  )
}
