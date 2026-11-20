// SOLUSDEV-329 — Settings › Python for local tools (docs/wireflows/settings.md),
// driven through a fake window.solus.mcpRuntime bridge.
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PythonToolsSection } from './PythonToolsSection'
import { usePythonTools } from './usePythonTools'
import * as events from './pythonToolsEvents'
import { useSettingsStore } from '../../../store/settingsStore'
import type {
  Candidate,
  ChoiceView,
  ForkStatus,
  McpRuntimeBridge,
  ProgressPush,
  RuntimeEvent
} from '../../../../../main/mcpRuntime/channels'

vi.mock('./pythonToolsEvents', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./pythonToolsEvents')>()),
  reportInterpreterChosen: vi.fn(),
  reportManagedConsent: vi.fn(),
  reportSetupFinished: vi.fn()
}))

const cand = (over: Partial<Candidate>): Candidate => ({
  type: 'candidate',
  path: '/opt/homebrew/bin/python3.12',
  version: '3.12.7',
  implementation: 'cpython',
  source: 'known_location',
  supported: true,
  reason: null,
  ...over
})
const PY312 = cand({})
const PY313 = cand({ path: '/usr/local/bin/python3.13', version: '3.13.1', source: 'path' })
const PY39 = cand({
  path: '/usr/bin/python3',
  version: '3.9.6',
  source: 'path',
  supported: false,
  reason: 'python_unsupported_version'
})

const fork = (name: string, over: Partial<ForkStatus> = {}): ForkStatus => ({
  type: 'status',
  fork: name,
  state: 'ready',
  detail: null,
  base_version: '3.12.7',
  managed: false,
  ...over
})

const AUTO_CHOICE: ChoiceView = { mode: 'auto', path: null, writable: true }

interface Fake extends McpRuntimeBridge {
  push(event: RuntimeEvent, runId?: string): void
}

function fakeBridge(
  init: {
    candidates?: Candidate[]
    forks?: ForkStatus[]
    choice?: ChoiceView
  } = {}
): Fake {
  let handler: ((p: ProgressPush) => void) | null = null
  return {
    detect: vi.fn(async () => ({ candidates: init.candidates ?? [PY39, PY312, PY313] })),
    status: vi.fn(async () => ({ forks: init.forks ?? [fork('kicad'), fork('code')] })),
    getChoice: vi.fn(async () => init.choice ?? AUTO_CHOICE),
    choose: vi.fn(async () => ({ ok: true as const, version_minor: '3.12' as const })),
    provision: vi.fn(async () => ({ runId: 'run-1' })),
    installManaged: vi.fn(async () => ({ runId: 'run-m' })),
    cancel: vi.fn(async () => ({ ok: true })),
    onProgress: (h) => {
      handler = h
      return () => (handler = null)
    },
    push(event, runId = 'run-1') {
      act(() => handler?.({ runId, event }))
    }
  }
}

function Harness({ bridge }: { bridge: McpRuntimeBridge }): React.JSX.Element {
  const tools = usePythonTools(bridge)
  return <PythonToolsSection tools={tools} />
}

async function renderWith(bridge: Fake): Promise<void> {
  render(<Harness bridge={bridge} />)
  await waitFor(() => expect(screen.queryByTestId('python-detecting')).toBeNull())
}

const DONE = (outcome: string, ok: number, failed: number): RuntimeEvent =>
  ({ type: 'done', outcome, ok, failed, skipped: 0 }) as RuntimeEvent

beforeEach(() => {
  vi.clearAllMocks()
  useSettingsStore.setState({ solMode: 'Expert' })
})

describe('detecting', () => {
  it('shows a skeleton while detect and status run', () => {
    const bridge = fakeBridge()
    bridge.detect = vi.fn(() => new Promise<never>(() => undefined))
    render(<Harness bridge={bridge} />)
    expect(screen.getByTestId('python-detecting')).toBeInTheDocument()
  })
})

