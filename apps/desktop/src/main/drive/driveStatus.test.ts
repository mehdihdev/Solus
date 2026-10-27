import { describe, expect, it } from 'vitest'
import {
  DRIVE_AGENT_STATES,
  DRIVE_UNAVAILABLE,
  type DriveAgentState,
  type DriveUnavailable
} from './driveStatus'

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

describe('DRIVE_AGENT_STATES', () => {
  it('lists every agent registration state, once', () => {
    const all: Record<DriveAgentState, true> = {
      enabled: true,
      requires_approval: true,
      not_registered: true,
      not_found: true
    }
    expect([...DRIVE_AGENT_STATES].sort()).toEqual(Object.keys(all).sort())
  })
})
