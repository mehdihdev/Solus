// Settings → Team data (FND-07; slimmed in SOLUSDEV-244 / HOME H5): the active
// team's detail and my role, plus rename / settings / delete. Everything else
// the old Team screen needed (members, invites, feed, projects, the switcher)
// lives on Home in `useHomeTeam` / `useHomeData` — keeping it here cost four
// extra calls per Settings visit for data nobody rendered.
import { useCallback, useEffect, useState } from 'react'
import {
  deleteTeam as deleteTeamApi,
  getMe,
  getTeamDetail,
  updateTeam as updateTeamApi,
  type TeamDetail,
  type TeamRole,
  type TeamSummary
} from '../../lib/api/resources'
import { classifyFetchError } from '../../lib/api/errors'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { resolveTeamId } from '../workspace/activeTeam'
import { switchWorkspaceTeam } from '../workspace/teamSwitch'
import { useWorkspaceFetchEnabled } from '../workspace/workspaceOnline'

export type TeamDataStatus = 'loading' | 'ready' | 'offline' | 'gone'

export interface TeamActions {
  updateTeam: (input: {
    name?: string
    settings?: { notify_project_created: boolean }
  }) => Promise<boolean>
  /** Owner-only, confirmed by the caller; Home moves to the personal team. */
  deleteTeam: () => Promise<boolean>
  refresh: () => Promise<void>
}

export interface TeamData {
  status: TeamDataStatus
  team: TeamDetail | null
  teams: TeamSummary[]
  myRole: TeamRole | null
  actions: TeamActions
}

export function useTeamData(): TeamData {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const storedTeamId = useWorkspaceStore((s) => s.teamId)
  const [status, setStatus] = useState<TeamDataStatus>(fetchEnabled ? 'loading' : 'offline')
  const [teamId, setTeamId] = useState<string | null>(null)
  const [team, setTeam] = useState<TeamDetail | null>(null)
  const [teams, setTeams] = useState<TeamSummary[]>([])

  const load = useCallback(async (): Promise<void> => {
    if (!fetchEnabled) {
      setStatus('offline')
      return
    }
    try {
      const me = await getMe().catch(() => null)
      setTeams(me?.teams ?? [])
      const id = resolveTeamId(me, storedTeamId)
      if (!id) {
        setStatus('offline')
        return
      }
      const detail = await getTeamDetail(id)
      setTeamId(id)
      setTeam(detail)
      setStatus('ready')
    } catch (error: unknown) {
      // A 404 means the team is gone — not "the backend is down" (errors.ts).
      setStatus(classifyFetchError(error) === 'gone' ? 'gone' : 'offline')
    }
  }, [fetchEnabled, storedTeamId])

  useEffect(() => {
    void load()
  }, [load])

  const run = async (action: () => Promise<unknown>): Promise<boolean> => {
    try {
      await action()
      await load().catch(() => undefined)
      return true
    } catch {
      return false
    }
  }

  const actions: TeamActions = {
    updateTeam: (input) =>
      teamId ? run(() => updateTeamApi(teamId, input)) : Promise.resolve(false),
    deleteTeam: async () => {
      if (!teamId) return false
      try {
        await deleteTeamApi(teamId)
      } catch {
        return false
      }
      const personal = teams.find((t) => t.is_personal)
      if (personal) switchWorkspaceTeam(personal.team_id, 'home')
      await load().catch(() => undefined)
      return true
    },
    refresh: load
  }

  return { status, team, teams, myRole: team?.role ?? null, actions }
}
