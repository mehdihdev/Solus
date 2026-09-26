export interface DisplayPose {
  translation: number[]
  rotation: number[]
}
export const ZERO_POSE: DisplayPose = { translation: [0, 0, 0], rotation: [0, 0, 0] }
export function poseKey(user: string | null, project: string, model: string): string | null {
  return user ? `solus.scene.pose.v1:${JSON.stringify([user, project, model])}` : null
}
function valid(value: unknown): value is DisplayPose {
  if (typeof value !== 'object' || value === null) return false
  return ['translation', 'rotation'].every((key) => {
    const values = (value as Record<string, unknown>)[key]
    return (
      Array.isArray(values) &&
      values.length === 3 &&
      values.every(
        (n: unknown) => typeof n === 'number' && Number.isFinite(n) && Math.abs(n) <= 10000
      )
    )
  })
}
export function loadPose(key: string | null): DisplayPose {
  try {
    const raw = key ? localStorage.getItem(key) : null
    if (!raw || raw.length > 2048) return ZERO_POSE
    const value: unknown = JSON.parse(raw)
    return valid(value) ? value : ZERO_POSE
  } catch {
    return ZERO_POSE
  }
}
export function savePose(key: string | null, pose: DisplayPose): boolean {
  if (!key || !valid(pose)) return false
  try {
    localStorage.setItem(key, JSON.stringify(pose))
    return true
  } catch {
    return false
  }
}
