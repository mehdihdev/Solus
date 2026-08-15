// One rule for "why did that fetch fail", because the app kept getting it wrong.
//
// Every data hook used to `catch { setStatus('offline') }`, so a 404 for a team
// that no longer exists rendered as "Solus can't reach its API. Make sure the
// backend is running" — while the backend was answering that very request. The
// user goes and restarts a healthy server; the stale reference that actually
// broke them is never mentioned.
//
// `useValidateProject.ts` already stated the rule correctly in prose: ONLY a 404
// means gone; a 401, a 5xx or an unreachable API means we could not ask. This is
// that rule as one function, so the three hand-rolled `status === 404` checks and
// the six hooks stop each having their own opinion.
import { ApiError } from './envelope.types'

/**
 * Why a request failed, in the only three shapes a caller acts on differently.
 *
 * - `gone` — the server answered, authoritatively, that this resource is not
 *   there. The ONLY verdict that justifies discarding local state.
 * - `unauthorized` — we are not allowed to ask. Says nothing about whether the
 *   resource exists.
 * - `unreachable` — we could not get an answer we can trust: network failure,
 *   5xx, or anything unrecognised.
 */
export type FetchFailure = 'gone' | 'unauthorized' | 'unreachable'

export function classifyFetchError(error: unknown): FetchFailure {
  // Not an ApiError ⇒ the request never produced a parsed HTTP status at all
  // (network failure, abort, a bug). An object that merely *looks* like one is
  // not trusted: only the client mints ApiError, and only from a real response.
  if (!(error instanceof ApiError)) return 'unreachable'
  if (error.status === 404) return 'gone'
  if (error.status === 401 || error.status === 403) return 'unauthorized'
  // Everything else — 5xx, and 4xx like 409/422 that mean WE asked wrongly —
  // falls through to `unreachable`. That is deliberate: `gone` is the verdict
  // that makes callers throw state away, so nothing reaches it by accident.
  return 'unreachable'
}
