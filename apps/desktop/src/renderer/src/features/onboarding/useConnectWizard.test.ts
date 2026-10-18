// The wizard's surface glue: open/begin/pickFiles/close for the active catalog
// entry, shared by the Sources page and onboarding. Close mid-flight CANCELS
// the attempt (SOLUSDEV-165): the tile state is forgotten immediately and the
// abandoned flow settles quietly. Cancel NEVER deletes a source — for
// multi-selection connectors the backend reuses the existing connected source,
// so `result.sourceId` can name live, populated graph data (security review
// C1). A flow that completed successfully despite the cancel keeps its source
// and is reported: real work is never thrown away silently.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useConnectWizard, useTeamPick, NOT_LINKED_ERROR } from './useConnectWizard'
import {
  EMPTY_EXPORT_ERROR,
  FILE_READ_ERROR,
  MAX_EXPORT_BYTES,
  OVERSIZE_EXPORT_ERROR
} from './edaConnect'
import {
  KICAD_TOO_MANY_FILES_ERROR,
  NO_FILES_ERROR,
  TOO_MANY_FILES_ERROR,
  SCHEMATIC_UNSUPPORTED_ERROR,
  UNRECOGNIZED_FILE_ERROR
} from './kicadFiles'
import { useOnboardingStore } from './onboardingStore'
import * as oauthConnect from './oauthConnect'
import * as accountConnect from './accountConnect'
import * as edaConnect from './edaConnect'
import * as resources from '../../lib/api/resources'
import * as bridgeModule from '../../lib/desktopBridge'
import type { CatalogEntry } from './integrationCatalog'

vi.mock('./oauthConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./oauthConnect')>()
  return { ...actual, runOAuthConnect: vi.fn() }
})
vi.mock('./accountConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./accountConnect')>()
  return { ...actual, runAccountConnect: vi.fn() }
})
vi.mock('./edaConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./edaConnect')>()
  return { ...actual, runEdaConnect: vi.fn() }
})
vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    listSelectable: vi.fn(async () => []),
    createSource: vi.fn(async () => ({ id: 's1' })),
    disconnectSource: vi.fn(async () => ({ id: 's1', retained_entities: false }))
  }
})

const mockedOAuth = vi.mocked(oauthConnect.runOAuthConnect)
const mockedAccount = vi.mocked(accountConnect.runAccountConnect)
const mockedEda = vi.mocked(edaConnect.runEdaConnect)

const LINKED_GITHUB: resources.Connection = {
  id: 'c1',
  provider: 'github',
  status: 'connected',
  account_login: 'octocat',
  access: null,
  needs_reauth: null,
  last_error: null,
  health: 'healthy',
  projects: [],
  created_at: '',
  updated_at: ''
}
const mockedDisconnect = vi.mocked(resources.disconnectSource)

const GITHUB: CatalogEntry = {
  id: 'github',
  name: 'GitHub',
  kind: 'Code',
  mark: 'GH',
  mode: 'oauth',
  configFields: ['repo', 'branch'],
  selection: { mode: 'single', config_key: 'repo', label: 'repository' },
  accessModes: null,
  hosted: null
}

const KICAD: CatalogEntry = {
  id: 'kicad',
  name: 'KiCad',
  kind: 'PCB',
  mark: 'Ki',
  mode: 'export-file',
  configFields: ['export', 'board'],
  selection: null,
  accessModes: null,
  hosted: null
}

const ALTIUM: CatalogEntry = {
  ...KICAD,
  id: 'altium',
  name: 'Altium',
  mark: 'Al',
  configFields: ['export']
}

const BOARD_TEXT = '(kicad_pcb (version 20240108))'
const SCH_TEXT = '(kicad_sch (version 20231120))'

const cancelOAuth = vi.fn(async () => true)

function withBridge(): void {
  vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue({
    getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb?solus_cb=x'),
    awaitGithub: vi.fn(async () => ({ code: 'cd' })),
    getConnectorRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb'),
    awaitOAuth: vi.fn(async () => ({ code: 'cd' })),
    cancelOAuth
  })
}

