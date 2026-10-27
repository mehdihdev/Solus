import { describe, expect, it } from 'vitest'
import { DRIVE_UNAVAILABLE, type DriveUnavailable } from './driveStatus'

describe('DRIVE_UNAVAILABLE', () => {
  it('lists every reason the setting can show, once', () => {
    const all: Record<DriveUnavailable, true> = {
      not_macos: true,
      no_helper: true,
      no_folder: true,
      nested_folder: true
    }
    expect([...DRIVE_UNAVAILABLE].sort()).toEqual(Object.keys(all).sort())
  })
})
