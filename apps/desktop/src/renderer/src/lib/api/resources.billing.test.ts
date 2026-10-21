// Billing reads/writes added by SOLUSDEV-236: summary, extended subscription,
// and portal deep-link flows. Paths, methods and bodies are the contract.
import { describe, it, expect } from 'vitest'
import {
  createBillingPortalFlow,
  getBillingSubscription,
  getBillingSummary,
  type BillingSummary
} from './resources.billing'
import type { ApiClient } from './client'

function stubClient(result: unknown): {
  client: ApiClient
  calls: { path: string; options?: unknown }[]
} {
  const calls: { path: string; options?: unknown }[] = []
  const client: ApiClient = {
    request: (async (path: string, options?: unknown) => {
      calls.push({ path, options })
      return result
    }) as ApiClient['request'],
    requestPage: (async () => {
      throw new Error('unused')
    }) as ApiClient['requestPage']
  }
  return { client, calls }
}

describe('getBillingSubscription', () => {
  it('GETs the subscription row and returns the extended fields', async () => {
    const row = {
      user_id: 'u1',
      plan: 'basic',
      status: 'active',
      limits: {},
      expires_at: null,
      seat_count: 1,
      billing_interval: 'year',
      current_period_end: '2026-11-19T00:00:00+00:00',
      trial_expired: false
    }
    const { client, calls } = stubClient(row)
    const sub = await getBillingSubscription(client)
    expect(calls).toEqual([{ path: '/users/me/subscription', options: undefined }])
    expect(sub.billing_interval).toBe('year')
    expect(sub.trial_expired).toBe(false)
  })
})

describe('getBillingSummary', () => {
  it('GETs /billing/summary and returns the typed body', async () => {
    const body: BillingSummary = {
      plan: 'basic',
      status: 'active',
      billing_interval: 'month',
      current_period_end: null,
      cancel_at: null,
      trial: { state: 'none', ends_at: null },
      next_invoice: null,
      payment_method: null,
      prices: null,
      packs_available: false,
      stripe_status: 'unavailable'
    }
    const { client, calls } = stubClient(body)
    await expect(getBillingSummary(client)).resolves.toEqual(body)
    expect(calls).toEqual([{ path: '/billing/summary', options: undefined }])
  })
})

describe('createBillingPortalFlow', () => {
  it('POSTs with no body for the general portal', async () => {
    const { client, calls } = stubClient({ url: 'https://portal/x' })
    await expect(createBillingPortalFlow(undefined, client)).resolves.toEqual({
      url: 'https://portal/x'
    })
    expect(calls).toEqual([{ path: '/billing/portal-session', options: { method: 'POST' } }])
  })

  it.each(['update', 'cancel'] as const)('POSTs {flow: %s} for a deep link', async (flow) => {
    const { client, calls } = stubClient({ url: 'https://portal/y' })
    await createBillingPortalFlow(flow, client)
    expect(calls).toEqual([
      { path: '/billing/portal-session', options: { method: 'POST', body: { flow } } }
    ])
  })
})
