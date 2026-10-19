// Local folder card on Home (SOLUSDEV-244; from the Project Overview hub,
// SOLUSDEV-164): select an existing directory or clone a repo, then
// open/unlink the linked folder. A long path is clipped with an ellipsis.
//
// SOLUSDEV-249 (I2): the linked folder is a `local` graph source for this
// machine — link/unlink talk to the API with the machine identity, and the
// card shows the scan state, the detected projects and Open-in-tool honestly
// (offline companion disables, never hides; a refusal is shown verbatim).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProjectFolderCard } from './ProjectFolderCard'
import { useProjectFolderStore } from './projectFolderStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as bridge from '../../lib/desktopBridge'
import * as localFolderApi from '../../lib/api/resources.localfolder'
import * as resourcesApi from '../../lib/api/resources'
import type { Source } from '../../lib/api/resources'
import type { DetectedProject, LocalFolderView } from '../../lib/api/resources.localfolder'
import {
  COMPANION_OFFLINE_NOTE,
  COMPANION_RECONNECTING_NOTE,
  NOTHING_DETECTED_TEXT,
  VSCODE_MISSING_NOTE
} from './localFolder.constants'

vi.mock('../../lib/desktopBridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/desktopBridge')>()
  return { ...actual, getDesktopFolderBridge: vi.fn() }
})
vi.mock('../../lib/api/resources.localfolder', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources.localfolder')>()
  return {
    ...actual,
    linkLocalFolder: vi.fn(),
    getLocalFolder: vi.fn(),
    openLocalFolderEntity: vi.fn()
  }
})
vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, disconnectSource: vi.fn() }
})

const pick = vi.fn()
const reveal = vi.fn()
const clone = vi.fn()
const openInVscode = vi.fn()
// The ~/.solus registry write-through (SOLUSDEV-166) rides on the same bridge.
const link = vi.fn()
const unlink = vi.fn()
const links = vi.fn()
const machine = vi.fn()

const MACHINE = { id: '0123456789abcdef0123456789abcdef', name: 'mehdi-mbp' }

const source = (over: Partial<Source> = {}): Source => ({
  id: 's1',
  project_id: 'p1',
  type: 'local',
  name: 'mehdi-mbp',
  status: 'connected',
  config: { machine_id: MACHINE.id, machine_name: MACHINE.name, folder_name: 'arm' },
  account_login: null,
  last_synced_at: '2026-09-07T00:00:00Z',
  last_error: null,
  created_at: '',
  updated_at: '',
  ...over
})

const ROOT: DetectedProject = {
  entity_id: 'e-root',
  entity_key: 'clone:',
  tool: 'clone',
  name: 'arm',
  path: '',
  open_targets: ['vscode', 'system']
}
const KICAD: DetectedProject = {
  entity_id: 'e-kicad',
  entity_key: 'kicad:hw/main',
  tool: 'kicad',
  name: 'main',
  path: 'hw/main/main.kicad_pro',
  open_targets: ['kicad', 'vscode', 'system']
}
const ARDUINO: DetectedProject = {
  entity_id: 'e-ino',
  entity_key: 'arduino:fw/blink',
  tool: 'arduino',
  name: 'blink',
  path: 'fw/blink',
  open_targets: ['vscode', 'system']
}

const view = (over: Partial<LocalFolderView> = {}): LocalFolderView => ({
  source: source(),
  bridge: { connected: true, tools_installed: { kicad: true, vscode: true } },
  detected: [ROOT, KICAD, ARDUINO],
  ...over
})

/** The folder's own "Open in editor" (the root entity) — detected rows carry
 *  their own, so the name alone is ambiguous once the list has landed. */
const rootEditor = (): HTMLElement => screen.getByTestId('open-root-editor')

function linkedCard(): void {
  useWorkspaceStore.setState({ linked: true })
  useProjectFolderStore.setState({ folders: { p1: { path: '/home/u/arm' } } })
}

