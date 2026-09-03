import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectStep } from './ConnectStep'
import { useOnboardingStore } from './onboardingStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSettingsStore } from '../../store/settingsStore'
import * as provisioning from './provisioning'
import * as oauthConnect from './oauthConnect'
import * as edaConnect from './edaConnect'
import * as catalogModule from './integrationCatalog'
import { FALLBACK_CATALOG } from './integrationCatalog'
import * as bridgeModule from '../../lib/desktopBridge'
import type { SelectableItem } from '../../lib/api/resources'

vi.mock('./provisioning', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./provisioning')>()
  return { ...actual, ensureWorkspace: vi.fn() }
})

vi.mock('./oauthConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./oauthConnect')>()
  return { ...actual, runOAuthConnect: vi.fn() }
})

vi.mock('./edaConnect', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./edaConnect')>()
  return { ...actual, runEdaConnect: vi.fn() }
})

vi.mock('./integrationCatalog', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./integrationCatalog')>()
  return { ...actual, loadIntegrationCatalog: vi.fn() }
})

const mockedEnsure = vi.mocked(provisioning.ensureWorkspace)
const mockedRun = vi.mocked(oauthConnect.runOAuthConnect)
const mockedEda = vi.mocked(edaConnect.runEdaConnect)
const mockedCatalog = vi.mocked(catalogModule.loadIntegrationCatalog)

function reset(): void {
  useOnboardingStore.getState().reset()
  useWorkspaceStore.getState().reset()
  useSettingsStore.setState({ solMode: 'Guide' })
  vi.clearAllMocks()
  mockedEnsure.mockResolvedValue({ linked: false })
  mockedRun.mockResolvedValue({ ok: true })
  mockedEda.mockResolvedValue({ ok: true })
  mockedCatalog.mockResolvedValue(FALLBACK_CATALOG)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ConnectStep — workspace bootstrap', () => {
  beforeEach(reset)

  it('ensures a workspace on mount, reusing any existing project', async () => {
    useWorkspaceStore.setState({ teamId: 't1', project: { id: 'p1', name: 'X' }, linked: true })
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    expect(mockedEnsure).toHaveBeenCalledWith({
      description: '',
      solMode: 'Guide',
      existing: { teamId: 't1', project: { id: 'p1', name: 'X' } }
    })
  })
})

describe('ConnectStep — OAuth routing', () => {
  beforeEach(reset)

  it('drives the REAL connector when linked + bridge present', async () => {
    const bridge = {
      getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb?solus_cb=x'),
      awaitGithub: vi.fn(async () => ({ code: 'cd' })),
      getConnectorRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb'),
      awaitOAuth: vi.fn(async () => ({ code: 'cd' }))
    }
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(bridge)
    mockedEnsure.mockResolvedValue({ linked: true, teamId: 't1', project: { id: 'p1', name: 'X' } })

    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    // The mount effect linked the workspace.
    await vi.waitFor(() => expect(useWorkspaceStore.getState().linked).toBe(true))

    // The tile opens the wizard; its Connect action starts the real flow.
    await userEvent.click(screen.getByText('GitHub'))
    await userEvent.click(screen.getByRole('button', { name: 'Connect GitHub' }))

    await vi.waitFor(() => expect(mockedRun).toHaveBeenCalledTimes(1))
    const [, projectId, provider, options] = mockedRun.mock.calls[0]
    expect(projectId).toBe('p1')
    expect(provider).toBe('github')
    expect(options).toEqual({ redirectUri: 'http://127.0.0.1:9/cb', displayName: 'GitHub' })
  })

  it('reports an honest error when there is no bridge (dev/web) — never a fake connect', async () => {
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(null)
    mockedEnsure.mockResolvedValue({ linked: true, teamId: 't1', project: { id: 'p1', name: 'X' } })

    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    await vi.waitFor(() => expect(useWorkspaceStore.getState().linked).toBe(true))
    await userEvent.click(screen.getByText('GitHub'))
    await userEvent.click(screen.getByRole('button', { name: 'Connect GitHub' }))

    expect(mockedRun).not.toHaveBeenCalled()
    const github = useOnboardingStore.getState().connections.github
    expect(github?.phase).toBe('error')
    expect(github).toMatchObject({ error: expect.stringMatching(/desktop app/i) })
  })

  it('reports an honest error when the workspace never linked', async () => {
    const bridge = {
      getRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb?solus_cb=x'),
      awaitGithub: vi.fn(async () => ({ code: 'cd' })),
      getConnectorRedirectUrl: vi.fn(async () => 'http://127.0.0.1:9/cb'),
      awaitOAuth: vi.fn(async () => ({ code: 'cd' }))
    }
    vi.spyOn(bridgeModule, 'getDesktopOAuthBridge').mockReturnValue(bridge)
    mockedEnsure.mockResolvedValue({ linked: false })

    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    await userEvent.click(screen.getByText('GitHub'))
    await userEvent.click(screen.getByRole('button', { name: 'Connect GitHub' }))

    expect(mockedRun).not.toHaveBeenCalled()
    const github = useOnboardingStore.getState().connections.github
    expect(github?.phase).toBe('error')
    expect(github).toMatchObject({ error: expect.stringMatching(/unreachable/i) })
  })

  it('renders a picker in the wizard when a busy state carries selectable items', async () => {
    const selectable: SelectableItem[] = [
      { id: 'a/one', name: 'a/one' },
      { id: 'a/two', name: 'a/two' }
    ]
    useOnboardingStore.getState().setConnection('github', {
      phase: 'busy',
      stage: 'configure',
      label: 'Choose repositories to track…',
      sourceId: 's1',
      selectable,
      selectionMode: 'single'
    })
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    // The picker lives in the wizard now — opening the tile surfaces it.
    await userEvent.click(screen.getByText('GitHub'))
    const picker = await screen.findByLabelText('Choose an item to track')
    expect(picker).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'a/two' })).toBeInTheDocument()
  })
})