beforeEach(() => {
  useOnboardingStore.getState().reset()
  vi.clearAllMocks()
  mockedOAuth.mockResolvedValue({ ok: true, sourceId: 's1' })
  mockedEda.mockResolvedValue({ ok: true, sourceId: 's2' })
})

afterEach(() => vi.restoreAllMocks())

/** Park runOAuthConnect and hand the test its resolve. */
function parkOAuth(firstProgress?: import('./onboardingStore').ConnectionState): {
  settle: (r: oauthConnect.OAuthConnectResult) => void
} {
  const parked = { settle: (() => undefined) as (r: oauthConnect.OAuthConnectResult) => void }
  mockedOAuth.mockImplementation(
    (deps) =>
      new Promise((resolve) => {
        if (firstProgress) deps.onProgress(firstProgress)
        parked.settle = resolve
      })
  )
  return parked
}

describe('useConnectWizard', () => {
  registerWizardReadinessTests()

  registerWizardDispatchTests()

  registerExportValidationTests()

  registerExportReadFailuresTests()

  registerExportSizeGuardsTests()

  registerWizardCancellationTests()

  registerWizardSettlementTests()

  registerTeamRepoDispatchTests()
})

it('reopens a failed browser connect as a fresh linked-account project picker', async () => {
  vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
  const { result, rerender } = renderHook(
    ({ linked }: { linked: resources.Connection[] }) =>
      useConnectWizard({ projectId: 'p1', linkedConnections: linked }),
    { initialProps: { linked: [] as resources.Connection[] } }
  )
  act(() => result.current.open(GITHUB))
  await act(() => result.current.begin())
  expect(useOnboardingStore.getState().connections.github?.phase).toBe('error')
  act(() => result.current.close())
  rerender({ linked: [LINKED_GITHUB] })
  act(() => result.current.open(GITHUB))
  expect(useOnboardingStore.getState().connections.github).toBeUndefined()
  await act(() => result.current.begin())
  expect(mockedOAuth).toHaveBeenCalledWith(
    expect.anything(),
    'p1',
    'github',
    expect.objectContaining({ linkedConnection: { id: 'c1', login: 'octocat' } })
  )
  expect(mockedAccount).not.toHaveBeenCalled()
})

it('keeps a completed linked-account result when reopening', () => {
  useOnboardingStore.getState().setConnection('github', { phase: 'done', result: 'Synced' })
  const { result } = renderHook(() =>
    useConnectWizard({
      projectId: 'p1',
      linkedConnections: [LINKED_GITHUB]
    })
  )
  act(() => result.current.open(GITHUB))
  expect(useOnboardingStore.getState().connections.github).toEqual({
    phase: 'done',
    result: 'Synced'
  })
})

it('uses the new project scope when account linking and opening are batched', () => {
  useOnboardingStore.getState().failConnect('github', 'GitHub connect needs the desktop app.')
  const { result, rerender } = renderHook(
    ({ scope }: { scope: 'account' | 'project' }) =>
      useConnectWizard({
        projectId: 'p1',
        scope,
        linkedConnections: [LINKED_GITHUB]
      }),
    { initialProps: { scope: 'account' as 'account' | 'project' } }
  )
  act(() => {
    result.current.open(GITHUB)
    rerender({ scope: 'project' })
  })
  expect(result.current.linkedAccount?.id).toBe('c1')
  expect(useOnboardingStore.getState().connections.github).toBeUndefined()
})

it('refreshes only the active configure source through the existing explicit API', async () => {
  const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
  act(() => result.current.open(GITHUB))
  act(() =>
    useOnboardingStore.getState().setConnection('github', {
      phase: 'busy',
      stage: 'configure',
      label: 'Choose',
      sourceId: 's1',
      selectable: [{ id: 'one', name: 'One' }]
    })
  )
  await act(async () => {
    await result.current.refreshSelection()
  })
  expect(resources.listSelectable).toHaveBeenCalledWith('p1', 's1', undefined, { refresh: true })
})

