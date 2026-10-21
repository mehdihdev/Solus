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

/** The code hosts a repo can link to, and their web origins. */
const REPO_HOSTS: Readonly<Record<string, string>> = {
  github: 'https://github.com',
  gitlab: 'https://gitlab.com'
}

/** `owner/name`, or `group/sub/name` on GitLab: plain path segments only. */
const REPO_PATH = /^[A-Za-z0-9_.-]+(\/[A-Za-z0-9_.-]+)+$/

/** The repo's web page, or null when the host is unknown or the name is not
 *  plainly path-shaped (the name is user-controlled; never build a URL from
 *  anything else). Segments are encoded and `..` is refused. */
export function repoUrl(repo: LinkedRepo): string | null {
  const origin = REPO_HOSTS[repo.provider.toLowerCase()]
  if (!origin || !REPO_PATH.test(repo.repo)) return null
  const parts = repo.repo.split('/')
  if (parts.some((p) => p === '.' || p === '..')) return null
  return `${origin}/${parts.map(encodeURIComponent).join('/')}`
}

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
