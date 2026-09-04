// SOLUSDEV-235 — user-facing text for the Store's failure paths. Route-plan
// error codes (docs/api/extensions.md §13) map to one honest sentence each;
// anything else is "couldn't reach Solus". Server messages are never rendered
// verbatim — they are data, not copy.
import { ApiError } from '../../lib/api/envelope.types'

export interface ExtensionFailure {
  readonly code: string
  readonly message: string
}

export const EXTENSION_ERROR_TEXT: Readonly<Record<string, string>> = {
  extension_blocked: 'Blocked by your team.',
  grants_required: 'This version asks for permissions you have not granted yet.',
  validation_error: 'Solus rejected that request. Check the values and try again.',
  scope_denied: 'This extension does not hold the permission that action needs.',
  not_found: 'That extension or version is no longer in the catalog.',
  forbidden: 'Only project members can change extensions here.',
  rate_limited: 'Too many changes at once. Wait a moment and try again.',
  unauthorized: 'Your session has expired. Sign in again.'
}

export const UNREACHABLE_MESSAGE = "Couldn't reach Solus. Try again."

/** No desktop bridge (browser preview): the server row exists, the cache does not. */
export const BUNDLE_DEFERRED_NOTE =
  'Installed in this project. The bundle downloads when you open it in the Solus desktop app.'

export function describeExtensionError(error: unknown): ExtensionFailure {
  if (error instanceof ApiError) {
    return {
      code: error.code,
      message: EXTENSION_ERROR_TEXT[error.code] ?? UNREACHABLE_MESSAGE
    }
  }
  return { code: 'unreachable', message: UNREACHABLE_MESSAGE }
}

export function bundleFailureNote(reason: string): string {
  return `Installed in this project, but the bundle could not be cached on this machine (${reason}).`
}