beforeEach(() => {
  vi.clearAllMocks()
  link.mockResolvedValue({ ok: true })
  unlink.mockResolvedValue({ ok: true })
  links.mockResolvedValue({})
  machine.mockResolvedValue(MACHINE)
  useProjectFolderStore.setState({ folders: {} })
  useWorkspaceStore.setState({ linked: false, project: null })
  vi.mocked(bridge.getDesktopFolderBridge).mockReturnValue({
    pick,
    reveal,
    clone,
    openInVscode,
    link,
    unlink,
    links,
    machine
  })
  vi.mocked(localFolderApi.getLocalFolder).mockResolvedValue(view())
  vi.mocked(localFolderApi.linkLocalFolder).mockResolvedValue({ source: source(), job_id: 'j1' })
  vi.mocked(localFolderApi.openLocalFolderEntity).mockResolvedValue({
    launched: true,
    tool: 'kicad',
    reason: null
  })
  vi.mocked(resourcesApi.disconnectSource).mockResolvedValue({ id: 's1', retained_entities: true })
})

describe('ProjectFolderCard', () => {
  projectFolderBindingTests()
  projectFolderActionsTests()
})

describe('ProjectFolderCard — scan state and detected projects', () => {
  detectedProjectActionsTests()
  projectScanAvailabilityTests()
})

describe('ProjectFolderCard — long paths', () => {
  it('clips the path to one line ending in an ellipsis and keeps the full path in the title', () => {
    const long = '/Users/someone/Documents/robotics/teams/strider/rover-mk2/firmware/workspace'
    useProjectFolderStore.setState({ folders: { p1: { path: long } } })
    render(<ProjectFolderCard projectId="p1" />)
    const path = screen.getByTitle(long)
    expect(path).toHaveTextContent(long)
    expect(path).toHaveStyle({ textOverflow: 'ellipsis', whiteSpace: 'nowrap', overflow: 'hidden' })
  })
})

afterEach(() => {
  vi.useRealTimers()
})

it.each(['api_unreachable', 'parse_error'])(
  'renders scan error %s truthfully through a folder reconnect',
  async (code) => {
    vi.useFakeTimers()
    useWorkspaceStore.setState({ linked: true })
    pick.mockResolvedValue('/home/u/new-folder')
    const message =
      code === 'api_unreachable'
        ? 'this machine’s Solus companion is not connected'
        : 'The schematic cannot be parsed'
    vi.mocked(localFolderApi.getLocalFolder).mockResolvedValue(
      view({
        source: source({ status: 'error', last_error: { code, message } }),
        bridge: { connected: false, tools_installed: {} }
      })
    )
    render(<ProjectFolderCard projectId="p1" />)
    fireEvent.click(screen.getByRole('button', { name: /Select folder/ }))
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(screen.getByText(COMPANION_RECONNECTING_NOTE)).toBeInTheDocument()
    if (code === 'api_unreachable') expect(screen.queryByText(message)).not.toBeInTheDocument()
    else expect(screen.getByText(message)).toBeInTheDocument()
    await act(() => vi.advanceTimersByTimeAsync(30_001))
    expect(screen.getByText(message)).toBeInTheDocument()
  }
)

it('changes a linked folder through the native picker and waits for the registry before integration', async () => {
  linkedCard()
  pick.mockResolvedValue('/home/u/replacement')
  let finish!: (value: { ok: boolean }) => void
  link.mockImplementation(
    () =>
      new Promise<{ ok: boolean }>((resolve) => {
        finish = resolve
      })
  )
  render(<ProjectFolderCard projectId="p1" />)
  await userEvent.click(screen.getByRole('button', { name: /change folder/i }))
  expect(pick).toHaveBeenCalledTimes(1)
  expect(useProjectFolderStore.getState().folders['p1']?.path).toBe('/home/u/arm')
  expect(localFolderApi.linkLocalFolder).not.toHaveBeenCalled()
  await act(async () => {
    finish({ ok: true })
  })
  await waitFor(() =>
    expect(localFolderApi.linkLocalFolder).toHaveBeenCalledWith(
      'p1',
      expect.objectContaining({ folder_name: 'replacement' })
    )
  )
  expect(useProjectFolderStore.getState().folders['p1']?.path).toBe('/home/u/replacement')
  expect(reveal).not.toHaveBeenCalled()
})

