// Academic plan client (SOLUSDEV-319, ADR-042). Paths, methods and bodies are the contract.
import { describe, it, expect } from 'vitest'
import { getAcademicStatus, sendAcademicCode, verifyAcademicCode } from './resources.academic'
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

const STATUS = {
  state: 'none',
  email: null,
  pending_email: null,
  code_expires_at: null,
  expires_at: null,
  monthly_credits: 1000,
  suffixes: ['edu']
}

describe('academic client', () => {
  it('GETs the caller status', async () => {
    const { client, calls } = stubClient(STATUS)
    await expect(getAcademicStatus(client)).resolves.toEqual(STATUS)
    expect(calls).toEqual([{ path: '/billing/academic', options: undefined }])
  })

  it('POSTs the email to /code', async () => {
    const { client, calls } = stubClient(STATUS)
    await sendAcademicCode('ada@mit.edu', client)
    expect(calls).toEqual([
      {
        path: '/billing/academic/code',
        options: { method: 'POST', body: { email: 'ada@mit.edu' } }
      }
    ])
  })

  it('POSTs the code to /verify', async () => {
    const { client, calls } = stubClient(STATUS)
    await verifyAcademicCode('123456', client)
    expect(calls).toEqual([
      { path: '/billing/academic/verify', options: { method: 'POST', body: { code: '123456' } } }
    ])
  })
})
