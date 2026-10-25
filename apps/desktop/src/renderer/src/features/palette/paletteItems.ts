// SOLUSDEV-317 — the ⌘K command palette's searchable items (command-palette.md).
// Pure: live data in (screens, rail extensions, the user's teams and projects,
// the OPEN project's entities), palette items out. Every item names a target
// the shell already knows how to reach — the palette adds a way in, never a
// new destination. Node and `.solus` items come only from the open project: the
// palette never searches another project's graph. Besides the loaded snapshot,
// the project's search index (docs/api/search.md) answers the typed query, so
// a node matched by text the snapshot never sees, and every `.solus` entry,
// is reachable too.
import type { Entity, Project, TeamSummary } from '../../lib/api/resources'
import type { EntityHit, SearchWhy, SolusHit } from '../../lib/api/search'
import type { ProjectSearch } from '../workspace/useProjectSearch'
import type { WorkspaceProject } from '../../store/workspaceStore'
import type { MainScreen } from '../workspace/shellStore'

export type PaletteKind = 'page' | 'project' | 'team' | 'node' | 'solus'

export type PaletteTarget =
  | { type: 'screen'; screen: MainScreen }
  | { type: 'extension'; slug: string }
  | { type: 'project'; project: WorkspaceProject }
  | { type: 'team'; teamId: string }
  | { type: 'node'; projectId: string; entityId: string }

export interface PaletteItem {
  /** Stable across reloads; recents are stored as keys and re-resolved against live items. */
  key: string
  kind: PaletteKind
  label: string
  detail?: string
  /** Extra match terms, ranked below the label. */
  keywords?: readonly string[]
  /** Set when the search index matched this item for the current query: a
   *  score floor, so a hit on text the label never shows still ranks. */
  matched?: number
  target: PaletteTarget
}

interface ScreenSpec {
  screen: MainScreen
  label: string
  keywords: readonly string[]
}

/** Same order as the View menu, then the account screens. */
const SCREENS: readonly ScreenSpec[] = [
  { screen: 'home', label: 'Home', keywords: ['projects', 'teams', 'accounts'] },
  { screen: 'workspace', label: 'Workspace', keywords: ['graph', 'nodes', 'parts'] },
  { screen: 'bench', label: 'Live Bench', keywords: ['telemetry', 'sim', 'devices', 'hardware'] },
  { screen: 'sol', label: 'SOL', keywords: ['agent', 'chat', 'ask'] },
  { screen: 'store', label: 'Store', keywords: ['extensions', 'widgets'] },
  { screen: 'billing', label: 'Billing', keywords: ['plan', 'credits', 'subscription'] },
  { screen: 'settings', label: 'Settings', keywords: ['preferences', 'account', 'mode'] }
]

export function pageItems(extensions: readonly { slug: string; label: string }[]): PaletteItem[] {
  return [
    ...SCREENS.map(
      ({ screen, label, keywords }): PaletteItem => ({
        key: `page:${screen}`,
        kind: 'page',
        label,
        keywords,
        target: { type: 'screen', screen }
      })
    ),
    ...extensions.map(
      ({ slug, label }): PaletteItem => ({
        key: `ext:${slug}`,
        kind: 'page',
        label,
        detail: 'Extension',
        target: { type: 'extension', slug }
      })
    )
  ]
}

export interface TeamProjects {
  team: TeamSummary
  projects: readonly Project[]
}

export function projectItems(groups: readonly TeamProjects[]): PaletteItem[] {
  return groups.flatMap(({ team, projects }) =>
    projects.map(
      (p): PaletteItem => ({
        key: `project:${p.id}`,
        kind: 'project',
        label: p.name,
        detail: team.name,
        target: { type: 'project', project: { id: p.id, name: p.name, teamId: p.team_id } }
      })
    )
  )
}

export function teamItems(groups: readonly TeamProjects[]): PaletteItem[] {
  return groups.map(({ team, projects }) => ({
    key: `team:${team.team_id}`,
    kind: 'team',
    label: team.name,
    detail: `${projects.length} project${projects.length === 1 ? '' : 's'}`,
    target: { type: 'team', teamId: team.team_id }
  }))
}

/** The open project's entities as node items. Entity names are ingested content:
 *  they are only ever rendered as text, never interpreted. */
export function nodeItems(projectId: string, entities: readonly Entity[] | null): PaletteItem[] {
  return (entities ?? [])
    .filter((e) => e.project_id === undefined || e.project_id === projectId)
    .map((e) => ({
      key: `node:${projectId}:${e.id}`,
      kind: 'node',
      label: e.name.trim() || `Unnamed ${e.type}`,
      detail: `${e.domain} · ${e.type}`,
      keywords: [e.type, e.domain],
      target: { type: 'node', projectId, entityId: e.id }
    }))
}

/** Index hits rank below a local label prefix (101) and word start (81) but
 *  above a keyword (20): the index already matched by name, text or reference. */
const MATCHED_BY_WHY: Readonly<Record<SearchWhy, number>> = {
  name_match: 70,
  text_match: 40,
  ref_match: 40
}

function matchedScore(hit: EntityHit | SolusHit): number {
  return MATCHED_BY_WHY[hit.why] + Math.min(Math.max(hit.score, 0), 1)
}

/** Loaded node items the index also matched carry its score as a floor. */
export function withIndexScores(
  items: readonly PaletteItem[],
  search: Pick<ProjectSearch, 'entities'>
): PaletteItem[] {
  const scores = new Map(search.entities.map((hit) => [hit.id, matchedScore(hit)]))
  return items.map((item) => {
    const score = item.target.type === 'node' ? scores.get(item.target.entityId) : undefined
    return score === undefined ? item : { ...item, matched: score }
  })
}

/** The index's answer for the typed query: entities the loaded snapshot does
 *  not list (still loading, or filtered) and the project's `.solus` entries.
 *  Every entry is a graph node of its own (SOLUSDEV-320); one not yet placed
 *  in the tree has no node to jump to and is skipped until the next rebuild. */
export function searchItems(
  projectId: string,
  search: Pick<ProjectSearch, 'entities' | 'solus'>,
  knownEntityIds: ReadonlySet<string>
): PaletteItem[] {
  const entities = search.entities
    .filter((hit) => !knownEntityIds.has(hit.id))
    .map(
      (hit): PaletteItem => ({
        key: `node:${projectId}:${hit.id}`,
        kind: 'node',
        label: hit.name.trim() || `Unnamed ${hit.kind}`,
        detail: `${hit.domain} · ${hit.kind}`,
        matched: matchedScore(hit),
        target: { type: 'node', projectId, entityId: hit.id }
      })
    )
  const solus = search.solus.flatMap((hit): PaletteItem[] =>
    hit.entity_id === null
      ? []
      : [
          {
            key: `solus:${projectId}:${hit.id}`,
            kind: 'solus',
            label: hit.name.trim() || hit.kind,
            detail: hit.subsection ? `${hit.section} › ${hit.subsection}` : hit.section,
            matched: matchedScore(hit),
            target: { type: 'node', projectId, entityId: hit.entity_id }
          }
        ]
  )
  return [...entities, ...solus]
}
