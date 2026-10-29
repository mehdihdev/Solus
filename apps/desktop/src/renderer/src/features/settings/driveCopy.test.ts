import { describe, it, expect } from 'vitest'
import {
  DRIVE_NOT_FOUND_COPY,
  DRIVE_REASON_COPY,
  driveBlocked,
  driveHelperMissing,
  driveNeedsApproval,
  missingGrants
} from './driveCopy'
import { driveStatus } from './drive.fixtures'

describe('drive copy (sol-drive.md §5)', () => {
  it('has one sentence per unavailable reason', () => {
    expect(DRIVE_REASON_COPY).toEqual({
      not_macos: 'Only on macOS for now.',
      no_helper: 'The input helper is missing from this install.',
      no_folder: 'Link this project to a folder on this computer first.',
      nested_folder:
        "This project's folder is inside, or contains, another linked project's folder. Move one of them so SOL can't act on the other project's files.",
      bundle_modified:
        "This copy of Solus has been changed since it was signed, so SOL can't use your mouse and keyboard. Reinstall Solus from solusforge.com."
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

  it('needs approval only while on and the agent asks for it', () => {
    expect(driveNeedsApproval(null)).toBe(false)
    expect(driveNeedsApproval(driveStatus({ agent: 'requires_approval' }))).toBe(false)
    expect(driveNeedsApproval(driveStatus({ enabled: true }))).toBe(false)
    expect(driveNeedsApproval(driveStatus({ enabled: true, agent: 'requires_approval' }))).toBe(
      true
    )
  })

  it('reports a missing helper only while on', () => {
    expect(driveHelperMissing(driveStatus({ agent: 'not_found' }))).toBe(false)
    expect(driveHelperMissing(driveStatus({ enabled: true, agent: 'not_found' }))).toBe(true)
    expect(driveHelperMissing(driveStatus({ enabled: true, agent: null }))).toBe(false)
    expect(DRIVE_NOT_FOUND_COPY).toBe(
      'The input helper is not installed correctly; reinstall Solus.'
    )
  })
})