describe('ConnectStep — KiCad export routing (SOLUSDEV-100)', () => {
  beforeEach(reset)

  it('drives the REAL export connect from the picked netlist when linked', async () => {
    mockedEnsure.mockResolvedValue({ linked: true, teamId: 't1', project: { id: 'p1', name: 'X' } })
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    await vi.waitFor(() => expect(useWorkspaceStore.getState().linked).toBe(true))

    // The tile opens the wizard, whose file step hosts the (hidden) netlist
    // picker; picking a file hands its CONTENT to the orchestration.
    await userEvent.click(screen.getByText('KiCad'))
    const input = screen.getByLabelText('Choose a committed netlist export')
    const netlist = '<export version="E"><components/><nets/></export>'
    const file = new File([netlist], 'power-board.xml', { type: 'text/xml' })
    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } })
    })

    await vi.waitFor(() => expect(mockedEda).toHaveBeenCalledTimes(1))
    const [, projectId, provider, picked] = mockedEda.mock.calls[0]
    expect(projectId).toBe('p1')
    expect(provider).toBe('kicad')
    expect(picked).toEqual({ fileName: 'power-board.xml', content: netlist })
  })

  it('reports an honest error when the workspace never linked', async () => {
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    await userEvent.click(screen.getByText('KiCad'))
    const input = screen.getByLabelText('Choose a committed netlist export')
    const file = new File(['<x/>'], 'a.xml', { type: 'text/xml' })
    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } })
    })

    expect(mockedEda).not.toHaveBeenCalled()
    const kicad = useOnboardingStore.getState().connections.kicad
    expect(kicad?.phase).toBe('error')
    expect(kicad).toMatchObject({ error: expect.stringMatching(/unreachable/i) })
  })

  it('lists live extra export providers (altium) as connectable tiles', async () => {
    mockedCatalog.mockResolvedValue([
      ...FALLBACK_CATALOG,
      { ...FALLBACK_CATALOG[1], id: 'altium', name: 'Altium', mark: 'Al', mode: 'export-file' }
    ])
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    expect(await screen.findByText('Altium')).toBeInTheDocument()
    expect(screen.getByText(/OF 3 CONNECTED/)).toBeInTheDocument()
  })
})

describe('ConnectStep — local-bridge routing (SOLUSDEV-72)', () => {
  beforeEach(reset)

  it('a local-bridge tile opens the companion guidance, not a credential flow', async () => {
    mockedCatalog.mockResolvedValue([
      ...FALLBACK_CATALOG,
      {
        id: 'fusion',
        name: 'Fusion',
        kind: 'Local tool — companion bridge',
        mark: 'Fu',
        mode: 'local-bridge',
        configFields: [],
        selection: null,
        accessModes: null,
        hosted: null,
        localTool: {
          type: 'fusion',
          display_name: 'Fusion',
          hosting: 'vendor-run',
          url_host: '127.0.0.1:27182',
          connect_notice: 'Launch Fusion and enable the MCP server',
          requires: 'companion'
        }
      }
    ])
    // Deliberately NOT linked: guidance needs no project and no OAuth bridge.
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    await userEvent.click(await screen.findByText('Fusion'))

    expect(await screen.findByText('Connect Fusion')).toBeInTheDocument()
    expect(screen.getByText('Launch Fusion and enable the MCP server')).toBeInTheDocument()
    expect(mockedRun).not.toHaveBeenCalled()
    expect(mockedEda).not.toHaveBeenCalled()
    // No error state was invented for the tile either.
    expect(useOnboardingStore.getState().connections.fusion).toBeUndefined()
  })
})

describe('ConnectStep — skip path (FND-08)', () => {
  beforeEach(reset)

  it('offers Skip for now with zero connections and it triggers the build', async () => {
    const onBuild = vi.fn()
    await act(async () => {
      render(<ConnectStep onBuild={onBuild} />)
    })
    const skip = screen.getByRole('button', { name: 'Skip for now' })
    expect(skip).toBeEnabled()
    await userEvent.click(skip)
    expect(onBuild).toHaveBeenCalledTimes(1)
  })

  it('keeps the primary build button gated until enough sources connect', async () => {
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    expect(screen.getByRole('button', { name: /Build context model/ })).toBeDisabled()
  })

  it('hides Skip once the recommended sources are connected', async () => {
    useOnboardingStore.getState().setConnection('github', { phase: 'done' })
    useOnboardingStore.getState().setConnection('kicad', { phase: 'done' })
    await act(async () => {
      render(<ConnectStep onBuild={vi.fn()} />)
    })
    expect(screen.queryByRole('button', { name: 'Skip for now' })).toBeNull()
    expect(screen.getByRole('button', { name: /Build context model/ })).toBeEnabled()
  })
})
