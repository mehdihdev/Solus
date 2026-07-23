// Topbar project switcher data (SOLUSDEV-164): the signed-in user's ACTIVE
// projects grouped by team, so they can jump between projects from anywhere
// without returning Home first. A lean sibling of useHomeData — it skips the
// activity feed and archived projects the switcher doesn't need. Degrades to an
// empty list offline (dev bypass / unreachable API) like every workspace hook.
import { useCallback, useEffect, useState } from 'react'
import { getMe, listProjects, type Project, type TeamSummary } from '../../lib/api/resources'
import { useWorkspaceFetchEnabled } from './workspaceOnline'

export type ProjectSwitcherStatus = 'loading' | 'ready' | 'offline'

export interface SwitcherGroup {
  team: TeamSummary
  projects: Project[]
}

export interface ProjectSwitcherData {
  status: ProjectSwitcherStatus
  groups: SwitcherGroup[]
}

export function useProjectSwitcher(): ProjectSwitcherData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [status, setStatus] = useState<ProjectSwitcherStatus>(fetchEnabled ? 'loading' : 'offline')
  const [groups, setGroups] = useState<SwitcherGroup[]>([])

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) {
      setStatus('offline')
      setGroups([])
      return
    }
    try {
      const me = await getMe()
      const resolved = await Promise.all(
        me.teams.map(async (team) => ({
          team,
          projects: (await listProjects(team.team_id)).filter((p) => !p.archived_at)
        }))
      )
      setGroups(resolved)
      setStatus('ready')
    } catch {
      setStatus('offline')
      setGroups([])
    }
  }, [fetchEnabled])

  useEffect(() => {
    void load()
  }, [load])

  return { status, groups }
}
