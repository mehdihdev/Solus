// Whether workspace data hooks should attempt API fetches, and how to explain
// an offline result (SOLUSDEV-152 live-testing feedback). An authenticated
// session ALWAYS tries the API — the persisted `linked` onboarding flag only
// unlocks fetches for non-authenticated (dev-bypass) sessions, so a stale
// flag can never hide a real account's data. When data is still unavailable,
// the honest explanation depends on auth: a signed-in user is never told to
// "sign in" — for them the API is unreachable.
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'

export type OfflineReason = 'signed_out' | 'api_unreachable'

export function useWorkspaceFetchEnabled(): boolean {
  const isAuthenticated = useAuthStore((s) => s.status === 'authenticated')
  const linked = useWorkspaceStore((s) => s.linked)
  return isAuthenticated || linked
}

export function useOfflineReason(): OfflineReason {
  const isAuthenticated = useAuthStore((s) => s.status === 'authenticated')
  return isAuthenticated ? 'api_unreachable' : 'signed_out'
}
