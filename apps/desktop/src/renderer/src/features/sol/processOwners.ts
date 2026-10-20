// SOLUSDEV-317 §11.3: which conversation started which process, and which
// prompts already woke SOL. Renderer runtime only — never persisted, cleared on
// any identity change. Bounded: the server keeps at most 16 process entries.
export const MAX_PROCESS_OWNERS = 64
/** Woken (process_id, prompt_seq) keys kept before the oldest are forgotten. */
const MAX_WOKEN = 256

export interface ProcessOwner {
  readonly projectId: string
  readonly conversationId: string
}

const owners = new Map<string, ProcessOwner>()
const woken = new Set<string>()

const wakeKey = (processId: string, promptSeq: number): string => `${processId}:${promptSeq}`

/** Drop the oldest entries (insertion order) beyond `max`. */
function trim(
  keys: Iterable<string>,
  size: number,
  max: number,
  drop: (key: string) => void
): void {
  let excess = size - max
  for (const key of keys) {
    if (excess <= 0) return
    drop(key)
    excess -= 1
  }
}

/** The `process_id` a `code.process_start` result carries, or null. */
export function processIdOf(
  value: Readonly<Record<string, unknown>> | null | undefined
): string | null {
  const id = value?.process_id
  return typeof id === 'string' && id !== '' ? id : null
}

export function rememberProcessOwner(
  projectId: string,
  processId: string,
  conversationId: string
): void {
  owners.delete(processId)
  owners.set(processId, { projectId, conversationId })
  trim(owners.keys(), owners.size, MAX_PROCESS_OWNERS, (key) => owners.delete(key))
}

export function processOwner(processId: string): ProcessOwner | null {
  return owners.get(processId) ?? null
}

export function hasWoken(processId: string, promptSeq: number): boolean {
  return woken.has(wakeKey(processId, promptSeq))
}

export function markWoken(processId: string, promptSeq: number): void {
  woken.add(wakeKey(processId, promptSeq))
  trim(woken.values(), woken.size, MAX_WOKEN, (key) => woken.delete(key))
}

export function resetProcessOwners(): void {
  owners.clear()
  woken.clear()
}
