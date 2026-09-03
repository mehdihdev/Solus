// SOLUSDEV-235 / EXT-15 — the server-backed layout, per (project, user).
//
// Optimistic by design (wireflow "Persistence and honesty"): every edit lands
// on the grid immediately and schedules ONE debounced PUT; the last write wins.
// A failed PUT keeps the local layout and says so — `saveState` is the honest
// word beside the header button and it never clears on its own. Unknown refs
// are pruned from what renders and from what is written, but pruning alone
// never writes: a project nobody touched never accumulates layout rows.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { WidgetSlotSize } from '@solus/shared-types'
import {
  getWidgetLayout,
  putWidgetLayout,
  type WidgetLayoutApi,
  type WidgetLayoutSlotApi
} from '../../lib/api/resources.extensions'
import {
  addSlot,
  defaultLayout,
  moveSlot,
  pruneLayout,
  removeSlot,
  resizeSlot,
  type AvailableRefs,
  type PruneResult,
  type WidgetLayout
} from './layout'

export const SAVE_DEBOUNCE_MS = 800

export type LayoutStatus = 'loading' | 'ready' | 'offline'
export type SaveState = 'saved' | 'saving' | 'offline'

export interface WidgetLayoutDeps {
  readonly load: (projectId: string) => Promise<WidgetLayoutApi>
  readonly save: (
    projectId: string,
    layout: readonly WidgetLayoutSlotApi[]
  ) => Promise<WidgetLayoutApi>
}

/** Production deps — a module constant so the load effect keys on a stable identity. */
export const defaultWidgetLayoutDeps: WidgetLayoutDeps = {
  load: (projectId) => getWidgetLayout(projectId),
  save: (projectId, layout) => putWidgetLayout(projectId, layout)
}

export interface WidgetLayoutData {
  readonly status: LayoutStatus
  /** What renders and what the next PUT sends: the saved layout minus unknown refs. */
  readonly layout: WidgetLayout
  readonly saveState: SaveState
  readonly prunedCount: number
  readonly prunedRefs: readonly string[]
  add(ref: string, size: WidgetSlotSize): void
  remove(ref: string): void
  resize(ref: string, size: WidgetSlotSize): void
  move(ref: string, direction: -1 | 1): void
  restoreDefault(): void
  /** Re-send now (the note's `Retry`); a pending debounce already covers it. */
  retrySave(): void
}

interface Loaded {
  readonly projectId: string
  readonly status: LayoutStatus
  readonly layout: WidgetLayout
}

interface SaveRecord {
  readonly projectId: string
  readonly state: SaveState
}

interface Pending {
  readonly projectId: string
  readonly layout: WidgetLayout
}

const EMPTY: PruneResult = { layout: [], dropped: [] }

/** `layout: [], updated_at: null` is the server's "never arranged" — that gets the default. */
function fromApi(api: WidgetLayoutApi): WidgetLayout {
  if (api.layout.length === 0 && api.updated_at === null) return defaultLayout()
  return api.layout.map((slot) => ({ ref: slot.ref, size: slot.size }))
}

function toApi(layout: WidgetLayout): WidgetLayoutSlotApi[] {
  return layout.map((slot) => ({ ref: slot.ref, size: slot.size }))
}

interface Saver {
  /** Apply the debounce to a fresh layout (marks `saving`). */
  schedule(pending: Pending): void
  /** Send now unless a debounce already covers it. */
  retry(pending: Pending): void
  /** Send a still-debounced edit immediately (project switch / unmount). */
  flush(): void
  /** The latest edit for `projectId`, if one is unsaved. */
  pending(projectId: string): WidgetLayout | null
}