it('shows a registry refusal without claiming the folder was integrated', async () => {
  useWorkspaceStore.setState({ linked: true })
  pick.mockResolvedValue('/home/u/replacement')
  link.mockResolvedValue({ ok: false })
  render(<ProjectFolderCard projectId="p1" />)
  await userEvent.click(screen.getByRole('button', { name: /select folder/i }))
  expect(await screen.findByRole('alert')).toHaveTextContent(/could not link/i)
  expect(useProjectFolderStore.getState().folders['p1']).toBeUndefined()
  expect(localFolderApi.linkLocalFolder).not.toHaveBeenCalled()
})

it('ignores a native picker result after switching projects', async () => {
  let finish!: (path: string) => void
  pick.mockImplementation(
    () =>
      new Promise<string>((resolve) => {
        finish = resolve
      })
  )
  const { rerender } = render(<ProjectFolderCard projectId="p1" />)
  await userEvent.click(screen.getByRole('button', { name: /select folder/i }))
  rerender(<ProjectFolderCard projectId="p2" />)
  await act(async () => {
    finish('/home/u/old-project')
  })
  expect(link).not.toHaveBeenCalled()
  expect(localFolderApi.linkLocalFolder).not.toHaveBeenCalled()
})

it('keeps Change folder available after registry acknowledgement when graph linking is still pending', async () => {
  useWorkspaceStore.setState({ linked: true })
  pick.mockResolvedValue('/home/u/arm')
  vi.mocked(localFolderApi.linkLocalFolder).mockReturnValue(new Promise<never>(() => undefined))
  render(<ProjectFolderCard projectId="p1" />)
  await userEvent.click(screen.getByRole('button', { name: /select folder/i }))
  expect(await screen.findByRole('button', { name: /change folder/i })).toBeEnabled()
})

it('restores selection controls when unlink cancels a pending Change folder picker', async () => {
  linkedCard()
  let finish!: (path: string) => void
  pick.mockImplementation(
    () =>
      new Promise<string>((resolve) => {
        finish = resolve
      })
  )
  render(<ProjectFolderCard projectId="p1" />)
  await userEvent.click(screen.getByRole('button', { name: /change folder/i }))
  await userEvent.click(screen.getByRole('button', { name: /unlink/i }))
  await act(async () => {
    finish('/home/u/stale')
  })
  expect(screen.getByRole('button', { name: /select folder/i })).toBeEnabled()
  expect(localFolderApi.linkLocalFolder).not.toHaveBeenCalled()
  expect(link).not.toHaveBeenCalled()
})

it('does not restore pending selection state when returning to a project', async () => {
  linkedCard()
  let finish!: (path: string) => void
  pick.mockImplementation(
    () =>
      new Promise<string>((resolve) => {
        finish = resolve
      })
  )
  const { rerender } = render(<ProjectFolderCard projectId="p1" />)
  await userEvent.click(screen.getByRole('button', { name: /change folder/i }))
  rerender(<ProjectFolderCard projectId="p2" />)
  rerender(<ProjectFolderCard projectId="p1" />)
  expect(screen.getByRole('button', { name: /change folder/i })).toBeEnabled()
  await act(async () => {
    finish('/home/u/stale')
  })
  expect(link).not.toHaveBeenCalled()
})

function projectFolderBindingTests(): void {
  it('degrades honestly when not running under the desktop app', () => {
    vi.mocked(bridge.getDesktopFolderBridge).mockReturnValue(null)
    render(<ProjectFolderCard projectId="p1" />)
    expect(screen.getByText(/desktop app/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /select folder/i })).not.toBeInTheDocument()
  })

  it('offers select and clone when no folder is linked', () => {
    render(<ProjectFolderCard projectId="p1" />)
    expect(screen.getByRole('button', { name: /select folder/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /clone a repo/i })).toBeInTheDocument()
  })

  it('links a selected folder locally AND as this machine’s graph source', async () => {
    useWorkspaceStore.setState({ linked: true })
    pick.mockResolvedValue('/home/u/arm')
    render(<ProjectFolderCard projectId="p1" />)
    await userEvent.click(screen.getByRole('button', { name: /select folder/i }))
    await waitFor(() =>
      expect(useProjectFolderStore.getState().folders['p1']?.path).toBe('/home/u/arm')
    )
    expect(screen.getByText('/home/u/arm')).toBeInTheDocument()
    await waitFor(() =>
      expect(localFolderApi.linkLocalFolder).toHaveBeenCalledWith('p1', {
        machine_id: MACHINE.id,
        machine_name: MACHINE.name,
        folder_name: 'arm'
      })
    )
  })

  it('ignores a cancelled folder pick', async () => {
    pick.mockResolvedValue(null)
    render(<ProjectFolderCard projectId="p1" />)
    await userEvent.click(screen.getByRole('button', { name: /select folder/i }))
    await waitFor(() => expect(pick).toHaveBeenCalled())
    expect(useProjectFolderStore.getState().folders['p1']).toBeUndefined()
    expect(localFolderApi.linkLocalFolder).not.toHaveBeenCalled()
  })
}

