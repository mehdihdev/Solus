import { describe, it, expect } from 'vitest'
import { DRIVE_REASON_COPY, driveBlocked, missingGrants } from './driveCopy'
import { driveStatus } from './drive.fixtures'

describe('drive copy (sol-drive.md §5)', () => {
  it('has one sentence per unavailable reason', () => {
    expect(DRIVE_REASON_COPY).toEqual({
      not_macos: 'Only on macOS for now.',
      no_helper: 'The input helper is missing from this install.',
      no_folder: 'Link this project to a folder on this computer first.',
      nested_folder:
        "This project's folder is inside, or contains, another linked project's folder. Move one of them so SOL can't act on the other project's files."
    })
  })

  it('names the missing grants in a fixed order', () => {
    expect(missingGrants(null)).toEqual([])
    expect(missingGrants({ accessibility: true, screenRecording: true })).toEqual([])
    expect(missingGrants({ accessibility: false, screenRecording: false })).toEqual([
      'Accessibility',
      'Screen Recording'
    ])
    expect(missingGrants({ accessibility: true, screenRecording: false })).toEqual([
      'Screen Recording'
    ])
  })

  it('is blocked only when on, available and a grant is missing', () => {
    const missing = { accessibility: false, screenRecording: true }
    expect(driveBlocked(null)).toBe(false)
    expect(driveBlocked(driveStatus({ enabled: false, trust: missing }))).toBe(false)
    expect(driveBlocked(driveStatus({ enabled: true }))).toBe(false)
    expect(driveBlocked(driveStatus({ enabled: true, trust: null }))).toBe(false)
    expect(
      driveBlocked(
        driveStatus({ enabled: true, available: false, reason: 'no_folder', trust: missing })
      )
    ).toBe(false)
    expect(driveBlocked(driveStatus({ enabled: true, trust: missing }))).toBe(true)
  })
})
