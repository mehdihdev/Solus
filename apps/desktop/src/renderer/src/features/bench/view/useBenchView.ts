// The team-shared bench view, per project (docs/api/bench-view.md §2–§3, §7; wireflow
// live-bench-view.md §1, §3, §4). The server is the authority: display gestures apply
// optimistically and are replaced by the PATCH response; a `bench.view_changed` hint
// with a newer version (or a stream `ready`) refetches. Updates are immutable.
import { useEffect } from 'react'
import { create } from 'zustand'
import type { BenchView, BenchViewOp, SetDisplayOp } from '@solus/shared-types'
import {
  classifyBenchViewError,
  getBenchView,
  patchBenchView,
  type BenchViewFailure
} from '../../../lib/api/resources.benchView'
import { applyDisplayOps } from './viewOps'

export const CONFLICT_NOTICE = 'Bench view changed — try again'
const UNREACHABLE_NOTICE = 'The bench view could not be saved. Check your connection.'

export interface BenchViewEdit {
  version: number
  inverseOps: BenchViewOp[]
}

export interface ProjectBenchView {
  view: BenchView | null
  status: 'loading' | 'ready' | 'error'
  /** The user's own last editor write, for the 6 s Undo toast. */
  lastEdit: (BenchViewEdit & { at: number }) | null
  /** A display write's failure sentence (server text, or the fixed conflict line). */
  notice: string | null
}

export type BenchViewWriteOutcome =
  | ({ ok: true } & BenchViewEdit)
  | { ok: false; failure: BenchViewFailure }

interface BenchViewState {
  projects: Readonly<Record<string, ProjectBenchView>>
  load: (projectId: string) => Promise<void>
  /** A live `bench.view_changed`: refetch only when its version is newer than ours. */
  noteHint: (projectId: string, version: number) => Promise<void>
  /** A (re)connected project stream: refetch unconditionally. */
  noteReady: (projectId: string) => Promise<void>
  /** Pin/hide/order/unit/limits/group: optimistic, one retry on 409 (§4.1). */
  setDisplay: (projectId: string, ops: SetDisplayOp[]) => Promise<BenchViewWriteOutcome>
  /** Derived upsert/delete: not optimistic, never retried (§4.2). `baseVersion` (default:
   *  the held version) lets the editor keep a stale draft stale, so its save gets 409. */
  saveDerived: (
    projectId: string,
    ops: BenchViewOp[],
    baseVersion?: number
  ) => Promise<BenchViewWriteOutcome>
  /** Undo (route doc §7): the chip's version and inverse ops, `undo: true`, never retried. */
  undo: (projectId: string, edit: BenchViewEdit) => Promise<BenchViewWriteOutcome>
  dismissNotice: (projectId: string) => void
}

const EMPTY_ENTRY: ProjectBenchView = {
  view: null,
  status: 'loading',
  lastEdit: null,
  notice: null
}

function noticeFor(failure: BenchViewFailure): string {
  if (failure.kind === 'conflict') return CONFLICT_NOTICE
  if (failure.kind === 'refused') return failure.message
  if (failure.kind === 'expression') return failure.details[0]?.message ?? UNREACHABLE_NOTICE
  return UNREACHABLE_NOTICE
}

export const useBenchViewStore = create<BenchViewState>()((set, get) => {
  const entry = (projectId: string): ProjectBenchView => get().projects[projectId] ?? EMPTY_ENTRY
  const update = (projectId: string, change: Partial<ProjectBenchView>): void =>
    set((state) => ({
      projects: { ...state.projects, [projectId]: { ...entry(projectId), ...change } }
    }))

  /** One PATCH. `optimistic` is the view shown while it is in flight (reverted on failure
   *  only if nothing newer replaced it meanwhile). */
  async function send(
    projectId: string,
    body: { version: number; ops: BenchViewOp[]; undo?: boolean },
    optimistic: BenchView | null
  ): Promise<BenchViewWriteOutcome> {
    const before = entry(projectId).view
    if (optimistic) update(projectId, { view: optimistic, notice: null })
    try {
      const result = await patchBenchView(projectId, body)
      const held = entry(projectId).view
      if (!held || result.version >= held.version) update(projectId, { view: result.view })
      return { ok: true, version: result.version, inverseOps: result.inverse_ops }
    } catch (error: unknown) {
      if (optimistic && entry(projectId).view === optimistic) update(projectId, { view: before })
      return { ok: false, failure: classifyBenchViewError(error) }
    }
  }

  async function write(projectId: string, ops: BenchViewOp[]): Promise<BenchViewWriteOutcome> {
    const view = entry(projectId).view
    const optimistic = view ? applyDisplayOps(view, ops) : null
    return send(projectId, { version: view?.version ?? 0, ops }, optimistic)
  }

  function finish(projectId: string, outcome: BenchViewWriteOutcome): BenchViewWriteOutcome {
    if (outcome.ok)
      update(projectId, {
        lastEdit: { version: outcome.version, inverseOps: outcome.inverseOps, at: Date.now() },
        notice: null
      })
    return outcome
  }

  return {
    projects: Object.freeze({}),
    load: async (projectId) => {
      if (!get().projects[projectId]) update(projectId, {})
      try {
        const view = await getBenchView(projectId)
        const held = entry(projectId).view
        if (held && held.version > view.version) return
        update(projectId, { view, status: 'ready' })
      } catch {
        update(projectId, { status: entry(projectId).view ? 'ready' : 'error' })
      }
    },
    noteHint: async (projectId, version) => {
      const held = get().projects[projectId]?.view
      if (held && held.version >= version) return
      await get().load(projectId)
    },
    noteReady: (projectId) => get().load(projectId),
    setDisplay: async (projectId, ops) => {
      const first = await write(projectId, ops)
      if (first.ok || first.failure.kind !== 'conflict') {
        if (!first.ok) update(projectId, { notice: noticeFor(first.failure) })
        return finish(projectId, first)
      }
      await get().load(projectId)
      const retry = await write(projectId, ops)
      if (!retry.ok) update(projectId, { notice: noticeFor(retry.failure) })
      return finish(projectId, retry)
    },
    saveDerived: async (projectId, ops, baseVersion) =>
      finish(
        projectId,
        await send(
          projectId,
          { version: baseVersion ?? entry(projectId).view?.version ?? 0, ops },
          null
        )
      ),
    undo: async (projectId, edit) => {
      const outcome = await send(
        projectId,
        { version: edit.version, ops: edit.inverseOps, undo: true },
        null
      )
      if (outcome.ok) update(projectId, { lastEdit: null })
      return outcome
    },
    dismissNotice: (projectId) => update(projectId, { notice: null })
  }
})

/** Test seam: forget every project's view. */
export function resetBenchViewStore(): void {
  useBenchViewStore.setState({ projects: Object.freeze({}) })
}

/** The project's shared view; fetches on mount and whenever the project changes. */
export function useBenchView(projectId: string | null): ProjectBenchView | null {
  const project = useBenchViewStore((state) => (projectId ? state.projects[projectId] : undefined))
  useEffect(() => {
    if (projectId) void useBenchViewStore.getState().load(projectId)
  }, [projectId])
  return projectId ? (project ?? EMPTY_ENTRY) : null
}
