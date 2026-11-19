// SOLUSDEV-329 — python_tools.* client events (mcp-fork-runtime.md §10):
// enum and count payloads only — never a path, patch version or message.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  reportInterpreterChosen,
  reportManagedConsent,
  reportSetupFinished,
  setupFinishedPayload
} from './pythonToolsEvents'
import { useAuthStore } from '../../../store/authStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import * as ext from '../../../lib/api/resources.extensions'

const bypass = vi.hoisted(() => ({ active: false }))
vi.mock('../../../lib/supabase', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/supabase')>()),
  get devBypassActive() {
    return bypass.active
  }
}))
vi.mock('../../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof ext>()),
  postDataEvents: vi.fn(async () => undefined)
}))

const posted = (): Array<{ event_type: string; payload: Record<string, unknown> }> =>
  vi.mocked(ext.postDataEvents).mock.calls.map(([events]) => events[0] as never)

beforeEach(() => {
  vi.clearAllMocks()
  bypass.active = false
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.dev' } as never })
  useWorkspaceStore.setState({ project: null })
})

describe('python_tools events', () => {
  it('interpreter_chosen carries the source and minor version only', () => {
    reportInterpreterChosen('picked', '3.13')
    expect(posted()).toEqual([
      {
        event_type: 'python_tools.interpreter_chosen',
        payload: { source: 'picked', version_minor: '3.13' }
      }
    ])
  })

  it('managed_consent carries the answer', () => {
    reportManagedConsent(false)
    expect(posted()[0]).toEqual({
      event_type: 'python_tools.managed_consent',
      payload: { accepted: false }
    })
  })

  it('setup_finished omits error_code entirely on success', () => {
    reportSetupFinished({ outcome: 'ok', failedForks: 0, errorCode: null, trigger: 'settings' })
    const payload = posted()[0].payload
    expect(payload).toEqual({ outcome: 'ok', failed_forks: 0, trigger: 'settings' })
    expect(Object.hasOwn(payload, 'error_code')).toBe(false)
  })

  it('setup_finished includes the first failing code when not ok', () => {
    reportSetupFinished({
      outcome: 'partial',
      failedForks: 1,
      errorCode: 'venv_copies_unhealthy',
      trigger: 'repair'
    })
    expect(posted()[0].payload).toEqual({
      outcome: 'partial',
      failed_forks: 1,
      error_code: 'venv_copies_unhealthy',
      trigger: 'repair'
    })
  })

  it('never sends error_code null, and drops a code on an ok outcome', () => {
    expect(
      Object.hasOwn(
        setupFinishedPayload({
          outcome: 'failed',
          failedForks: 2,
          errorCode: null,
          trigger: 'first_run'
        }),
        'error_code'
      )
    ).toBe(false)
    expect(
      Object.hasOwn(
        setupFinishedPayload({
          outcome: 'ok',
          failedForks: 0,
          errorCode: 'internal',
          trigger: 'settings'
        }),
        'error_code'
      )
    ).toBe(false)
  })

  it('clamps failed_forks to 0–32 integers', () => {
    expect(
      setupFinishedPayload({
        outcome: 'failed',
        failedForks: 99,
        errorCode: null,
        trigger: 'settings'
      }).failed_forks
    ).toBe(32)
    expect(
      setupFinishedPayload({
        outcome: 'failed',
        failedForks: -3,
        errorCode: null,
        trigger: 'settings'
      }).failed_forks
    ).toBe(0)
  })

  it('no payload ever carries a path-like value', () => {
    reportInterpreterChosen('detected', '3.12')
    reportManagedConsent(true)
    reportSetupFinished({
      outcome: 'failed',
      failedForks: 2,
      errorCode: 'network_unreachable',
      trigger: 'settings'
    })
    for (const { payload } of posted()) {
      expect(JSON.stringify(payload)).not.toMatch(/[\\/]/)
      expect(Object.keys(payload)).not.toContain('path')
    }
  })

  it('posts nothing when signed out or in dev bypass', () => {
    useAuthStore.setState({ status: 'unauthenticated' } as never)
    reportManagedConsent(true)
    useAuthStore.setState({ status: 'authenticated' })
    bypass.active = true
    reportManagedConsent(true)
    expect(ext.postDataEvents).not.toHaveBeenCalled()
  })
})
