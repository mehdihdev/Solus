// Bridges the onboarding flow to the live API (SOLUSDEV-55): on build, resolve
// the user's personal team, create the project from their description, and
// persist their SOL mode. Best-effort — if the API is unreachable or auth isn't
// configured (dev bypass), it degrades to the simulated flow and the UI carries
// on. Connect/build of the actual graph remain simulated (no backend yet).
import { getMe, createProject, updateSolMode, personalTeam } from '../../lib/api/resources'
import type { SolMode } from '../../store/settingsStore'

const DEFAULT_PROJECT_NAME = 'My first robot'
const MAX_NAME_LENGTH = 80

/** Turn the free-text "what are you building?" into a project name. Pure. */
export function deriveProjectName(description: string): string {
  const firstLine = description.split('\n')[0]?.trim() ?? ''
  if (!firstLine) return DEFAULT_PROJECT_NAME
  const sentence = firstLine.split(/[.!?]/)[0].trim() || firstLine
  return sentence.length > MAX_NAME_LENGTH
    ? `${sentence.slice(0, MAX_NAME_LENGTH).trim()}…`
    : sentence
}

export interface ProvisionResult {
  linked: boolean
  teamId?: string
  project?: { id: string; name: string }
  error?: string
}

export interface ProvisionInput {
  description: string
  solMode: SolMode
  /**
   * The workspace already resolved earlier in the flow (e.g. on entering the
   * Connect step). When a project is present we reuse it instead of creating a
   * second one — onboarding only ever provisions one project.
   */
  existing?: { teamId?: string | null; project?: { id: string; name: string } | null }
}

/**
 * Resolve the real workspace via the API: find the personal team and create the
 * project (once) from the description, persisting the chosen SOL mode. If a
 * project was already created earlier in the flow, reuse it. Resolves
 * `linked: false` (never throws) when the backend can't be reached so
 * onboarding still completes against the simulated path.
 *
 * This is called when entering the Connect step so a real GitHub connect has a
 * project to attach a source to, and again (idempotently) when the build
 * begins.
 */
export async function ensureWorkspace({
  description,
  solMode,
  existing
}: ProvisionInput): Promise<ProvisionResult> {
  if (existing?.project) {
    return { linked: true, teamId: existing.teamId ?? undefined, project: existing.project }
  }
  try {
    const me = await getMe()
    const team = personalTeam(me)
    if (!team) return { linked: false, error: 'No team available for this account' }

    const name = deriveProjectName(description)
    const project = await createProject(team.team_id, {
      name,
      description: description || undefined
    })
    // SOL mode is non-critical; don't fail provisioning if only this errors.
    await updateSolMode(solMode).catch(() => undefined)

    return { linked: true, teamId: team.team_id, project: { id: project.id, name: project.name } }
  } catch (error) {
    return { linked: false, error: error instanceof Error ? error.message : 'API unreachable' }
  }
}

/**
 * Build-time provisioning entry point. Kept for the existing build flow; now a
 * thin alias over {@link ensureWorkspace} so the project is never created twice.
 */
export function provisionWorkspace(input: ProvisionInput): Promise<ProvisionResult> {
  return ensureWorkspace(input)
}
