// One project's full activity feed for the Home card's dialog (SOLUSDEV-242).
// Server-filtered (`?project_id=`, API.md §2.2) so the total is the project's
// own and paging walks only its rows. Loads on mount, appends on `loadMore`,
// and keeps the current feed when a page fails (activity-feed.md).
import { useCallback, useEffect, useState } from 'react'
import { listActivityPage, type ActivityApi } from '../../lib/api/resources'
import type { ApiMeta } from '../../lib/api/envelope.types'

export type ProjectActivityStatus = 'loading' | 'ready' | 'offline'

export interface ProjectActivityData {
  status: ProjectActivityStatus
  activity: ActivityApi[]
  total: number
  hasMore: boolean
  loadMore: () => Promise<void>
}

export function useProjectActivity(teamId: string, projectId: string): ProjectActivityData {
  const [status, setStatus] = useState<ProjectActivityStatus>('loading')
  const [activity, setActivity] = useState<ActivityApi[]>([])
  const [meta, setMeta] = useState<ApiMeta>({})

  useEffect(() => {
    let stale = false
    setStatus('loading')
    setActivity([])
    setMeta({})
    listActivityPage(teamId, { projectId })
      .then((page) => {
        if (stale) return
        setActivity(page.data)
        setMeta(page.meta)
        setStatus('ready')
      })
      .catch(() => {
        if (!stale) setStatus('offline')
      })
    return () => {
      stale = true
    }
  }, [teamId, projectId])

  const loadMore = useCallback(async (): Promise<void> => {
    if (!meta.has_next || !meta.next_cursor) return
    try {
      const page = await listActivityPage(teamId, { projectId, cursor: meta.next_cursor })
      setActivity((prev) => [...prev, ...page.data])
      setMeta(page.meta)
    } catch {
      /* keep the current feed */
    }
  }, [teamId, projectId, meta])

  return {
    status,
    activity,
    total: meta.total ?? activity.length,
    hasMore: meta.has_next ?? false,
    loadMore
  }
}
