// Button primitive, ported from Btn in TestDesign/app/util.jsx.
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from 'react'

export type ButtonKind = 'primary' | 'ghost' | 'soft' | 'danger' | 'bare'
export type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  kind?: ButtonKind
  size?: ButtonSize
  children: ReactNode
}

const SIZE_STYLE: Record<ButtonSize, CSSProperties> = {
  sm: { fontSize: 12, padding: '6px 12px' },
  md: { fontSize: 13, padding: '8px 15px' },
  lg: { fontSize: 14.5, padding: '12px 22px' }
}

const KIND_STYLE: Record<ButtonKind, CSSProperties> = {
  primary: { background: 'var(--acc)', color: 'var(--acc-ink)', border: '1px solid transparent' },
  ghost: { background: 'transparent', color: 'var(--tx)', border: '1px solid var(--bd)' },
  soft: { background: 'var(--sur2)', color: 'var(--tx)', border: '1px solid var(--bd)' },
  danger: { background: 'transparent', color: 'var(--err)', border: '1px solid var(--err)' },
  bare: { background: 'transparent', color: 'var(--mut)', border: '1px solid transparent' }
}

export function Button({
  kind = 'ghost',
  size = 'md',
  disabled = false,
  style,
  children,
  type = 'button',
  ...rest
}: ButtonProps): React.JSX.Element {
  const base: CSSProperties = {
    fontFamily: 'var(--font-ui)',
    fontWeight: kind === 'primary' ? 600 : 500,
    borderRadius: 3,
    cursor: disabled ? 'default' : 'pointer',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 7,
    justifyContent: 'center',
    transition: 'background 0.12s, border-color 0.12s, opacity 0.12s',
    opacity: disabled ? 0.45 : 1,
    whiteSpace: 'nowrap',
    ...SIZE_STYLE[size],
    ...KIND_STYLE[kind],
    ...style
  }
  return (
    <button type={type} disabled={disabled} style={base} {...rest}>
      {children}
    </button>
  )
}