describe('none found', () => {
  const none = (): Fake => fakeBridge({ candidates: [cand({ ...PY39 })] })

  it('offers the managed Python, naming the download and its size', async () => {
    await renderWith(none())
    expect(screen.getByText('No Python 3.12 or 3.13 found.')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Install Python for Solus.*30 MB/ })
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Choose…' })).toBeInTheDocument()
  })

  it('installs nothing until the user consents', async () => {
    const bridge = none()
    await renderWith(bridge)
    await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(events.reportManagedConsent).toHaveBeenCalledWith(false)
    expect(bridge.installManaged).not.toHaveBeenCalled()
  })

  it('consent installs, then chooses the managed Python and offers setup', async () => {
    const bridge = none()
    await renderWith(bridge)
    await userEvent.click(screen.getByRole('button', { name: /Install Python for Solus/ }))
    expect(events.reportManagedConsent).toHaveBeenCalledWith(true)
    expect(bridge.installManaged).toHaveBeenCalledWith({ consent: true })
    bridge.push({ type: 'progress', fork: null, step: 'download', done: 5, total: 30 }, 'run-m')
    expect(screen.getByText(/download/i)).toBeInTheDocument()
    bridge.push(DONE('ok', 1, 0), 'run-m')
    await waitFor(() => expect(bridge.choose).toHaveBeenCalledWith({ mode: 'managed' }))
    expect(events.reportInterpreterChosen).toHaveBeenCalledWith('managed', '3.12')
    expect(await screen.findByRole('button', { name: 'Set up now' })).toBeInTheDocument()
  })
})