function projectFolderActionsTests(): void {
  it('opens the linked folder in the editor through the API, on the root entity', async () => {
    linkedCard()
    render(<ProjectFolderCard projectId="p1" />)
    expect(rootEditor()).toHaveTextContent('Open in editor')
    await waitFor(() => expect(rootEditor()).toBeEnabled())
    await userEvent.click(rootEditor())
    expect(localFolderApi.openLocalFolderEntity).toHaveBeenCalledWith('p1', 's1', {
      entity_id: 'e-root',
      tool: 'vscode'
    })
    // Never from the renderer directly.
    expect(openInVscode).not.toHaveBeenCalled()
  })

  it('opens a linked folder in the file manager and unlinks, disconnecting the source', async () => {
    linkedCard()
    reveal.mockResolvedValue({ ok: true })
    render(<ProjectFolderCard projectId="p1" />)
    await waitFor(() => expect(rootEditor()).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /show in file manager/i }))
    expect(reveal).toHaveBeenCalledWith('/home/u/arm')
    await userEvent.click(screen.getByRole('button', { name: /unlink/i }))
    expect(useProjectFolderStore.getState().folders['p1']).toBeUndefined()
    await waitFor(() =>
      expect(resourcesApi.disconnectSource).toHaveBeenCalledWith('p1', 's1', {
        retainEntities: true
      })
    )
  })

  it('clones a repo into a chosen parent and links the result', async () => {
    useWorkspaceStore.setState({ linked: true })
    pick.mockResolvedValue('/home/u/code')
    clone.mockResolvedValue({ path: '/home/u/code/arm' })
    render(<ProjectFolderCard projectId="p1" suggestedRepoUrl="https://github.com/octo/arm.git" />)
    await userEvent.click(screen.getByRole('button', { name: /clone a repo/i }))
    // URL prefilled from the connected GitHub source.
    expect(screen.getByLabelText(/repository url/i)).toHaveValue('https://github.com/octo/arm.git')
    await userEvent.click(screen.getByRole('button', { name: /choose folder & clone/i }))
    await waitFor(() =>
      expect(clone).toHaveBeenCalledWith({
        repoUrl: 'https://github.com/octo/arm.git',
        parentDir: '/home/u/code'
      })
    )
    await waitFor(() =>
      expect(useProjectFolderStore.getState().folders['p1']?.path).toBe('/home/u/code/arm')
    )
    await waitFor(() =>
      expect(localFolderApi.linkLocalFolder).toHaveBeenCalledWith(
        'p1',
        expect.objectContaining({ folder_name: 'arm' })
      )
    )
  })

  it('shows a clone failure without linking', async () => {
    pick.mockResolvedValue('/home/u/code')
    clone.mockResolvedValue({ error: 'fatal: repository not found' })
    render(<ProjectFolderCard projectId="p1" suggestedRepoUrl="https://github.com/octo/x.git" />)
    await userEvent.click(screen.getByRole('button', { name: /clone a repo/i }))
    await userEvent.click(screen.getByRole('button', { name: /choose folder & clone/i }))
    expect(await screen.findByText(/repository not found/i)).toBeInTheDocument()
    expect(useProjectFolderStore.getState().folders['p1']).toBeUndefined()
  })
}

