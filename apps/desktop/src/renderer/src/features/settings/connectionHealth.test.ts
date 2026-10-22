import { describe, it, expect } from 'vitest'
import { connectionHealth } from './connectionHealth'
import type { Connection } from '../../lib/api/resources'

function conn(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'c1',
    provider: 'github',
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

describe('connectionHealth', () => {
  it('reads a healthy grant as Connected', () => {
    expect(connectionHealth(conn())).toEqual({ label: 'Connected', tone: 'ok' })
  })

  it('asks for a reconnect on a failed handshake or an expired token', () => {
    expect(connectionHealth(conn({ needs_reauth: 'token_error' })).label).toBe('Reconnect')
    expect(connectionHealth(conn({ health: 'token_expired' })).label).toBe('Reconnect')
  })

  it('ranks reconnect above a plain error, and error above degraded (Home H4 order)', () => {
    expect(connectionHealth(conn({ status: 'error', health: 'token_expired' })).label).toBe(
      'Reconnect'
    )
    expect(connectionHealth(conn({ status: 'error', health: 'degraded' })).label).toBe('Error')
    expect(connectionHealth(conn({ health: 'degraded' }))).toEqual({
      label: 'Degraded',
      tone: 'warn'
    })
  })

  it('shows a pending handshake as Pending', () => {
    expect(connectionHealth(conn({ status: 'pending' }))).toEqual({ label: 'Pending', tone: 'mut' })
  })
})
