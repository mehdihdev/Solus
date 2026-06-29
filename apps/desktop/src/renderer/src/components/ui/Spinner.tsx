// Loading spinner, ported from Spinner in TestDesign/app/util.jsx.
interface SpinnerProps {
  size?: number
  color?: string
  className?: string
}

export function Spinner({ size = 14, color = 'var(--acc)' }: SpinnerProps): React.JSX.Element {
  return (
    <span
      className="sol-spin"
      role="status"
      aria-label="Loading"
      style={{
        width: size,
        height: size,
        border: '1.6px solid var(--bd)',
        borderTopColor: color,
        borderRadius: 99,
        display: 'inline-block',
        flexShrink: 0
      }}
    />
  )
}