function registerWizardReadinessTests(): void {
  it('open exposes the active entry; close forgets it', () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    expect(result.current.active).toEqual(GITHUB)
    act(() => result.current.close())
    expect(result.current.active).toBeNull()
  })

  it('begin without a linked project fails honestly and never starts a flow', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: null }))
    act(() => result.current.open(GITHUB))
    await act(async () => result.current.begin())
    expect(mockedOAuth).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.github).toEqual({
      phase: 'error',
      error: NOT_LINKED_ERROR
    })
  })

  it('begin without the desktop bridge fails honestly for an OAuth connector', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    await act(async () => result.current.begin())
    expect(mockedOAuth).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('error')
  })

  it.each([true, false])('reuses a CONNECTED linked account with bridge=%s', async (hasBridge) => {
    if (hasBridge) withBridge()
    else vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    const { result } = renderHook(() =>
      useConnectWizard({ projectId: 'p1', linkedConnections: [LINKED_GITHUB] })
    )
    act(() => result.current.open(GITHUB))
    expect(result.current.linkedAccount).toEqual(LINKED_GITHUB)
    await act(async () => result.current.begin())
    expect(mockedOAuth.mock.calls[0][3]).toMatchObject({
      linkedConnection: { id: 'c1', login: 'octocat' }
    })
  })

  it('ignores a linked account that is not connected', async () => {
    withBridge()
    const errored = { ...LINKED_GITHUB, status: 'error' as const }
    const { result } = renderHook(() =>
      useConnectWizard({ projectId: 'p1', linkedConnections: [errored] })
    )
    act(() => result.current.open(GITHUB))
    expect(result.current.linkedAccount).toBeNull()
    await act(async () => result.current.begin())
    expect(mockedOAuth.mock.calls[0][3]).not.toHaveProperty('linkedConnection')
  })
}

function registerWizardDispatchTests(): void {
  it('account scope binds the account with no project at all', async () => {
    withBridge()
    mockedAccount.mockResolvedValue({ ok: true, connectionId: 'c1', result: 'Connected as x' })
    const onConnected = vi.fn()
    const { result } = renderHook(() =>
      useConnectWizard({ projectId: null, scope: 'account', onConnected })
    )
    act(() => result.current.open(GITHUB))
    expect(result.current.linkedAccount).toBeNull()
    await act(async () => result.current.begin())
    expect(mockedAccount).toHaveBeenCalledTimes(1)
    expect(mockedAccount.mock.calls[0][1]).toBe('github')
    expect(mockedOAuth).not.toHaveBeenCalled()
    expect(onConnected).toHaveBeenCalledTimes(1)
  })

  it('begin drives the OAuth flow and reports success through onConnected', async () => {
    withBridge()
    const onConnected = vi.fn()
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(GITHUB))
    await act(async () => result.current.begin())
    expect(mockedOAuth).toHaveBeenCalledTimes(1)
    expect(mockedOAuth.mock.calls[0][1]).toBe('p1')
    expect(mockedOAuth.mock.calls[0][2]).toBe('github')
    expect(onConnected).toHaveBeenCalledTimes(1)
  })

  it('pickFiles reads a netlist and drives the committed-export flow', async () => {
    const onConnected = vi.fn()
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(KICAD))
    await act(async () => result.current.pickFiles([new File(['<x/>'], 'a.xml')]))
    expect(mockedEda).toHaveBeenCalledTimes(1)
    expect(mockedEda.mock.calls[0][2]).toBe('kicad')
    expect(mockedEda.mock.calls[0][3]).toEqual({ netlist: { fileName: 'a.xml', content: '<x/>' } })
    expect(onConnected).toHaveBeenCalledTimes(1)
  })

  it('pickFiles assembles a netlist + board pick into both config inputs', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    await act(async () =>
      result.current.pickFiles([
        new File([BOARD_TEXT], 'a.kicad_pcb'),
        new File(['(export (version "E"))'], 'a.net')
      ])
    )
    expect(mockedEda).toHaveBeenCalledTimes(1)
    expect(mockedEda.mock.calls[0][3]).toEqual({
      netlist: { fileName: 'a.net', content: '(export (version "E"))' },
      board: { fileName: 'a.kicad_pcb', content: BOARD_TEXT }
    })
  })

  it('pickFiles routes a board-only pick by content, not by extension', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    await act(async () => result.current.pickFiles([new File([BOARD_TEXT], 'misnamed.net')]))
    expect(mockedEda.mock.calls[0][3]).toEqual({
      board: { fileName: 'misnamed.net', content: BOARD_TEXT }
    })
  })
}

