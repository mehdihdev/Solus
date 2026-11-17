// The words a failed hardware write shows: gone, stale, or the server's own message.
import { ApiError } from '../../../lib/api/envelope.types'

export function hardwareErrorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 404)
    return 'This hardware item is no longer available. Reload to review the current project.'
  if (
    error instanceof ApiError &&
    error.status === 409 &&
    ['version_conflict', 'config_conflict'].includes(error.code)
  )
    return 'The saved hardware changed. Reload to review the current version before retrying.'

  return error instanceof Error ? error.message : 'The request failed. Please try again.'
}
