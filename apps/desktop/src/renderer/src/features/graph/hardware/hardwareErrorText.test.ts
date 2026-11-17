// The words a failed hardware write shows: gone, stale, or the server's own message.
import { expect, it } from 'vitest'
import { ApiError } from '../../../lib/api/envelope.types'
import { hardwareErrorText } from './hardwareErrorText'

it('distinguishes deleted hardware from a stale saved version', () => {
  expect(hardwareErrorText(new ApiError(404, 'not_found', 'Part not found'))).toContain(
    'no longer available'
  )
  expect(hardwareErrorText(new ApiError(409, 'version_conflict', 'Version changed'))).toContain(
    'Reload'
  )
  expect(hardwareErrorText(new ApiError(409, 'config_conflict', 'Config changed'))).toContain(
    'Reload'
  )
})

it("keeps the server's words for any other failure and never shows a non-error", () => {
  expect(hardwareErrorText(new ApiError(409, 'held', 'Already on a robot'))).toBe(
    'Already on a robot'
  )
  expect(hardwareErrorText('boom')).toBe('The request failed. Please try again.')
})
