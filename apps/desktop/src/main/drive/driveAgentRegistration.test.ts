// SOLUSDEV-319 drive slice 3b (sol-drive.md §2.1, §5): the packaged app
// registers the solus-input launch agent with SMAppService only while drive
// is wanted, and reports its state to Settings.
import { describe, expect, it, vi } from 'vitest'
import {
  DRIVE_AGENT_SERVICE,
  DRIVE_LOGIN_ITEMS_URL,
  createAgentRegistration,
  mapAgentStatus,
  type LoginItemsApi
} from './driveAgentRegistration'

describe('mapAgentStatus', () => {
  it.each([
    ['enabled', 'enabled'],
    ['requires-approval', 'requires_approval'],
    ['not-registered', 'not_registered'],
    ['not-found', 'not_found']
  ])('%s → %s', (raw, state) => {
    expect(mapAgentStatus(raw)).toBe(state)
  })

  it.each([[undefined], [''], ['Enabled'], [42]])('null for %s', (raw) => {
    expect(mapAgentStatus(raw)).toBeNull()
  })
})

function api(status = 'not-registered'): LoginItemsApi & {
  set: ReturnType<typeof vi.fn>
  get: ReturnType<typeof vi.fn>
} {
  const set = vi.fn()
  const get = vi.fn(() => ({ status }))
  return { set, get, setLoginItemSettings: set, getLoginItemSettings: get }
}

describe('createAgentRegistration', () => {
  it('registers the agent service when wanted, unregisters when not', () => {
    const a = api()
    const reg = createAgentRegistration(a)
    reg.apply(true)
    reg.apply(false)
    expect(a.set.mock.calls).toEqual([
      [{ openAtLogin: true, ...DRIVE_AGENT_SERVICE }],
      [{ openAtLogin: false, ...DRIVE_AGENT_SERVICE }]
    ])
    expect(DRIVE_AGENT_SERVICE).toEqual({
      type: 'agentService',
      serviceName: 'com.solusforge.solus.input.agent.plist'
    })
  })

  it('the first apply always runs (clears a registration a previous run left behind)', () => {
    const a = api()
    createAgentRegistration(a).apply(false)
    expect(a.set).toHaveBeenCalledWith({ openAtLogin: false, ...DRIVE_AGENT_SERVICE })
  })

  it('a repeated decision does not call SMAppService again', () => {
    const a = api()
    const reg = createAgentRegistration(a)
    reg.apply(true)
    reg.apply(true)
    expect(a.set).toHaveBeenCalledTimes(1)
  })

  it('reads the state for the agent service', () => {
    const a = api('requires-approval')
    expect(createAgentRegistration(a).state()).toBe('requires_approval')
    expect(a.get).toHaveBeenCalledWith(DRIVE_AGENT_SERVICE)
  })

  it('never throws: a failing SMAppService call is retried on the next apply', () => {
    const a = api()
    a.set.mockImplementationOnce(() => {
      throw new Error('denied')
    })
    a.get.mockImplementation(() => {
      throw new Error('nope')
    })
    const warn = vi.fn()
    const reg = createAgentRegistration(a, warn)
    expect(() => reg.apply(true)).not.toThrow()
    expect(reg.state()).toBeNull()
    reg.apply(true)
    expect(a.set).toHaveBeenCalledTimes(2)
    expect(warn).toHaveBeenCalledTimes(1)
  })
})

it('the approval pane is System Settings › Login Items (a fixed URL, never renderer-supplied)', () => {
  expect(DRIVE_LOGIN_ITEMS_URL).toBe(
    'x-apple.systempreferences:com.apple.LoginItems-Settings.extension'
  )
})