function registerExportValidationTests(): void {
  it('a schematic pick fails fast with guidance and never starts a flow', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    await act(async () => result.current.pickFiles([new File([SCH_TEXT], 'a.kicad_sch')]))
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: SCHEMATIC_UNSUPPORTED_ERROR
    })
  })

  it('an assembly error settles the attempt: closing keeps it retryable', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    await act(async () => result.current.pickFiles([new File(['garbage'], 'a.net')]))
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: UNRECOGNIZED_FILE_ERROR
    })
    act(() => result.current.close())
    expect(useOnboardingStore.getState().connections.kicad?.phase).toBe('error')
  })

  it('an empty pick fails without reading or starting anything', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    await act(async () => result.current.pickFiles([]))
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: NO_FILES_ERROR
    })
  })

  it('a single-file provider (altium) keeps its unsniffed one-netlist path', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(ALTIUM))
    await act(async () => result.current.pickFiles([new File(['whatever'], 'design.net')]))
    expect(mockedEda.mock.calls[0][2]).toBe('altium')
    expect(mockedEda.mock.calls[0][3]).toEqual({
      netlist: { fileName: 'design.net', content: 'whatever' }
    })
  })

  it('a single-file provider refuses two files BEFORE reading either (S5)', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(ALTIUM))
    const files = [new File(['a'], 'a.net'), new File(['b'], 'b.net')]
    const reads = files.map((file) => vi.spyOn(file, 'text'))
    await act(async () => result.current.pickFiles(files))
    reads.forEach((read) => expect(read).not.toHaveBeenCalled())
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.altium).toEqual({
      phase: 'error',
      error: TOO_MANY_FILES_ERROR
    })
  })
}

function registerExportReadFailuresTests(): void {
  it('kicad refuses a third file BEFORE reading any — a folder pick never lands in memory (S5)', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const files = [
      new File(['<x/>'], 'a.xml'),
      new File([BOARD_TEXT], 'a.kicad_pcb'),
      new File(['(export)'], 'b.net')
    ]
    const reads = files.map((file) => vi.spyOn(file, 'text'))
    await act(async () => result.current.pickFiles(files))
    reads.forEach((read) => expect(read).not.toHaveBeenCalled())
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: KICAD_TOO_MANY_FILES_ERROR
    })
  })

  it('kicad still accepts exactly two files after the count bound', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    await act(async () =>
      result.current.pickFiles([new File(['<x/>'], 'a.xml'), new File([BOARD_TEXT], 'a.kicad_pcb')])
    )
    expect(mockedEda).toHaveBeenCalledTimes(1)
  })

  it('pickFiles without a project fails honestly even when guard() lets it through (T2)', async () => {
    // `account` scope skips the project check in guard(); pickFiles must still
    // never reach the engine with a null projectId.
    const { result } = renderHook(() => useConnectWizard({ projectId: null, scope: 'account' }))
    act(() => result.current.open(KICAD))
    const file = new File(['<x/>'], 'a.xml')
    const read = vi.spyOn(file, 'text')
    await act(async () => result.current.pickFiles([file]))
    expect(read).not.toHaveBeenCalled()
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: NOT_LINKED_ERROR
    })
  })

  it('a failed file read fails the tile with friendly copy and settles the attempt (T1)', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const file = new File(['<x/>'], 'a.xml')
    vi.spyOn(file, 'text').mockRejectedValue(new Error('EACCES: permission denied'))
    // Resolves (never rejects): a `void wizard.pickFiles()` caller must not
    // surface an unhandled rejection.
    await act(async () => expect(result.current.pickFiles([file])).resolves.toBeUndefined())
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: FILE_READ_ERROR
    })
    expect(FILE_READ_ERROR).not.toMatch(/EACCES/)
    // Settled: closing keeps the error retryable instead of cancelling.
    act(() => result.current.close())
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: FILE_READ_ERROR
    })
  })
}