function detectedProjectActionsTests(): void {
  it('lists every detected project (not the root) with its own Open-in buttons', async () => {
    linkedCard()
    render(<ProjectFolderCard projectId="p1" />)
    const list = await screen.findByRole('list', { name: 'Detected projects' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('main')
    expect(within(rows[0]).getByTitle('hw/main/main.kicad_pro')).toBeInTheDocument()
    expect(within(rows[0]).getByRole('button', { name: 'Open in KiCad' })).toBeEnabled()
    expect(within(rows[1]).queryByRole('button', { name: 'Open in KiCad' })).toBeNull()
    expect(within(rows[1]).getByRole('button', { name: 'Open' })).toBeEnabled()
    expect(screen.getByTestId('scan-state')).toHaveTextContent(/^Scanned /)
    // Rows enter with a staggered fade-rise.
    expect(rows[1]).toHaveClass('local-row-in')
    expect(rows[1]).toHaveStyle({ animationDelay: '40ms' })
  })

  it('fits the card width: rows wrap, name/path clip, nothing declares an intrinsic width', async () => {
    linkedCard()
    vi.mocked(localFolderApi.getLocalFolder).mockResolvedValue(
      view({
        detected: [
          ROOT,
          KICAD,
          { ...KICAD, entity_id: 'e-k2', name: 'a-very-long-kicad-project-name-that-keeps-going' },
          ARDUINO,
          { ...ARDUINO, entity_id: 'e-a2', path: 'firmware/sensors/imu/calibration/blink-long' }
        ]
      })
    )
    render(<ProjectFolderCard projectId="p1" />)
    const list = await screen.findByRole('list', { name: 'Detected projects' })
    expect(screen.getByTestId('linked-folder')).toHaveStyle({ minWidth: '0px', overflow: 'hidden' })
    expect(list).toHaveStyle({ minWidth: '0px', width: '100%' })
    for (const row of screen.getAllByTestId('detected-row')) {
      expect(row).toHaveStyle({ display: 'flex', flexWrap: 'wrap', minWidth: '0px' })
      const name = within(row).getByTestId('detected-name')
      expect(name).toHaveStyle({ minWidth: '0px' })
      for (const line of Array.from(name.children)) {
        expect(line).toHaveStyle({
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap'
        })
        expect(line).toHaveAttribute('title')
      }
      expect(within(row).getByTestId('detected-open')).toHaveStyle({ minWidth: '0px' })
      expect(within(row).getByTestId('open-in-group')).toHaveStyle({ flexWrap: 'wrap' })
    }
    expect(screen.getByTitle('firmware/sensors/imu/calibration/blink-long')).toBeInTheDocument()
  })

  it('opens a detected project in its tool and shows the tool’s refusal inline', async () => {
    linkedCard()
    vi.mocked(localFolderApi.openLocalFolderEntity).mockResolvedValue({
      launched: false,
      tool: 'kicad',
      reason: 'KiCad is not installed on this machine'
    })
    render(<ProjectFolderCard projectId="p1" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Open in KiCad' }))
    expect(localFolderApi.openLocalFolderEntity).toHaveBeenCalledWith('p1', 's1', {
      entity_id: 'e-kicad',
      tool: 'kicad'
    })
    expect(await screen.findByText('KiCad is not installed on this machine')).toBeInTheDocument()
  })
}

function projectScanAvailabilityTests(): void {
  it('disables every Open control — never hides it — while the companion is offline', async () => {
    linkedCard()
    vi.mocked(localFolderApi.getLocalFolder).mockResolvedValue(
      view({ bridge: { connected: false, tools_installed: { kicad: true, vscode: true } } })
    )
    render(<ProjectFolderCard projectId="p1" />)
    const kicad = await screen.findByRole('button', { name: 'Open in KiCad' })
    expect(kicad).toBeDisabled()
    expect(rootEditor()).toBeDisabled()
    expect(rootEditor()).toHaveAttribute('title', COMPANION_OFFLINE_NOTE)
    for (const button of screen.getAllByRole('button', { name: /^Open/ })) {
      if (!/open folder/i.test(button.textContent ?? '')) expect(button).toBeDisabled()
    }
    expect(screen.getByText(COMPANION_OFFLINE_NOTE)).toBeInTheDocument()
    // The OS reveal does not need the companion.
    expect(screen.getByRole('button', { name: /show in file manager/i })).toBeEnabled()
  })

  it('says VS Code is missing when the scan found none', async () => {
    linkedCard()
    vi.mocked(localFolderApi.getLocalFolder).mockResolvedValue(
      view({
        bridge: { connected: true, tools_installed: { kicad: true, vscode: false } },
        detected: [{ ...ROOT, open_targets: ['system'] }]
      })
    )
    render(<ProjectFolderCard projectId="p1" />)
    await waitFor(() => expect(rootEditor()).toHaveAttribute('title', VSCODE_MISSING_NOTE))
    // SOLUSDEV-253: the reason is written under the buttons, not only in a tooltip.
    expect(screen.getByRole('note', { name: '' })).toHaveTextContent(VSCODE_MISSING_NOTE)
  })

  it('shows Scanning… while the source syncs, and the error verbatim on failure', async () => {
    linkedCard()
    vi.mocked(localFolderApi.getLocalFolder).mockResolvedValue(
      view({ source: source({ status: 'syncing', last_synced_at: null }), detected: [] })
    )
    const { unmount } = render(<ProjectFolderCard projectId="p1" />)
    const scanning = await screen.findByTestId('scan-state')
    expect(scanning).toHaveTextContent('Scanning…')
    expect(scanning).toHaveClass('local-scan-shimmer')
    unmount()

    vi.mocked(localFolderApi.getLocalFolder).mockResolvedValue(
      view({
        source: source({
          status: 'error',
          last_error: { code: 'api_unreachable', message: 'No companion session for this machine' }
        }),
        detected: []
      })
    )
    render(<ProjectFolderCard projectId="p1" />)
    const failed = await screen.findByTestId('scan-state')
    expect(failed).toHaveTextContent('No companion session for this machine')
    expect(failed).toHaveStyle({ color: 'var(--err)' })
  })

  it('is honest when a finished scan recognised nothing', async () => {
    linkedCard()
    vi.mocked(localFolderApi.getLocalFolder).mockResolvedValue(view({ detected: [ROOT] }))
    render(<ProjectFolderCard projectId="p1" />)
    expect(await screen.findByText(NOTHING_DETECTED_TEXT)).toBeInTheDocument()
  })

  it('shows nothing under the path before the source exists', async () => {
    linkedCard()
    vi.mocked(localFolderApi.getLocalFolder).mockResolvedValue(view({ source: null, detected: [] }))
    render(<ProjectFolderCard projectId="p1" />)
    await waitFor(() => expect(localFolderApi.getLocalFolder).toHaveBeenCalled())
    expect(screen.queryByTestId('scan-state')).toBeNull()
    expect(screen.queryByText(NOTHING_DETECTED_TEXT)).toBeNull()
    expect(rootEditor()).toBeDisabled()
  })
}

// Home's Overview (SOLUSDEV-317) shows the card compact: a heading, the path,
// Open in editor and Show in file manager up front, Change folder and Unlink
// behind More, and no detected-project list (the Sources tab keeps it).
describe('ProjectFolderCard — compact', () => {
  it('heads the card and keeps the primary actions up front', async () => {
    linkedCard()
    reveal.mockResolvedValue({ ok: true })
    render(<ProjectFolderCard projectId="p1" compact heading="ON THIS COMPUTER" />)
    expect(screen.getByText('ON THIS COMPUTER')).toBeInTheDocument()
    await waitFor(() => expect(rootEditor()).toBeEnabled())
    expect(screen.queryByRole('button', { name: 'Change folder' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /show in file manager/i }))
    expect(reveal).toHaveBeenCalledWith('/home/u/arm')
    expect(screen.queryByRole('list', { name: 'Detected projects' })).toBeNull()
  })

  it('puts Change folder and Unlink behind More', async () => {
    linkedCard()
    render(<ProjectFolderCard projectId="p1" compact />)
    await userEvent.click(screen.getByRole('button', { name: 'More folder actions' }))
    expect(screen.getByRole('menuitem', { name: 'Change folder' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('menuitem', { name: 'Unlink' }))
    expect(useProjectFolderStore.getState().folders['p1']).toBeUndefined()
  })

  it('closes More on Escape', async () => {
    linkedCard()
    render(<ProjectFolderCard projectId="p1" compact />)
    await userEvent.click(screen.getByRole('button', { name: 'More folder actions' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
  })
})
