// SOLUSDEV-329 — python_tools.* client events (docs/architecture/
// mcp-fork-runtime.md §10, API.md §2.13). Enum and count payloads only —
// never a path, a patch version or a message. Best effort, like every client
// event: consent is gated server-side and a failed post is dropped.
// The API rejects `error_code: null` and an `error_code` on an ok outcome, so
// the key is omitted unless there is a failing code to report.
import { postDataEvents } from '../../../lib/api/resources.extensions'
import { devBypassActive } from '../../../lib/supabase'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import type { DoneEvent, RuntimeErrorCode } from '../../../../../main/mcpRuntime/protocol'
import type { ProvisionTrigger } from '../../../../../main/mcpRuntime/channels'

export type InterpreterSource = 'detected' | 'picked' | 'managed'
export type VersionMinor = '3.12' | '3.13'
const MAX_FAILED_FORKS = 32

function post(eventType: string, payload: Record<string, unknown>): void {
  if (devBypassActive || useAuthStore.getState().status !== 'authenticated') return
  const projectId = useWorkspaceStore.getState().project?.id
  void postDataEvents([
    { event_type: eventType, ...(projectId ? { project_id: projectId } : {}), payload }
  ]).catch(() => undefined)
}

export function reportInterpreterChosen(
  source: InterpreterSource,
  versionMinor: VersionMinor
): void {
  post('python_tools.interpreter_chosen', { source, version_minor: versionMinor })
}

export function reportManagedConsent(accepted: boolean): void {
  post('python_tools.managed_consent', { accepted })
}

export interface SetupFinished {
  outcome: DoneEvent['outcome']
  failedForks: number
  errorCode: RuntimeErrorCode | null
  trigger: ProvisionTrigger
}

export function setupFinishedPayload(s: SetupFinished): Record<string, unknown> {
  const failed = Math.min(MAX_FAILED_FORKS, Math.max(0, Math.trunc(s.failedForks)))
  const withCode = s.outcome !== 'ok' && s.errorCode !== null
  return {
    outcome: s.outcome,
    failed_forks: failed,
    ...(withCode ? { error_code: s.errorCode } : {}),
    trigger: s.trigger
  }
}

export function reportSetupFinished(s: SetupFinished): void {
  post('python_tools.setup_finished', setupFinishedPayload(s))
}
