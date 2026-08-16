// Component-side glue for the real committed-export EDA connect (SOLUSDEV-100):
// binds the typed API singleton + onboarding store to the pure orchestration in
// edaConnect.ts, mirroring useOAuthConnect.
import { useRef } from 'react'
import { createSource, getSource, getSyncs, triggerSync } from '../../lib/api/resources'
import {
  runEdaConnect,
  type EdaConnectApi,
  type EdaConnectResult,
  type EdaExportFile
} from './edaConnect'
import { useOnboardingStore } from './onboardingStore'

/** The typed API surface the orchestration runs against (app singleton). */
const edaApi: EdaConnectApi = { createSource, triggerSync, getSyncs, getSource }

export interface UseEdaConnect {
  /** Begin the real connect for a provider with the picked export file.
   * Resolves with the structured result so callers can clean up on cancel. */
  start: (projectId: string, provider: string, file: EdaExportFile) => Promise<EdaConnectResult>
  /** Abandon the in-flight connect: the sync itself cannot be stopped, but the
   * attempt goes quiet — no further progress writes resurrect the tile state
   * the wizard forgot. The caller reads `start`'s result to act on the outcome. */
  cancel: () => void
}

export function useEdaConnect(): UseEdaConnect {
  const setConnection = useOnboardingStore((s) => s.setConnection)
  const currentAttempt = useRef<{ cancelled: boolean } | null>(null)

  const start = async (
    projectId: string,
    provider: string,
    file: EdaExportFile
  ): Promise<EdaConnectResult> => {
    const attempt = { cancelled: false }
    currentAttempt.current = attempt
    return runEdaConnect(
      {
        api: edaApi,
        onProgress: (state) => {
          if (!attempt.cancelled) setConnection(provider, state)
        }
      },
      projectId,
      provider,
      file
    )
  }

  const cancel = (): void => {
    if (currentAttempt.current) currentAttempt.current.cancelled = true
  }

  return { start, cancel }
}