describe('candidates', () => {
  it('lists supported interpreters first and unsupported ones dimmed with the reason', async () => {
    await renderWith(fakeBridge())
    const radios = screen.getAllByRole('radio')
    expect(radios.map((r) => r.getAttribute('value'))).toEqual([
      PY312.path,
      PY313.path,
      'managed',
      PY39.path
    ])
    expect(screen.getByRole('radio', { name: /\/usr\/bin\/python3/ })).toBeDisabled()
    expect(screen.getByText('3.9 — Solus needs 3.12 or 3.13')).toBeInTheDocument()
  })

  it('choosing a detected interpreter saves it, reports it and offers setup', async () => {
    const bridge = fakeBridge()
    await renderWith(bridge)
    await userEvent.click(screen.getByRole('radio', { name: /python3\.13/ }))
    expect(bridge.choose).toHaveBeenCalledWith({ mode: 'path', path: PY313.path })
    await waitFor(() =>
      expect(events.reportInterpreterChosen).toHaveBeenCalledWith('detected', '3.12')
    )
    expect(await screen.findByRole('button', { name: 'Set up now' })).toBeInTheDocument()
    expect(screen.getAllByText('Needs setup')).toHaveLength(2)
  })

  it('a cancelled or failed setup keeps the new choice marked as needing setup', async () => {
    // Old envs still pass trust, so status says ready; only a fully ok run on the
    // new base may clear the marking (SOLUSDEV-329 Phase 4).
    for (const outcome of ['cancelled', 'failed', 'partial']) {
      const bridge = fakeBridge()
      const { unmount } = render(<Harness bridge={bridge} />)
      await waitFor(() => expect(screen.queryByTestId('python-detecting')).toBeNull())
      await userEvent.click(screen.getByRole('radio', { name: /python3\.13/ }))
      await userEvent.click(await screen.findByRole('button', { name: 'Set up now' }))
      const refreshes = vi.mocked(bridge.status).mock.calls.length
      bridge.push(DONE(outcome, 0, 1))
      await waitFor(() => expect(vi.mocked(bridge.status).mock.calls.length).toBeGreaterThan(refreshes))
      expect(screen.getAllByText('Needs setup')).toHaveLength(2)
      unmount()
    }
  })

  it('Choose… asks main for its picker and reports a picked interpreter', async () => {
    const bridge = fakeBridge()
    bridge.choose = vi.fn(async () => ({ ok: true as const, version_minor: '3.13' as const }))
    await renderWith(bridge)
    await userEvent.click(screen.getByRole('button', { name: 'Choose…' }))
    expect(bridge.choose).toHaveBeenCalledWith({ mode: 'path' })
    await waitFor(() =>
      expect(events.reportInterpreterChosen).toHaveBeenCalledWith('picked', '3.13')
    )
  })

  it('an unsupported pick shows the reason and is not reported', async () => {
    const bridge = fakeBridge()
    bridge.choose = vi.fn(async () => ({
      ok: false as const,
      error_code: 'python_unsupported_version' as const
    }))
    await renderWith(bridge)
    await userEvent.click(screen.getByRole('button', { name: 'Choose…' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/3\.12 or 3\.13/)
    expect(events.reportInterpreterChosen).not.toHaveBeenCalled()
  })

  it('a cancelled picker shows nothing', async () => {
    const bridge = fakeBridge()
    bridge.choose = vi.fn(async () => ({ ok: false as const, error_code: 'cancelled' as const }))
    await renderWith(bridge)
    await userEvent.click(screen.getByRole('button', { name: 'Choose…' }))
    await waitFor(() => expect(bridge.choose).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('installing', () => {
  it('shows per-tool progress, disables other rows, and Cancel cancels the run', async () => {
    const bridge = fakeBridge({
      forks: [
        fork('kicad', { state: 'needs_setup', detail: 'needs_setup:no_env', base_version: null })
      ]
    })
    await renderWith(bridge)
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    expect(bridge.provision).toHaveBeenCalledWith({ trigger: 'settings' })
    bridge.push({ type: 'progress', fork: 'kicad', step: 'install', done: 12, total: 58 })
    const row = screen.getByTestId('python-fork-kicad')
    expect(within(row).getByText(/install 12\/58/i)).toBeInTheDocument()
    for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(bridge.cancel).toHaveBeenCalledWith({ runId: 'run-1' })
  })
})

describe('partial / failed', () => {
  async function partial(bridge: Fake): Promise<void> {
    await renderWith(bridge)
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    bridge.push({
      type: 'fork_result',
      fork: 'kicad',
      outcome: 'ok',
      error_code: null,
      message: ''
    })
    bridge.push({
      type: 'fork_result',
      fork: 'local',
      outcome: 'failed',
      error_code: 'venv_copies_unhealthy',
      message: '<b>The copied interpreter could not start.</b>'
    })
    bridge.push(DONE('partial', 1, 1))
  }
  const needing = (): Fake =>
    fakeBridge({
      forks: [
        fork('kicad', { state: 'needs_setup', detail: 'needs_setup:no_env' }),
        fork('local', { state: 'needs_setup', detail: 'needs_setup:no_env' })
      ]
    })

  it('shows each failed tool message as text with a fix hint', async () => {
    await partial(needing())
    const row = screen.getByTestId('python-fork-local')
    expect(
      within(row).getByText('<b>The copied interpreter could not start.</b>')
    ).toBeInTheDocument()
    expect(row.querySelector('b')).toBeNull()
    expect(within(row).getByText(/Solus-managed Python/)).toBeInTheDocument()
  })

  it('reports setup_finished with the first failing code', async () => {
    await partial(needing())
    expect(events.reportSetupFinished).toHaveBeenCalledWith({
      outcome: 'partial',
      failedForks: 1,
      errorCode: 'venv_copies_unhealthy',
      trigger: 'settings'
    })
  })

  it('Repair re-runs only the failed tools', async () => {
    const bridge = needing()
    await partial(bridge)
    await userEvent.click(await screen.findByRole('button', { name: 'Repair' }))
    expect(bridge.provision).toHaveBeenLastCalledWith({ trigger: 'repair', forks: ['local'] })
  })

  it('a clean run reports ok with no error code', async () => {
    const bridge = needing()
    await renderWith(bridge)
    await userEvent.click(screen.getByRole('button', { name: 'Install' }))
    bridge.push(DONE('ok', 2, 0))
    expect(events.reportSetupFinished).toHaveBeenCalledWith({
      outcome: 'ok',
      failedForks: 0,
      errorCode: null,
      trigger: 'settings'
    })
  })
})

describe('ready', () => {
  it('marks each tool ready with its base version and names OS-only tools', async () => {
    await renderWith(
      fakeBridge({
        forks: [
          fork('kicad'),
          fork('altium', { state: 'unsupported_platform', base_version: null })
        ]
      })
    )
    expect(
      within(screen.getByTestId('python-fork-kicad')).getByText(/Ready · 3\.12\.7/)
    ).toBeInTheDocument()
    expect(
      within(screen.getByTestId('python-fork-altium')).getByText('— (Windows only)')
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Install' })).toBeNull()
  })
})

describe('SOL mode copy', () => {
  it('Guide explains, Expert is terse', async () => {
    useSettingsStore.setState({ solMode: 'Guide' })
    const { unmount } = render(<Harness bridge={fakeBridge()} />)
    await waitFor(() => expect(screen.queryByTestId('python-detecting')).toBeNull())
    const guide = screen.getByTestId('python-intro').textContent
    expect(screen.getByRole('button', { name: 'Learn more' })).toBeInTheDocument()
    unmount()
    useSettingsStore.setState({ solMode: 'Expert' })
    render(<Harness bridge={fakeBridge()} />)
    await waitFor(() => expect(screen.queryByTestId('python-detecting')).toBeNull())
    const expert = screen.getByTestId('python-intro').textContent
    expect(guide).not.toBe(expert)
    expect((guide ?? '').length).toBeGreaterThan((expert ?? '').length)
    expect(screen.queryByRole('button', { name: 'Learn more' })).toBeNull()
  })
})

describe('helper unavailable', () => {
  it('says so when detect fails', async () => {
    const bridge = fakeBridge()
    bridge.detect = vi.fn(async () => Promise.reject(new Error('unavailable')))
    render(<Harness bridge={bridge} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/local tools helper/i)
  })
})
