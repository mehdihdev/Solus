import type { BenchSignalPoint } from '../../lib/api/resources'

const FAMILIES: readonly (readonly string[])[] = [
  ['rad', 'deg'],
  ['rad/s', 'deg/s'],
  ['m', 'cm', 'mm'],
  ['A', 'mA'],
  ['V', 'mV']
]
const SCALE: Readonly<Record<string, number>> = {
  rad: 1,
  deg: Math.PI / 180,
  'rad/s': 1,
  'deg/s': Math.PI / 180,
  m: 1,
  cm: 0.01,
  mm: 0.001,
  A: 1,
  mA: 0.001,
  V: 1,
  mV: 0.001
}

export function unitOptions(unit: string | null): readonly string[] {
  return unit === null ? [] : (FAMILIES.find((family) => family.includes(unit)) ?? [unit])
}

export function convertUnit(
  value: number,
  source: string | null,
  target: string | null
): number | null {
  if (!Number.isFinite(value)) return null
  if (source === target) return value
  if (source === null || target === null || !unitOptions(source).includes(target)) return null
  const converted = (value * SCALE[source]) / SCALE[target]
  return Number.isFinite(converted) ? converted : null
}

export function displayPoints(
  points: readonly BenchSignalPoint[],
  unit: string | null
): BenchSignalPoint[] {
  return points.flatMap((point) => {
    const value = convertUnit(point.value, point.unit ?? null, unit)
    return value === null ? [] : [{ ...point, value, unit }]
  })
}

/** Never connect a line across a sample whose units cannot be compared. */
export function displayGroups(
  points: readonly BenchSignalPoint[],
  unit: string | null
): BenchSignalPoint[][] {
  const groups: BenchSignalPoint[][] = [[]]
  for (const point of points) {
    const converted = displayPoints([point], unit)
    if (converted.length === 0) groups.push([])
    else groups[groups.length - 1].push(converted[0])
  }
  return groups.filter((group) => group.length > 0)
}

/** Smallest vertical span a sparkline shows, per unit: a held joint wobbles a few ticks, and
 *  autoscaling that to full height reads as wild oscillation. Unknown units keep their range. */
const MIN_CHART_SPAN: Readonly<Record<string, number>> = {
  deg: 10,
  rad: 10 * (Math.PI / 180),
  '%': 10,
  tick: 100,
  mm: 5,
  cm: 0.5,
  m: 0.005
}

/** Decimals shown per unit, about one encoder step (0.088 deg on a 4096-tick servo): finer
 *  digits are quantization noise that churns on every sample. Unknown units keep 6 sig. digits. */
const DISPLAY_DECIMALS: Readonly<Record<string, number>> = {
  deg: 1,
  rad: 3,
  '%': 1,
  tick: 0,
  mm: 1,
  cm: 2,
  m: 3
}

export function formatValue(value: number, unit: string | null): string {
  const decimals = unit === null ? undefined : DISPLAY_DECIMALS[unit]
  return decimals === undefined ? String(Number(value.toPrecision(6))) : value.toFixed(decimals)
}

export function valueDomain(
  values: readonly number[],
  unit: string | null
): { vMin: number; vMax: number } {
  const vMin = Math.min(...values)
  const vMax = Math.max(...values)
  const floor = unit === null ? 0 : (MIN_CHART_SPAN[unit] ?? 0)
  if (vMax - vMin >= floor) return { vMin, vMax }
  const mid = (vMin + vMax) / 2
  return { vMin: mid - floor / 2, vMax: mid + floor / 2 }
}

/** The team's display unit (bench view) when the packet unit converts to it; else the packet unit. */
export function sharedUnit(packetUnit: string | null, teamUnit: string | null): string | null {
  return teamUnit !== null && unitOptions(packetUnit).includes(teamUnit) ? teamUnit : packetUnit
}

/** A fixed y-axis range from the shared view wins over autoscale (display only). */
export function limitedDomain(
  values: readonly number[],
  unit: string | null,
  limits: { min: number; max: number } | null
): { vMin: number; vMax: number } {
  return limits ? { vMin: limits.min, vMax: limits.max } : valueDomain(values, unit)
}
