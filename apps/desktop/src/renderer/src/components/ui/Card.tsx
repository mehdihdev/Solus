// Surface card, ported from Card in TestDesign/app/util.jsx.
import type { HTMLAttributes } from 'react'

/** Any div attribute passes through (role, tabIndex, aria-*, key handlers), so a
 *  card can be a real button for assistive tech without a wrapper (SOLUSDEV-235).
 *  `dangerouslySetInnerHTML` is excluded on purpose: a surface primitive must
 *  never become an HTML sink for whatever a caller hands it (CLAUDE.md §7). */
interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'dangerouslySetInnerHTML'> {
  pad?: number
}

export function Card({
  children,
  pad = 16,
  style,
  className,
  onClick,
  id,
  ...rest
}: CardProps): React.JSX.Element {
  // Belt and braces for untyped call sites: drop the sink even if it slipped past the types.
  const { dangerouslySetInnerHTML: _dropped, ...safeRest } = rest as CardProps & {
    dangerouslySetInnerHTML?: unknown
  }
  void _dropped
  // A card with a click handler reads as clickable (hover tint + pointer).
  const classes = [className, onClick ? 'interactive' : null].filter(Boolean).join(' ')
  return (
    <div
      {...safeRest}
      id={id}
      className={classes || undefined}
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
