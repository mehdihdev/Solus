import { useSyncExternalStore } from 'react'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

// Equality cannot detect A → B → A while an operation awaits a response.
// Every intervening account/project boundary permanently expires old work.
let generation = 0
const listeners = new Set<() => void>()
function expire(): void {
  generation += 1
  listeners.forEach((listener) => listener())
}
useAuthStore.subscribe((next, previous) => {
  if (next.status !== previous.status || next.user?.email !== previous.user?.email) expire()
})
useWorkspaceStore.subscribe((next, previous) => {
  if (next.project?.id !== previous.project?.id) expire()
})
export const workspaceSessionGeneration = (): number => generation
function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
export function useWorkspaceSessionGeneration(): number {
  return useSyncExternalStore(subscribe, workspaceSessionGeneration)
}
