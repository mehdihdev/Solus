// The git repos linked to each project, for Home's project list (SOLUSDEV-317):
// a project row names its repo under the project name. There is no team-wide
// sources route, so each project's sources are read ONCE per Home mount (no
// polling — this desktop has 429'd itself before, SOLUSDEV-234); the current
// project's live list overrides its entry in HomeScreen. A failed read leaves
// that project without a line rather than guessing.
import { useEffect, useState } from 'react'
import { listSources, type Source } from '../../lib/api/resources'
import { useWorkspaceFetchEnabled } from './workspaceOnline'

export interface LinkedRepo {
  /** The source type, which is also its logo key (github, gitlab, …). */
  provider: string
  repo: string
}

export type ReposByProject = Readonly<Record<string, readonly LinkedRepo[]>>

/** A source names a repo when its config carries a non-empty `repo`. */
export function linkedRepos(sources: readonly Source[]): LinkedRepo[] {
  return sources.flatMap((s) => {
    const repo = s.config['repo']
    return typeof repo === 'string' && repo.length > 0 ? [{ provider: s.type, repo }] : []
  })
}

export function useProjectRepos(projectIds: readonly string[]): ReposByProject {
  const fetchEnabled = useWorkspaceFetchEnabled()
  const [repos, setRepos] = useState<ReposByProject>({})
  // A stable key: re-read only when the SET of projects changes.
  const key = [...projectIds].sort().join(',')

  useEffect(() => {
    if (!fetchEnabled || key === '') return
    let stale = false
    void Promise.all(
      key.split(',').map(async (id) => {
        try {
          return [id, linkedRepos(await listSources(id))] as const
        } catch {
          return null
        }
      })
    ).then((rows) => {
      if (stale) return
      const found = rows.filter((r): r is readonly [string, LinkedRepo[]] => r !== null)
      setRepos(Object.fromEntries(found))
    })
    return () => {
      stale = true
    }
  }, [fetchEnabled, key])

  return fetchEnabled ? repos : {}
}