/** The debounced PUT: one timer, last write wins, `saving` until the LAST write lands. */
function useLayoutSaver(
  save: WidgetLayoutDeps['save'],
  setSaveState: (projectId: string, state: SaveState) => void
): Saver {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingRef = useRef<Pending | null>(null)
  const seqRef = useRef(0)

  const send = useCallback(
    async ({ projectId, layout }: Pending): Promise<void> => {
      const token = ++seqRef.current
      try {
        await save(projectId, toApi(layout))
        if (token !== seqRef.current) return
        // A newer change is already waiting on the debounce: stay `saving`.
        if (timerRef.current !== null) return
        pendingRef.current = null
        setSaveState(projectId, 'saved')
      } catch {
        if (token === seqRef.current) setSaveState(projectId, 'offline')
      }
    },
    [save, setSaveState]
  )

  return useMemo<Saver>(
    () => ({
      schedule: (pending) => {
        pendingRef.current = pending
        setSaveState(pending.projectId, 'saving')
        if (timerRef.current !== null) clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => {
          timerRef.current = null
          if (pendingRef.current !== null) void send(pendingRef.current)
        }, SAVE_DEBOUNCE_MS)
      },
      retry: (pending) => {
        if (timerRef.current !== null) return
        setSaveState(pending.projectId, 'saving')
        void send(pending)
      },
      flush: () => {
        const pending = pendingRef.current
        if (timerRef.current === null || pending === null) return
        clearTimeout(timerRef.current)
        timerRef.current = null
        pendingRef.current = null
        save(pending.projectId, toApi(pending.layout)).catch(() => undefined)
      },
      pending: (projectId) =>
        pendingRef.current?.projectId === projectId ? pendingRef.current.layout : null
    }),
    [save, send, setSaveState]
  )
}

export function useWidgetLayout(
  projectId: string,
  available: AvailableRefs | null,
  deps: WidgetLayoutDeps = defaultWidgetLayoutDeps
): WidgetLayoutData {
  const { load, save } = deps
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [saveRecord, setSaveRecord] = useState<SaveRecord | null>(null)
  const setSaveState = useCallback(
    (forProject: string, state: SaveState) => setSaveRecord({ projectId: forProject, state }),
    []
  )
  const saver = useLayoutSaver(save, setSaveState)

  const current = loaded !== null && loaded.projectId === projectId ? loaded : null
  const view = useMemo<PruneResult>(() => {
    if (current === null) return EMPTY
    return available === null
      ? { layout: current.layout, dropped: [] }
      : pruneLayout(current.layout, available)
  }, [current, available])

  useEffect(() => {
    let live = true
    load(projectId)
      .then((api) => {
        if (live) setLoaded({ projectId, status: 'ready', layout: fromApi(api) })
      })
      .catch(() => {
        if (!live) return
        setLoaded({ projectId, status: 'offline', layout: defaultLayout() })
        setSaveState(projectId, 'offline')
      })
    return () => {
      live = false
      // Leaving the project (or unmounting) with an edit still on the debounce:
      // send it now rather than lose it. Its outcome belongs to the old project.
      saver.flush()
    }
  }, [projectId, load, saver, setSaveState])

  const edit = useCallback(
    (change: (layout: WidgetLayout) => WidgetLayout): void => {
      if (current === null) return
      const base = saver.pending(projectId) ?? view.layout
      const next = change(base)
      if (next === base) return
      setLoaded((prev) => (prev?.projectId === projectId ? { ...prev, layout: next } : prev))
      saver.schedule({ projectId, layout: next })
    },
    [current, projectId, view.layout, saver]
  )

  return {
    status: current === null ? 'loading' : current.status,
    layout: view.layout,
    saveState: saveRecord?.projectId === projectId ? saveRecord.state : 'saved',
    prunedCount: view.dropped.length,
    prunedRefs: view.dropped,
    add: (ref, size) => edit((l) => addSlot(l, ref, size)),
    remove: (ref) => edit((l) => removeSlot(l, ref)),
    resize: (ref, size) => edit((l) => resizeSlot(l, ref, size)),
    move: (ref, direction) => edit((l) => moveSlot(l, ref, direction)),
    restoreDefault: () => edit(() => defaultLayout()),
    retrySave: () => {
      if (current !== null)
        saver.retry({ projectId, layout: saver.pending(projectId) ?? view.layout })
    }
  }
}
