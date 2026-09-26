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
