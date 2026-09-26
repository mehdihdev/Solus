export type Point = [number, number, number]
export const MAX_SENSOR_BYTES = 8 * 1024 * 1024
export function parsePointCloud(text: string): Point[] {
  if (text.length > MAX_SENSOR_BYTES) throw new Error('Point cloud exceeds bound')
  const value: unknown = JSON.parse(text)
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid cloud')
  const row = value as Record<string, unknown>
  if (
    Object.keys(row).sort().join(',') !== 'points,schema_version,unit' ||
    row.schema_version !== 1 ||
    row.unit !== 'm' ||
    !Array.isArray(row.points) ||
    row.points.length > 10000
  )
    throw new Error('Unsupported cloud')
  return row.points.map((point: unknown) => {
    if (
      !Array.isArray(point) ||
      point.length !== 3 ||
      !point.every(
        (n: unknown) => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 1e6
      )
    )
      throw new Error('Invalid point')
    return point as Point
  })
}
