// Segmented control, ported from Seg in TestDesign/app/util.jsx.
interface SegmentedProps<T extends string> {
  options: readonly T[]
  value: T
  onChange: (value: T) => void
  size?: 'sm' | 'md'
  ariaLabel?: string
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
  ariaLabel
}: SegmentedProps<T>): React.JSX.Element {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      style={{
        display: 'inline-flex',
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 3,
        overflow: 'hidden'
      }}
    >
      {options.map((o, i) => {
        const active = value === o
        return (
          <button
            key={o}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o)}
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: size === 'sm' ? 11 : 12.5,
              fontWeight: 500,
              padding: size === 'sm' ? '5px 11px' : '6px 14px',
              cursor: 'pointer',
              userSelect: 'none',
              background: active ? 'var(--sur2)' : 'transparent',
              color: active ? 'var(--tx)' : 'var(--mut)',
              border: 'none',
              borderRight: i < options.length - 1 ? '1px solid var(--bd)' : 'none',
              boxShadow: active ? 'inset 0 -2px 0 var(--acc)' : 'none'
            }}
          >
            {o}
          </button>
        )
      })}
    </div>
  )
}
