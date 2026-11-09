// Stroke icons the onboarding cards need that the shared set lacks
// (SOLUSDEV-323). Decorative: always aria-hidden, text carries the meaning.
const STROKE = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true
} as const

export function GraphGlyph(): React.JSX.Element {
  return (
    <svg {...STROKE}>
      <circle cx="5" cy="6" r="2.2" />
      <circle cx="19" cy="6" r="2.2" />
      <circle cx="12" cy="18" r="2.2" />
      <path d="M7 7l4 9M17 7l-4 9M7.2 6h9.6" />
    </svg>
  )
}

export function EyeGlyph(): React.JSX.Element {
  return (
    <svg {...STROKE}>
      <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

export function PointerGlyph(): React.JSX.Element {
  return (
    <svg {...STROKE}>
      <path d="M5 3l12 8-5.5 1.2L9 18z" />
      <path d="M14 14l5 5" />
    </svg>
  )
}

export function KeyboardGlyph(): React.JSX.Element {
  return (
    <svg {...STROKE}>
      <rect x="3" y="7" width="18" height="11" rx="2" />
      <path d="M7 11h.01M11 11h.01M15 11h.01M8 15h8" />
    </svg>
  )
}

export function GlyphTile({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <span
      style={{
        width: 36,
        height: 36,
        flex: 'none',
        borderRadius: 6,
        background: 'var(--sur2)',
        border: '1px solid var(--bd)',
        color: 'var(--acc)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center'
      }}
    >
      {children}
    </span>
  )
}
