// Component-side glue for the real committed-export EDA connect (SOLUSDEV-100):
// binds the typed API singleton + onboarding store to the pure orchestration in
// edaConnect.ts, mirroring useGithubConnect.
import { createSource, getSource, getSyncs, triggerSync } from '../../lib/api/resources'
import { runEdaConnect, type EdaConnectApi, type EdaExportFile } from './edaConnect'
import { useOnboardingStore } from './onboardingStore'

/** The typed API surface the orchestration runs against (app singleton). */
const edaApi: EdaConnectApi = { createSource, triggerSync, getSyncs, getSource }

export interface UseEdaConnect {
  /** Begin the real connect for a provider with the picked export file. */
  start: (projectId: string, provider: string, file: EdaExportFile) => Promise<void>
}

export function useEdaConnect(): UseEdaConnect {
  const setConnection = useOnboardingStore((s) => s.setConnection)

  const start = async (projectId: string, provider: string, file: EdaExportFile): Promise<void> => {
    await runEdaConnect(
      { api: edaApi, onProgress: (state) => setConnection(provider, state) },
      projectId,
      provider,
      file
    )
  }

  return { start }
}
