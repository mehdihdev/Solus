// Component-side glue for the real GitHub connector: bridges the in-tile repo
// picker (a user click) to the async `onChooseRepo` the orchestration awaits,
// and exposes a `start` to kick the flow plus a `chooseRepo` for the picker.
// The pure orchestration lives in githubConnect.ts; this hook only holds the
// React refs + store wiring (SOLUSDEV-103).
import { useRef } from 'react'
import {
  startGithubOAuth,
  exchangeGithubOAuth,
  listRepos,
  updateSource,
  triggerSync,
  getSyncs,
  getSource,
  type GithubRepo
} from '../../lib/api/resources'
import { getDesktopOAuthBridge } from '../../lib/desktopBridge'
import { runGithubConnect, type GithubConnectApi } from './githubConnect'
import { useOnboardingStore, type ConnectionState } from './onboardingStore'

const GITHUB_ID = 'github'

/** The typed API surface the orchestration runs against (app singleton). */
const githubApi: GithubConnectApi = {
  startGithubOAuth,
  exchangeGithubOAuth,
  listRepos,
  updateSource,
  triggerSync,
  getSyncs,
  getSource
}

export interface UseGithubConnect {
  /** Begin the real connect for a project. */
  start: (projectId: string) => Promise<void>
  /** Resolve the in-tile repo picker. */
  chooseRepo: (repo: GithubRepo) => void
}

export function useGithubConnect(): UseGithubConnect {
  const setConnection = useOnboardingStore((s) => s.setConnection)
  // Resolver for the in-tile repo picker; runGithubConnect awaits the choice.
  const repoChoice = useRef<((repo: GithubRepo | null) => void) | null>(null)

  const onProgress = (state: ConnectionState): void => setConnection(GITHUB_ID, state)

  const onChooseRepo = (): Promise<GithubRepo | null> =>
    new Promise<GithubRepo | null>((resolve) => {
      repoChoice.current = (repo) => {
        repoChoice.current = null
        resolve(repo)
      }
    })

  const start = async (projectId: string): Promise<void> => {
    const bridge = getDesktopOAuthBridge()
    const redirectUri = bridge ? await bridge.getRedirectUrl() : ''
    await runGithubConnect({ api: githubApi, bridge, onProgress, onChooseRepo }, projectId, {
      redirectUri
    })
  }

  const chooseRepo = (repo: GithubRepo): void => repoChoice.current?.(repo)

  return { start, chooseRepo }
}
