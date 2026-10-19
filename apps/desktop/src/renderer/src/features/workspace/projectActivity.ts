// Per-project activity for the Home project list (SOLUSDEV-242 / HOME H1). Pure.
//
// Home fetches the ACTIVE TEAM's feed once and splits it by project, so a
// team with twenty projects costs one request rather than twenty (this desktop
// has 429'd itself before — SOLUSDEV-234). The split is therefore a WINDOW:
// a project absent from the team's latest rows shows "No recent activity",
// which is honest for the window and never invented. The per-project dialog
// (`useProjectActivity`) asks the server for that project's full feed.
import type { ActivityApi } from '../../lib/api/resources'

/** Rows fetched per Home load — the server's default page, its cap is 100. */
export const HOME_ACTIVITY_FETCH_LIMIT = 50
/** Rows previewed in the Home pane's RECENT ACTIVITY for the current project. */
export const HOME_PANE_ACTIVITY_COUNT = 5

export type ActivityByProject = Readonly<Record<string, readonly ActivityApi[]>>

/** Split a newest-first feed by `project_id`; team-level rows (no project) are dropped. */
export function groupActivityByProject(rows: readonly ActivityApi[]): ActivityByProject {
  const grouped: Record<string, ActivityApi[]> = {}
  for (const row of rows) {
    if (row.project_id === null) continue
    grouped[row.project_id] = [...(grouped[row.project_id] ?? []), row]
  }
  return grouped
}