function registerExportSizeGuardsTests(): void {
  it('a failed read on an attempt the user already cancelled stays quiet (T1)', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const file = new File(['<x/>'], 'a.xml')
    let failRead: (reason: Error) => void = () => undefined
    vi.spyOn(file, 'text').mockImplementation(() => new Promise((_, reject) => (failRead = reject)))

    act(() => {
      void result.current.pickFiles([file])
    })
    act(() => result.current.close())
    await act(async () => failRead(new Error('gone')))

    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toBeUndefined()
  })

  it('rejects an empty pick without reading it and without starting a flow', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const file = new File([], 'empty.xml')
    const text = vi.spyOn(file, 'text')
    await act(async () => result.current.pickFiles([file]))
    expect(text).not.toHaveBeenCalled()
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: EMPTY_EXPORT_ERROR
    })
  })

  it('rejects an oversized pick by SIZE, before file.text() can hang the renderer', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const file = new File(['x'], 'huge.xml')
    Object.defineProperty(file, 'size', { value: MAX_EXPORT_BYTES + 1 })
    const text = vi.spyOn(file, 'text')
    await act(async () => result.current.pickFiles([file]))
    expect(text).not.toHaveBeenCalled()
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toEqual({
      phase: 'error',
      error: OVERSIZE_EXPORT_ERROR
    })
  })

  it('checks EVERY file by size before reading ANY of them', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const fine = new File(['<x/>'], 'a.xml')
    const huge = new File(['x'], 'huge.kicad_pcb')
    Object.defineProperty(huge, 'size', { value: MAX_EXPORT_BYTES + 1 })
    const fineText = vi.spyOn(fine, 'text')
    await act(async () => result.current.pickFiles([fine, huge]))
    expect(fineText).not.toHaveBeenCalled()
    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad?.phase).toBe('error')
  })
}

