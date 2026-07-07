// Sparkline, ported from Spark in TestDesign/app/util.jsx: values normalized
// to their own (or a supplied) range, optional soft area fill.
interface SparkProps {
  values: readonly number[]
  w?: number
  h?: number
  color?: string
  fill?: boolean
  yMin?: number
  yMax?: number
}

/** Normalize the series into svg polyline points. Pure. */
function sparkPoints(
  values: readonly number[],
  w: number,
  h: number,
  yMin: number | undefined,
  yMax: number | undefined
): string[] {
  const mn = yMin ?? Math.min(...values)
  const mx = yMax ?? Math.max(...values)
  const rg = mx - mn || 1
  return values.map(
    (v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - mn) / rg) * (h - 4)}`
  )
}

export function Spark({
  values,
  w = 120,
  h = 30,
  color = 'var(--acc)',
  fill = true,
  yMin,
  yMax
}: SparkProps): React.JSX.Element {
  if (!values || values.length < 2) return <svg width={w} height={h} />
  const pts = sparkPoints(values, w, h, yMin, yMax)
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      {fill && <polygon points={`0,${h} ${pts.join(' ')} ${w},${h}`} fill={color} opacity="0.10" />}
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  )
}
