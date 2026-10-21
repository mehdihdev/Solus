// How Home's SOURCES block (SOLUSDEV-317) groups a project's sources: one
// group per tool the project uses or has a linked account for, a group for
// local folders, holding tools first — and a local folder that is a clone of
// one of the project's GitHub/GitLab repos placed right under it, both ends
// marked. Pure; the component only renders what this returns.
import type { Source } from '../../lib/api/resources'
import type { CatalogEntry } from '../onboarding/integrationCatalog'
import { LOCAL_SOURCE_TYPE } from './connectedAccounts'

export interface ToolGroup {
  key: string
  /** The tool's catalog entry; null for the local-folder group. */
  entry: CatalogEntry | null
  /** An account for this tool is linked. */
  linked: boolean
  held: Source[]
  /** Draw the clone connector toward the paired row. */
  link?: 'above' | 'below'
  /** On a git group: the machine one of its repos is cloned on. */
  clonedOn?: string
  /** On the local group: the repo it is a clone of, as the git source names it. */
  cloneOf?: string
}

/** A git source is its repo; a local folder its machine; anything else its name. */
export function sourceLabel(source: Source): string {
  if (source.type === LOCAL_SOURCE_TYPE) return source.name
  const repo = source.config['repo']
  return typeof repo === 'string' && repo.length > 0 ? repo : source.name
}

export function toolGroups(
  catalog: readonly CatalogEntry[],
  sources: readonly Source[],
  linkedProviders: ReadonlySet<string>
): ToolGroup[] {
  const groups: ToolGroup[] = catalog
    .filter((e) => e.mode !== 'local-bridge')
    .map((entry) => ({
      key: entry.id,
      entry,
      linked: linkedProviders.has(entry.id),
      held: sources.filter((s) => s.type === entry.id)
    }))
    .filter((g) => g.linked || g.held.length > 0)
  const local = sources.filter((s) => s.type === LOCAL_SOURCE_TYPE)
  const all =
    local.length > 0
      ? [...groups, { key: LOCAL_SOURCE_TYPE, entry: null, linked: false, held: local }]
      : groups
  const sorted = [...all].sort((a, b) => Number(b.held.length > 0) - Number(a.held.length > 0))
  return pairLocalClone(sorted)
}

/** The repo a local folder's origin names in a git group, matched like the
 *  server's `clone_of` edge: same host as the tool, owner/name case-insensitive. */
function matchedRepo(local: Source, git: ToolGroup): string | null {
  // (the machine is the local source's name — docs/api/local-folder.md §2)
  const remote = local.remote
  if (!remote || remote.host !== git.key) return null
  const wanted = remote.repo.toLowerCase()
  for (const s of git.held) {
    const repo = s.config['repo']
    if (typeof repo === 'string' && repo.toLowerCase() === wanted) return repo
  }
  return null
}

/** Place a cloned local folder right after its repo's group and mark both. */
export function pairLocalClone(groups: readonly ToolGroup[]): ToolGroup[] {
  const local = groups.find((g) => g.key === LOCAL_SOURCE_TYPE)
  if (!local) return [...groups]
  for (const git of groups) {
    if (git === local) continue
    const clone = local.held.find((s) => matchedRepo(s, git) !== null)
    const repo = clone ? matchedRepo(clone, git) : null
    if (!clone || repo === null) continue
    const rest = groups.filter((g) => g !== local && g !== git)
    const at = groups.filter((g) => g !== local).indexOf(git)
    const pairedGit: ToolGroup = { ...git, link: 'below', clonedOn: clone.name }
    const pairedLocal: ToolGroup = { ...local, link: 'above', cloneOf: repo }
    return [...rest.slice(0, at), pairedGit, pairedLocal, ...rest.slice(at)]
  }
  return [...groups]
}
