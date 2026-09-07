// SOLUSDEV-235 / EXT-20 — Settings → Developer (wireflow §4): load an unpacked
// folder, list registrations with the DEV badge and current problems, reload
// and remove. Desktop-only: without the extensions bridge nothing renders.
//
// State is seeded through the fake bridge's index (main's durable copy), not
// by writing the store — the section hydrates from the index on mount, exactly
// as the real app does after a restart.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ACK_BUTTON, ACK_COPY, DeveloperSection } from './DeveloperSection'
import {
  selectDevRegistration,
  useDevExtensionsStore
} from '../../devExtensions/devExtensionsStore'
import { fakeBridge, fakeManifest } from '../../extensions/frame/testing/fixtures'
import * as bridge from '../../../lib/desktopBridge'

vi.mock('../../../lib/desktopBridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/desktopBridge')>()
  return { ...actual, getDesktopExtensionsBridge: vi.fn(), getDesktopFolderBridge: vi.fn() }
})

type DevLoadResult = Awaited<ReturnType<bridge.ExtensionsBridge['devLoad']>>

const BOM_PATH = '/Users/maya/code/solus-ext-bom'
const BROKEN_PATH = '/Users/maya/code/broken-ext'
const PROBLEMS = [
  'views.page.entry: must be a relative path with no `..` segments',
  'store.privacy_policy: required when permissions are declared'
]
const LOADED_BOM: DevLoadResult = { ok: true, manifest: fakeManifest(), devPath: BOM_PATH }

const pick = vi.fn<() => Promise<string | null>>()
let extensions: ReturnType<typeof fakeBridge>
/** What main answers per folder; tests mutate it between actions. */
let answers: Record<string, DevLoadResult>

function folderBridge(): NonNullable<ReturnType<typeof bridge.getDesktopFolderBridge>> {
  return {
    pick,
    reveal: vi.fn(),
    openInVscode: vi.fn(),
    clone: vi.fn(),
    link: vi.fn(),
    unlink: vi.fn(),
    links: vi.fn(),
    machine: vi.fn()
  }
}

/** Register a dev row in main's index so hydrate() lists it. */
function registered(slug: string, devPath: string): void {
  extensions.entries[slug] = { version: '1.2.0', source: 'dev', devPath }
}

beforeEach(() => {
  vi.clearAllMocks()
  useDevExtensionsStore.getState().reset()
  answers = {}
  extensions = fakeBridge()
  extensions.devLoad = vi.fn(
    async (path: string) => answers[path] ?? { ok: false, problems: ['path: unknown folder'] }
  )
  vi.mocked(bridge.getDesktopExtensionsBridge).mockReturnValue(extensions)
  vi.mocked(bridge.getDesktopFolderBridge).mockReturnValue(folderBridge())
})

