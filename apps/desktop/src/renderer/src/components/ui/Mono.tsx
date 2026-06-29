// Uppercase monospace label, ported from Mono in TestDesign/app/util.jsx.
import type { CSSProperties, ReactNode } from 'react'

interface MonoProps {
  children: ReactNode
  size?: number
  color?: string
  ls?: string
  style?: CSSProperties
  className?: string
}

export function Mono({
  children,
  size = 10,
  color = 'var(--mut)',
  ls = '0.1em',
  style,
  className
}: MonoProps): React.JSX.Element {
  return (
    <span
      className={className}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: size,
        letterSpacing: ls,
        color,
        textTransform: 'uppercase',
        ...style
      }}
    >
      {children}
    </span>
  )
}
