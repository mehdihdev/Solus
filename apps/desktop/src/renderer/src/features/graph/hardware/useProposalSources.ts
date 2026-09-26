import { useEffect, useSyncExternalStore } from 'react'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceSessionGeneration, workspaceSessionGeneration } from '../workspaceSession'

type Bridge = Window['solus']['hardware']['sources']
interface SourceState {
  key: string
  refs: string[] | null
  error: string | null
}
interface Entry {
  state: SourceState
  started: boolean
}
let revision = 0
const listeners = new Set<() => void>()
const entries = new Map<string, Entry>()
let cacheEpoch = ''
let cacheBridge: Bridge | undefined
const EMPTY: string[] = []
const UNAVAILABLE =
  'Local source review is unavailable. Refresh or relink your files in this account.'
function emit(): void {
  listeners.forEach((listener) => listener())
}
export function notifyProposalSourcesChanged(): void {
  revision += 1
  entries.clear()
  emit()
}
// Authentication invalidation must be shared too: a new hook cannot restart its
// own epoch at zero while an existing rail is already in a later account scope.
useAuthStore.subscribe((next, previous) => {
  if (
    next.accessToken !== previous.accessToken ||
    next.user !== previous.user ||
    next.status !== previous.status
  )
    notifyProposalSourcesChanged()
})
function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
function scope(projectId: string | null): string {
  return JSON.stringify([projectId, workspaceSessionGeneration(), revision])
}
function entryFor(projectId: string | null, bridge: Bridge | undefined): Entry {
  const epoch = `${workspaceSessionGeneration()}:${revision}`
  if (cacheEpoch !== epoch || cacheBridge !== bridge) {
    entries.clear()
    cacheEpoch = epoch
    cacheBridge = bridge
  }
  const key = scope(projectId)
  let entry = entries.get(key)
  if (!entry) {
    entry = {
      state: { key, refs: bridge && projectId ? null : EMPTY, error: null },
      started: false
    }
    entries.set(key, entry)
  }
  return entry
}
function load(entry: Entry, projectId: string, bridge: Bridge): void {
  if (entry.started) return
  entry.started = true
  const key = scope(projectId)
  const current = (): boolean =>
    key === scope(projectId) &&
    entries.get(key) === entry &&
    window.solus?.hardware?.sources === bridge
  const fail = (): void => {
    if (!current()) return
    entry.state = { key, refs: null, error: UNAVAILABLE }
    emit()
  }
  void Promise.resolve()
    .then(() => bridge.list())
    .then((result) => {
      if (!current()) return
      if (!result.ok || result.value.projectId !== projectId || result.value.sources.length > 32) {
        fail()
        return
      }
      const sources = [...result.value.sources].sort((a, b) =>
        a.sourceRef.localeCompare(b.sourceRef)
      )
      entry.state = {
        key: JSON.stringify([
          key,
          result.value.accountId,
          sources.map((source) => [source.sourceRef, source.contentSha256])
        ]),
        refs: sources.map((source) => `source:${source.sourceRef}`),
        error: null
      }
      emit()
    })
    .catch(fail)
}

/** One MAIN-authorized snapshot per account/project revision for every device surface. */
export function useProposalSources(projectId: string | null): SourceState {
  useWorkspaceSessionGeneration()
  const bridge = window.solus?.hardware?.sources
  const state = useSyncExternalStore(subscribe, () => entryFor(projectId, bridge).state)
  const entry = entryFor(projectId, bridge)
  useEffect(() => {
    if (bridge && projectId) load(entry, projectId, bridge)
  }, [entry, projectId, bridge])
  return state
}