describe('DeveloperSection', () => {
  it('renders nothing without the desktop extensions bridge', () => {
    vi.mocked(bridge.getDesktopExtensionsBridge).mockReturnValue(null)
    const { container } = render(<DeveloperSection />)
    expect(container).toBeEmptyDOMElement()
    expect(extensions.index).not.toHaveBeenCalled()
  })

  it('shows the title, copy, load button and empty state, and hydrates on mount', async () => {
    render(<DeveloperSection />)
    expect(screen.getByText('Developer')).toBeInTheDocument()
    expect(screen.getByText(/Load an unpacked extension folder/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load unpacked extension…' })).toBeInTheDocument()
    expect(screen.getByText('No unpacked extensions loaded.')).toBeInTheDocument()
    await waitFor(() => expect(extensions.index).toHaveBeenCalledTimes(1))
  })

  it('lists a registration from the index with name, DEV badge, slug and path', async () => {
    registered('bom', BOM_PATH)
    answers[BOM_PATH] = LOADED_BOM
    render(<DeveloperSection />)

    const row = await screen.findByTestId('dev-ext-bom')

    expect(row).toHaveClass('screen-in')
    expect(within(row).getByText('BOM')).toBeInTheDocument()
    expect(within(row).getByTestId('dev-badge')).toBeInTheDocument()
    expect(within(row).getByText('bom')).toBeInTheDocument()
    expect(within(row).getByTitle(BOM_PATH)).toHaveTextContent(BOM_PATH)
    // SEC-H3: a fresh registration is gated behind its permissions, so the
    // row offers the acknowledgement button (not Reload) plus Remove.
    expect(within(row).getByRole('button', { name: ACK_BUTTON })).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
    expect(screen.queryByText('No unpacked extensions loaded.')).not.toBeInTheDocument()
  })

  it('lists validation problems verbatim, one per line, and marks a never-loaded row', async () => {
    registered('broken', BROKEN_PATH)
    answers[BROKEN_PATH] = { ok: false, problems: PROBLEMS }
    render(<DeveloperSection />)

    const row = await screen.findByTestId('dev-ext-broken')

    expect(within(row).getByText('Not loaded')).toBeInTheDocument()
    for (const problem of PROBLEMS) expect(within(row).getByText(problem)).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Pick again' })).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  })
})

describe('DeveloperSection — load unpacked extension', () => {
  it('picks a folder and loads it', async () => {
    pick.mockResolvedValue(BOM_PATH)
    answers[BOM_PATH] = LOADED_BOM
    render(<DeveloperSection />)

    await userEvent.click(screen.getByRole('button', { name: 'Load unpacked extension…' }))

    await waitFor(() => expect(screen.getByTestId('dev-ext-bom')).toBeInTheDocument())
    expect(extensions.devLoad).toHaveBeenCalledWith(BOM_PATH)
  })

  it('does nothing when the picker is cancelled', async () => {
    pick.mockResolvedValue(null)
    render(<DeveloperSection />)

    await userEvent.click(screen.getByRole('button', { name: 'Load unpacked extension…' }))

    await waitFor(() => expect(pick).toHaveBeenCalledTimes(1))
    expect(extensions.devLoad).not.toHaveBeenCalled()
  })

  it('shows a refused folder inline with the reason and no row', async () => {
    const refusal = 'path: must be an existing directory that is not the filesystem root'
    pick.mockResolvedValue('/Users/maya')
    answers['/Users/maya'] = { ok: false, problems: [refusal] }
    render(<DeveloperSection />)

    await userEvent.click(screen.getByRole('button', { name: 'Load unpacked extension…' }))

    const notice = await screen.findByRole('alert')
    expect(notice).toHaveTextContent('/Users/maya')
    expect(notice).toHaveTextContent('not loaded')
    expect(notice).toHaveTextContent(refusal)
    expect(screen.queryByTestId(/dev-ext-/)).not.toBeInTheDocument()
  })

  it('clears the inline notice once a later load succeeds', async () => {
    pick.mockResolvedValueOnce('/Users/maya').mockResolvedValueOnce(BOM_PATH)
    answers['/Users/maya'] = { ok: false, problems: ['path: refused'] }
    answers[BOM_PATH] = LOADED_BOM
    render(<DeveloperSection />)
    const button = screen.getByRole('button', { name: 'Load unpacked extension…' })

    await userEvent.click(button)
    await screen.findByRole('alert')
    await userEvent.click(button)

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByTestId('dev-ext-bom')).toBeInTheDocument()
  })
})

describe('DeveloperSection — row actions', () => {
  it('reloads a row through the store and shows fresh problems on the row', async () => {
    registered('bom', BOM_PATH)
    answers[BOM_PATH] = LOADED_BOM
    render(<DeveloperSection />)
    await screen.findByTestId('dev-ext-bom')
    await userEvent.click(screen.getByRole('button', { name: ACK_BUTTON }))
    answers[BOM_PATH] = { ok: false, problems: PROBLEMS }

    await userEvent.click(await screen.findByRole('button', { name: 'Reload' }))

    const row = screen.getByTestId('dev-ext-bom')
    await waitFor(() => expect(within(row).getByText(PROBLEMS[0])).toBeInTheDocument())
    expect(within(row).getByText(PROBLEMS[1])).toBeInTheDocument()
    expect(within(row).getByText('BOM')).toBeInTheDocument()
    expect(extensions.devLoad).toHaveBeenLastCalledWith(BOM_PATH)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('removes a row through the store', async () => {
    registered('bom', BOM_PATH)
    answers[BOM_PATH] = LOADED_BOM
    render(<DeveloperSection />)
    await screen.findByTestId('dev-ext-bom')

    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(extensions.devRemove).toHaveBeenCalledWith('bom'))
    await waitFor(() => expect(screen.queryByTestId('dev-ext-bom')).not.toBeInTheDocument())
    expect(screen.getByText('No unpacked extensions loaded.')).toBeInTheDocument()
  })

  it('tells the user when main refuses to remove', async () => {
    registered('bom', BOM_PATH)
    answers[BOM_PATH] = LOADED_BOM
    extensions.devRemove = vi.fn(async () => ({ ok: false }))
    render(<DeveloperSection />)
    await screen.findByTestId('dev-ext-bom')

    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not remove/)
    expect(screen.getByTestId('dev-ext-bom')).toBeInTheDocument()
  })
})

describe('DeveloperSection — permissions acknowledgement (SEC-H3)', () => {
  const declared = fakeManifest({
    permissions: { scopes: ['graph.read', 'sol.ask'], network: ['https://api.example.com'] }
  })

  it('gates a freshly loaded registration behind its declared scopes and origins', async () => {
    registered('bom', BOM_PATH)
    answers[BOM_PATH] = { ok: true, manifest: declared, devPath: BOM_PATH }
    render(<DeveloperSection />)

    const row = await screen.findByTestId('dev-ext-bom')
    const gate = within(row).getByTestId('dev-ext-ack')

    expect(gate).toHaveTextContent(ACK_COPY)
    expect(within(gate).getByText('graph.read')).toBeInTheDocument()
    expect(within(gate).getByText('sol.ask')).toBeInTheDocument()
    expect(within(gate).getByText('https://api.example.com')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: ACK_BUTTON })).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: 'Reload' })).not.toBeInTheDocument()
    expect(selectDevRegistration(useDevExtensionsStore.getState(), 'bom')).toBeNull()
  })

  it('says so when a manifest declares no scopes and no origins', async () => {
    registered('bom', BOM_PATH)
    answers[BOM_PATH] = {
      ok: true,
      manifest: fakeManifest({ permissions: { scopes: [], network: [] } }),
      devPath: BOM_PATH
    }
    render(<DeveloperSection />)
    const gate = within(await screen.findByTestId('dev-ext-bom')).getByTestId('dev-ext-ack')
    expect(gate).toHaveTextContent('No scopes')
    expect(gate).toHaveTextContent('No network origins')
  })

  it('"Run with these permissions" acknowledges once; the row then offers Reload', async () => {
    registered('bom', BOM_PATH)
    answers[BOM_PATH] = { ok: true, manifest: declared, devPath: BOM_PATH }
    render(<DeveloperSection />)
    const row = await screen.findByTestId('dev-ext-bom')

    await userEvent.click(within(row).getByRole('button', { name: ACK_BUTTON }))

    await waitFor(() => expect(within(row).queryByTestId('dev-ext-ack')).not.toBeInTheDocument())
    expect(within(row).getByRole('button', { name: 'Reload' })).toBeInTheDocument()
    expect(selectDevRegistration(useDevExtensionsStore.getState(), 'bom')).not.toBeNull()

    await userEvent.click(within(row).getByRole('button', { name: 'Reload' }))
    await waitFor(() => expect(extensions.devLoad).toHaveBeenCalledTimes(2))
    expect(within(row).queryByTestId('dev-ext-ack')).not.toBeInTheDocument()
  })

  it('a never-loaded row has no gate: there is nothing to run', async () => {
    registered('broken', BROKEN_PATH)
    answers[BROKEN_PATH] = { ok: false, problems: PROBLEMS }
    render(<DeveloperSection />)
    const row = await screen.findByTestId('dev-ext-broken')
    expect(within(row).queryByTestId('dev-ext-ack')).not.toBeInTheDocument()
  })
})
