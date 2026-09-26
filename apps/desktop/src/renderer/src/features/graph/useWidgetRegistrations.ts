import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Entity } from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'
import { reconcileWidgetGraph } from '../../lib/api/widgetGraph'
import { useHardwareGeneration } from './hardware/useHardwareGeneration'
import { isWidgetRegistration } from './widgetRegistrationProjection'
import { useAuthStore } from '../../store/authStore'

type Status = 'idle' | 'pending' | 'done' | 'forbidden' | 'error'
interface Attempt {
  controller: AbortController
  generation: number
}

/** Attempts belong to an account/project visit, not an access-token lifetime. */
function useRegistrationVisit(projectId: string | null): {
  visit: React.RefObject<number>
  attempt: React.RefObject<Attempt | null>
} {
  const visit = useRef(0)
  const attempt = useRef<Attempt | null>(null)
  useLayoutEffect(() => {
    visit.current += 1
    attempt.current = null
    return () => {
      visit.current += 1
      attempt.current?.controller.abort()
    }
  }, [projectId])
  useEffect(
    () =>
      useAuthStore.subscribe((next, previous) => {
        if (next.user?.email !== previous.user?.email || next.status !== previous.status) {
          visit.current += 1
          attempt.current?.controller.abort()
          attempt.current = null
        }
      }),
    []
  )
  return { visit, attempt }
}

export function useWidgetRegistrations(
  projectId: string | null,
  ready: boolean,
  entities: readonly Entity[] | null,
  onGraphChanged: () => void
): { status: Status; retry: () => void } {
  const { generation, authEpoch } = useHardwareGeneration(projectId ?? '')
  const { visit, attempt } = useRegistrationVisit(projectId)
  const [retryVersion, setRetryVersion] = useState(0)
  const [state, setState] = useState<{ visit: number; status: Status }>({
    visit: -1,
    status: 'idle'
  })
  const hasRoot = Boolean(
    projectId &&
    entities?.some(
      (entity) => entity.type === 'solus:live_bench' && isWidgetRegistration(entity, projectId)
    )
  )
  // A refreshed credential cancels pending work, but never grants an automatic retry.
  useEffect(() => {
    const previous = attempt.current
    if (
      !previous ||
      previous.generation === generation.current ||
      previous.controller.signal.aborted
    )
      return
    previous.controller.abort()
    const scope = visit.current
    void Promise.resolve().then(() => {
      if (visit.current !== scope) return
      setState((old) =>
        old.visit === scope && old.status !== 'pending' && old.status !== 'idle'
          ? old
          : { visit: scope, status: 'error' }
      )
    })
  }, [authEpoch, attempt, generation, visit])

  useEffect(() => {
    if (!projectId || !ready || entities === null || hasRoot || attempt.current) return
    const controller = new AbortController()
    const stamp = generation.current
    const scope = visit.current
    attempt.current = { controller, generation: stamp }
    const current = (): boolean => !controller.signal.aborted && generation.current === stamp
    // Defer dispatch so replayed/expired effects cancel before a write is sent.
    void Promise.resolve()
      .then(() => {
        if (!current()) return
        setState({ visit: scope, status: 'pending' })
        return reconcileWidgetGraph(projectId, controller.signal)
      })
      .then(() => {
        if (!current()) return
        setState({ visit: scope, status: 'done' })
        onGraphChanged()
      })
      .catch((error: unknown) => {
        if (!current()) return
        setState({
          visit: scope,
          status: error instanceof ApiError && error.status === 403 ? 'forbidden' : 'error'
        })
      })
  }, [
    projectId,
    ready,
    entities,
    hasRoot,
    generation,
    authEpoch,
    retryVersion,
    onGraphChanged,
    visit,
    attempt
  ])

  const status = hasRoot || state.visit !== visit.current ? 'idle' : state.status
  const retry = (): void => {
    if (status !== 'error' && status !== 'forbidden') return
    attempt.current = null
    setRetryVersion((version) => version + 1)
  }
  return { status, retry }
}