function registerWizardCancellationTests(): void {
  it('close DURING the file read cancels: no source is created for the abandoned pick', async () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(KICAD))
    const file = new File(['<x/>'], 'a.xml')
    let finishRead: (content: string) => void = () => undefined
    vi.spyOn(file, 'text').mockImplementation(() => new Promise((r) => (finishRead = r)))

    act(() => {
      void result.current.pickFiles([file])
    })
    act(() => result.current.close())
    await act(async () => finishRead('<x/>'))

    expect(mockedEda).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.kicad).toBeUndefined()
  })

  it('close mid-flight cancels: clears the tile state and NEVER deletes a source', async () => {
    withBridge()
    const onConnected = vi.fn()
    const parked = parkOAuth({ phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    await act(async () => undefined) // let the hook reach the engine
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')

    act(() => result.current.close())
    expect(result.current.active).toBeNull()
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()
    // The browser handshake is aborted so the flow settles now.
    expect(cancelOAuth).toHaveBeenCalled()

    // The abandoned flow settles as a failure that DID create a source. It is
    // NOT deleted — for reused-source connectors that id can be live graph
    // data, and cancel must never destroy anything (CLAUDE.md §7).
    act(() => parked.settle({ ok: false, error: 'Configuration cancelled.', sourceId: 's7' }))
    await act(async () => undefined)
    expect(mockedDisconnect).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()
    expect(onConnected).not.toHaveBeenCalled()
  })

  it('close BEFORE the first progress write still cancels the attempt', async () => {
    withBridge()
    const parked = parkOAuth()
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    // No progress has been written yet — the attempt must still be cancellable.
    act(() => result.current.close())
    expect(cancelOAuth).toHaveBeenCalled()

    act(() => parked.settle({ ok: false, error: 'Connect cancelled.' }))
    await act(async () => undefined)
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()
  })
}

function registerWizardSettlementTests(): void {
  it('a cancelled flow that still completed keeps its source — work is not thrown away', async () => {
    withBridge()
    const onConnected = vi.fn()
    const parked = parkOAuth({ phase: 'busy', stage: 'index', label: 'Indexing…' })
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1', onConnected }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    await act(async () => undefined)
    act(() => result.current.close())

    act(() => parked.settle({ ok: true, sourceId: 's8', result: 'Connected — 3 entities indexed' }))
    await waitFor(() => expect(onConnected).toHaveBeenCalledTimes(1))
    expect(mockedDisconnect).not.toHaveBeenCalled()
  })

  it("a stale cancelled attempt cannot clear a NEWER attempt's tile state", async () => {
    withBridge()
    const parked = parkOAuth({ phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    await act(async () => undefined)
    const settleA = parked.settle
    act(() => result.current.close()) // cancel attempt A

    // Retry: attempt B is live and busy.
    const parkedB = parkOAuth({ phase: 'busy', stage: 'authorize', label: 'Authorizing…' })
    act(() => result.current.open(GITHUB))
    act(() => {
      void result.current.begin()
    })
    await act(async () => undefined)
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')

    // A settles late, as a cancelled failure — B's busy tile must survive.
    act(() => settleA({ ok: false, error: 'Configuration cancelled.', sourceId: 's7' }))
    await act(async () => undefined)
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('busy')
    expect(mockedDisconnect).not.toHaveBeenCalled()

    act(() => parkedB.settle({ ok: true, sourceId: 's9' }))
  })

  it('closing on an error keeps the error state so the tile stays retryable', async () => {
    withBridge()
    mockedOAuth.mockImplementation(async (deps) => {
      deps.onProgress({ phase: 'error', error: 'GitHub sign-in was cancelled.' })
      return { ok: false, error: 'GitHub sign-in was cancelled.' }
    })
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    await act(async () => result.current.begin())
    act(() => result.current.close())
    expect(useOnboardingStore.getState().connections.github).toEqual({
      phase: 'error',
      error: 'GitHub sign-in was cancelled.'
    })
    expect(cancelOAuth).not.toHaveBeenCalled()
  })
}

function registerTeamRepoDispatchTests(): void {
  const TEAM_REPO = { id: 'o/vcu', name: 'o/vcu', config: { repo: 'o/vcu', branch: 'main' } }

  beforeEach(() => useTeamPick.setState({ picked: null }))

  it('a picked team repo is handed to the connect, works without the desktop bridge, and is consumed', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    act(() => useTeamPick.setState({ picked: TEAM_REPO }))
    mockedOAuth.mockImplementation(async (deps) => {
      await deps.api.createSource('p1', { type: 'github', name: 'GitHub', connection_id: 'x' })
      return { ok: true, sourceId: 's1' }
    })

    await act(async () => result.current.begin())

    expect(mockedOAuth).toHaveBeenCalledTimes(1)
    expect(vi.mocked(resources.createSource)).toHaveBeenCalledWith('p1', {
      type: 'github',
      name: 'GitHub',
      installation: true,
      config: { repo: 'o/vcu', branch: 'main' }
    })
    expect(useTeamPick.getState().picked).toBeNull()
    expect(useOnboardingStore.getState().connections.github).toBeUndefined()
  })

  it('without a pick and without the bridge, begin still refuses honestly', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))

    await act(async () => result.current.begin())

    expect(mockedOAuth).not.toHaveBeenCalled()
    expect(useOnboardingStore.getState().connections.github?.phase).toBe('error')
  })

  it('closing the wizard forgets an unconsumed pick', () => {
    const { result } = renderHook(() => useConnectWizard({ projectId: 'p1' }))
    act(() => result.current.open(GITHUB))
    act(() => useTeamPick.setState({ picked: TEAM_REPO }))
    act(() => result.current.close())
    expect(useTeamPick.getState().picked).toBeNull()
  })

  it('an account pick (nothing staged) keeps the linked-account path', async () => {
    withBridge()
    const { result } = renderHook(() =>
      useConnectWizard({ projectId: 'p1', linkedConnections: [LINKED_GITHUB] })
    )
    act(() => result.current.open(GITHUB))
    await act(async () => result.current.begin())
    expect(mockedOAuth.mock.calls[0][3]).toMatchObject({
      linkedConnection: { id: 'c1', login: 'octocat' }
    })
  })
}
