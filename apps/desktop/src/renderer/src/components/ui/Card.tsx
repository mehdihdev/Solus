// Surface card, ported from Card in TestDesign/app/util.jsx.
import type { CSSProperties, ReactNode } from 'react'

interface CardProps {
  children?: ReactNode
  pad?: number
  style?: CSSProperties
  className?: string
  onClick?: () => void
  id?: string
}

export function Card({
  children,
  pad = 16,
  style,
  className,
  onClick,
  id
}: CardProps): React.JSX.Element {
  return (
    <div
      id={id}
      className={className}
      onClick={onClick}
      style={{
        background: 'var(--sur)',
        border: '1px solid var(--bd)',
        borderRadius: 4,
        padding: pad,
        boxSizing: 'border-box',
        ...style
      }}
    >
      {children}
    </div>
  )
}
