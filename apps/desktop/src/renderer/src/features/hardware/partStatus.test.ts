// SOLUSDEV-326 P3: a part's status is derived from what is true now, never stored.
import { describe, expect, it } from 'vitest'
import { deriveStatus, statusLabel } from './partStatus'
import { device } from './testing/fixtures'

const NOW = Date.parse('2026-11-16T12:00:00Z')
const none = { live: false, plain: false, device: null, lastSeen: null }

describe('deriveStatus', () => {
  it('is Connected on a live connection', () => {
    expect(deriveStatus({ ...none, live: true })).toEqual({ kind: 'connected' })
  })

  it('is Connected when a present device is bound to it', () => {
    expect(deriveStatus({ ...none, device: device('usb:A') })).toEqual({ kind: 'connected' })
  })

  it('is Not connected when its device is neither present nor remembered', () => {
    expect(deriveStatus(none)).toEqual({ kind: 'not_connected' })
  })

  it('is Last seen from the remembered device when it is not present', () => {
    const at = '2026-11-14T12:00:00Z'
    const status = deriveStatus({ ...none, lastSeen: at })
    expect(status).toEqual({ kind: 'last_seen', at })
    expect(statusLabel(status, NOW)).toBe('Last seen 2 days ago')
  })

  it('is Identifying while its device is being inspected', () => {
    const inspecting = device('usb:A', { state: 'inspecting' })
    expect(deriveStatus({ ...none, device: inspecting })).toEqual({ kind: 'identifying' })
  })

  it('is not Identifying for a device the reader said Not now to', () => {
    const waved = device('usb:A', { state: 'inspecting', dismissed: true })
    expect(deriveStatus({ ...none, device: waved })).toEqual({ kind: 'connected' })
  })

  it('is Unknown, streaming for a plain connection with no protocol', () => {
    expect(deriveStatus({ ...none, plain: true, device: device('usb:A') })).toEqual({
      kind: 'streaming'
    })
    expect(deriveStatus({ ...none, plain: true, live: true })).toEqual({ kind: 'streaming' })
    expect(deriveStatus({ ...none, plain: true })).toEqual({ kind: 'not_connected' })
  })
})

describe('statusLabel', () => {
  it.each([
    [{ kind: 'connected' } as const, 'Connected'],
    [{ kind: 'not_connected' } as const, 'Not connected'],
    [{ kind: 'identifying' } as const, 'Identifying'],
    [{ kind: 'streaming' } as const, 'Unknown, streaming'],
    [{ kind: 'not_seen' } as const, 'Not seen yet'],
    [{ kind: 'last_seen', at: '2026-11-16T11:59:40Z' } as const, 'Last seen just now'],
    [{ kind: 'last_seen', at: '2026-11-16T11:15:00Z' } as const, 'Last seen 45 minutes ago'],
    [{ kind: 'last_seen', at: '2026-11-16T09:00:00Z' } as const, 'Last seen 3 hours ago'],
    [{ kind: 'last_seen', at: '2026-11-15T11:00:00Z' } as const, 'Last seen 1 day ago'],
    [{ kind: 'last_seen', at: 'not a time' } as const, 'Not connected']
  ])('%o reads %s', (status, words) => {
    expect(statusLabel(status, NOW)).toBe(words)
  })
})
