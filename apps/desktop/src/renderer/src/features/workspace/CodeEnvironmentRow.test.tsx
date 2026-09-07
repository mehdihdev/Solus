// SOLUSDEV-250 (I3) — the "Code environment" row under Home › Connected
// accounts › Software: rendered only when this machine holds the project's
// local source, with a status line that says what is actually known, a red
// conflict line when the graph found pins that disagree, and Details opening
// the modal.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Source } from '../../lib/api/resources'
import {
  EMPTY_CODE_ENVIRONMENT_VIEW,
  type CodeEnvironmentView
} from '../../lib/api/resources.codeenv'
import * as hook from '../project/useCodeEnvironment'
import { CodeEnvironmentRow } from './CodeEnvironmentRow'
import * as handoff from './codeEnvironmentSol'

vi.mock('../project/useCodeEnvironment', () => ({ useCodeEnvironment: vi.fn() }))
vi.mock('./codeEnvironmentSol', () => ({ handOffToSol: vi.fn(async () => undefined) }))

const SOURCE: Source = {
  id: 's1',
  project_id: 'p1',
  type: 'local',
  name: 'mehdi-mbp',
  status: 'connected',
  config: { machine_id: 'm1', machine_name: 'mehdi-mbp', folder_name: 'rover-fw' },
  account_login: null,
  last_synced_at: null,
  last_error: null,
  created_at: '',
  updated_at: ''
}

const LIVE: CodeEnvironmentView = {
  ...EMPTY_CODE_ENVIRONMENT_VIEW,
  source: SOURCE,
  bridge: { connected: true, code_server: true },
  probe: {
    python: { path: '/usr/bin/python3', version: '3.12.4' },
    interpreters: [],
    venv: { path: '.venv', python_version: '3.12.4', packages: [], truncated: false },
    conda: null,
    uv: null
  },
  requirements: { count: 3, files: ['requirements.txt'] }
}

const WARNING = {
  checker_id: 'pin_conflict',
  severity: 'warning' as const,
  message: 'torch is pinned differently',
  evidence: {},
  suggested_area: null
}

function mockHook(over: Partial<hook.CodeEnvironmentController> = {}): void {
  vi.mocked(hook.useCodeEnvironment).mockReturnValue({
    view: LIVE,
    status: 'ready',
    source: SOURCE,
    refresh: vi.fn(async () => undefined),
    ...over
  })
}

beforeEach(() => {
  vi.mocked(handoff.handOffToSol).mockClear()
})

describe('CodeEnvironmentRow', () => {
  it('renders nothing when this machine holds no local source for the project', () => {
    mockHook({ source: null, view: null, status: 'idle' })
    const { container } = render(<CodeEnvironmentRow projectId="p1" sources={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('leads with the Py mark, the title and the live summary', () => {
    mockHook()
    render(<CodeEnvironmentRow projectId="p1" sources={[SOURCE]} />)
    expect(screen.getByText('Py')).toBeInTheDocument()
    expect(screen.getByText('Code environment')).toBeInTheDocument()
    expect(screen.getByText('3.12.4 · .venv · 3 requirements')).toBeInTheDocument()
    expect(screen.queryByTestId('code-env-conflicts')).toBeNull()
  })

  it('says the companion is offline, the code server is down, or nothing was probed', () => {
    mockHook({ view: { ...LIVE, bridge: { connected: false, code_server: false } } })
    const { rerender } = render(<CodeEnvironmentRow projectId="p1" sources={[SOURCE]} />)
    expect(screen.getByText('Solus companion is offline on this machine')).toBeInTheDocument()

    mockHook({ view: { ...LIVE, bridge: { connected: true, code_server: false } } })
    rerender(<CodeEnvironmentRow projectId="p1" sources={[SOURCE]} />)
    expect(screen.getByText('code server not running')).toBeInTheDocument()

    mockHook({ view: { ...LIVE, probe: null } })
    rerender(<CodeEnvironmentRow projectId="p1" sources={[SOURCE]} />)
    expect(screen.getByText('not probed yet')).toBeInTheDocument()

    mockHook({ view: null, status: 'offline' })
    rerender(<CodeEnvironmentRow projectId="p1" sources={[SOURCE]} />)
    expect(screen.getByText("Solus can't reach its API")).toBeInTheDocument()
  })

  it('adds a red conflict line when pins disagree', () => {
    mockHook({
      view: {
        ...LIVE,
        conflicts: [WARNING, WARNING],
        proposal: { environments: [], split: true }
      }
    })
    render(<CodeEnvironmentRow projectId="p1" sources={[SOURCE]} />)
    const line = screen.getByTestId('code-env-conflicts')
    expect(line).toHaveTextContent('2 dependency conflicts — split proposed')
    expect(line).toHaveStyle({ color: 'var(--err)' })
  })
})

describe('CodeEnvironmentRow — Details', () => {
  it('Details opens the modal, whose Ask SOL hands off with the navigator', async () => {
    mockHook({
      view: {
        ...LIVE,
        conflicts: [WARNING],
        proposal: { environments: [], split: true }
      }
    })
    const onNavigate = vi.fn()
    render(<CodeEnvironmentRow projectId="p1" sources={[SOURCE]} onNavigate={onNavigate} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Code environment' }))
    const dialog = screen.getByRole('dialog', { name: 'Code environment' })
    expect(dialog).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Ask SOL to set it up' }))
    expect(handoff.handOffToSol).toHaveBeenCalledWith({ navigate: onNavigate })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('Details is offered even before a probe — the modal says what is missing', async () => {
    mockHook({ view: { ...LIVE, probe: null, bridge: { connected: false, code_server: false } } })
    render(<CodeEnvironmentRow projectId="p1" sources={[SOURCE]} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Code environment' }))
    expect(screen.getByRole('dialog', { name: 'Code environment' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('has no Details while the view is still unknown', () => {
    mockHook({ view: null, status: 'loading' })
    render(<CodeEnvironmentRow projectId="p1" sources={[SOURCE]} />)
    expect(screen.getByText('Loading…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Details for Code environment' })).toBeDisabled()
  })
})
