import { describe, it, expect } from 'vitest'
import { attentionItems, TRIAL_WARN_DAYS } from './attention'
import { SOL_STATE } from '../sol/solWindow.fixtures'
import type { Connection, Subscription } from '../../lib/api/resources'

const NOW = Date.parse('2026-10-22T12:00:00Z')
const DAY = 86_400_000

const BLOCKED = {
  ...SOL_STATE,
  capture: {
    mode: 'needs-permission' as const,
    message: 'Screen capture needs the Screen Recording permission for Solus.',
    settingsUrl: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'
  }
}

function sub(overrides: Partial<Subscription> = {}): Subscription {
  return {
    user_id: 'u1',
    plan: 'basic',
    status: 'trialing',
    limits: {},
    expires_at: new Date(NOW + 9 * DAY).toISOString(),
    seat_count: 1,
    ...overrides
  }
}

function conn(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'c1',
    provider: 'onshape',
    status: 'connected',
    account_login: 'maya',
    access: 'read',
    needs_reauth: null,
    last_error: null,
    health: 'healthy',
    projects: [],
    created_at: '',
    updated_at: '',
    ...overrides
  }
}

const base = { sol: SOL_STATE, subscription: null, connections: [], now: NOW }

describe('attentionItems', () => {
  it('is empty when nothing needs the user', () => {
    expect(attentionItems(base)).toEqual([])
  })

  it('flags blocked capture only while "SOL sees your screen" is on', () => {
    expect(attentionItems({ ...base, sol: BLOCKED })).toEqual([
      { kind: 'capture', message: BLOCKED.capture.message, canOpenSettings: true }
    ])
    expect(attentionItems({ ...base, sol: { ...BLOCKED, screenIntelligence: false } })).toEqual([])
  })

  it('offers no settings button when the platform has no pane to open (Wayland)', () => {
    const wayland = { ...SOL_STATE, capture: { mode: 'unavailable' as const, message: 'Wayland' } }
    expect(attentionItems({ ...base, sol: wayland })).toEqual([
      { kind: 'capture', message: 'Wayland', canOpenSettings: false }
    ])
  })

  it('ignores a missing SOL state (browser preview, bridge not loaded yet)', () => {
    expect(attentionItems({ ...base, sol: null })).toEqual([])
  })

  it(`warns about a trial ending within ${TRIAL_WARN_DAYS} days, not before`, () => {
    expect(attentionItems({ ...base, subscription: sub() })).toEqual([
      { kind: 'trial', days: 9, ended: false }
    ])
    const far = sub({ expires_at: new Date(NOW + (TRIAL_WARN_DAYS + 1) * DAY).toISOString() })
    expect(attentionItems({ ...base, subscription: far })).toEqual([])
  })

  it('says so when the trial has already ended', () => {
    const ended = sub({ expires_at: new Date(NOW - DAY).toISOString() })
    expect(attentionItems({ ...base, subscription: ended })).toEqual([
      { kind: 'trial', days: 0, ended: true }
    ])
  })

  it('never flags a paid plan', () => {
    expect(attentionItems({ ...base, subscription: sub({ status: 'active' }) })).toEqual([])
  })

  it('asks to reconnect an account whose token failed or expired, skipping revoked ones', () => {
    const items = attentionItems({
      ...base,
      connections: [
        conn({ id: 'a', needs_reauth: 'token_error' }),
        conn({ id: 'b', provider: 'github', health: 'token_expired', account_login: null }),
        conn({ id: 'c', status: 'revoked', health: 'token_expired' }),
        conn({ id: 'd' })
      ]
    })
    expect(items).toEqual([
      { kind: 'reconnect', connectionId: 'a', provider: 'onshape', login: 'maya' },
      { kind: 'reconnect', connectionId: 'b', provider: 'github', login: null }
    ])
  })

  it('orders capture, then trial, then reconnects', () => {
    const kinds = attentionItems({
      sol: BLOCKED,
      subscription: sub(),
      connections: [conn({ needs_reauth: 'token_error' })],
      now: NOW
    }).map((i) => i.kind)
    expect(kinds).toEqual(['capture', 'trial', 'reconnect'])
  })
})
