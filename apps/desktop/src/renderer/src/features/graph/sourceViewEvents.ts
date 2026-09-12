import { useEffect, useState } from 'react'

export const SOURCE_VIEW_STORAGE_KEY = 'solus-source-view-change'
const EVENT = 'solus:source-view-change'

/** No branch choices or account data are stored here; this is only a refresh signal. */
export function notifySourceViewChanged(projectId: string): void {
  window.dispatchEvent(new CustomEvent(EVENT, { detail: projectId }))
  try {
    localStorage.setItem(
      SOURCE_VIEW_STORAGE_KEY,
      JSON.stringify({ projectId, nonce: crypto.randomUUID() })
    )
  } catch {
    // The current window still refreshes when local storage is unavailable.
  }
}

export function useSourceViewVersion(projectId: string | null): number {
  const [version, setVersion] = useState(0)
  useEffect(() => {
    const refresh = (candidate: unknown): void => {
      if (projectId && candidate === projectId) setVersion((current) => current + 1)
    }
    const onChanged = (event: Event): void => {
      refresh((event as CustomEvent<unknown>).detail)
    }
    const onStorage = (event: StorageEvent): void => {
      if (
        event.storageArea !== localStorage ||
        event.key !== SOURCE_VIEW_STORAGE_KEY ||
        !event.newValue
      )
        return
      try {
        const value: unknown = JSON.parse(event.newValue)
        if (value && typeof value === 'object' && 'projectId' in value) refresh(value.projectId)
      } catch {
        /* Ignore malformed refresh signals. */
      }
    }
    window.addEventListener(EVENT, onChanged)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(EVENT, onChanged)
      window.removeEventListener('storage', onStorage)
    }
  }, [projectId])
  return version
}
