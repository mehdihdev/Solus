// Runtime guards shared by the live-stream decoders (ADR-037). Every frame
// crosses a process boundary, so a frame is accepted only when its key set is
// EXACTLY the contract's and every field passes its check — extra content is
// dropped, never trusted.
export type Check = (value: unknown) => boolean

/** One check per contract field; the mapped type makes a missing field a compile error. */
export type Shape<T> = { [K in keyof T]-?: Check }

export const isString: Check = (value) => typeof value === 'string'
export const isNullableString: Check = (value) => value === null || typeof value === 'string'
export const isNonNegativeInt: Check = (value) => Number.isInteger(value) && (value as number) >= 0
export const isStringArray: Check = (value) => Array.isArray(value) && value.every(isString)
export const literal =
  (expected: string): Check =>
  (value) =>
    value === expected

export function hasExactKeys(data: Record<string, unknown>, keys: readonly string[]): boolean {
  const own = Object.keys(data)
  return own.length === keys.length && keys.every((key) => key in data)
}

/** True when `data` has exactly the shape's keys and each value passes its check. */
export function matchesShape(data: Record<string, unknown>, shape: Record<string, Check>): boolean {
  return (
    hasExactKeys(data, Object.keys(shape)) && Object.entries(shape).every(([k, c]) => c(data[k]))
  )
}
