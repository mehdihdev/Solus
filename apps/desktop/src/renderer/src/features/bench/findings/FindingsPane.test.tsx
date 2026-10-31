// SOLUSDEV-321 P2-T7 — the Live Bench Findings pane: one open-findings read per connected robot,
// grouped by severity with count and last seen (infos collapsed, so they never push observer
// findings off the pane), "✓ Nothing out of range" for a robot with none, the six actions on
// their routes, live refetch on the findings key through the one stream the pane mounts, the
// marker-opened finding, and "could not check" read on request only.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../../lib/api/client'
import * as findingsApi from '../../../lib/api/findings'
import type { Finding } from '../../../lib/api/findings'
import * as resources from '../../../lib/api/resources'
import type { BenchSession } from '../../../lib/api/resources'
import * as localFolder from '../../../lib/api/resources.localfolder'
import { getDesktopSolBridge } from '../../../lib/desktopBridge'
import { useAuthStore } from '../../../store/authStore'
import { resetLiveRevisions } from '../../../store/liveRevisionStore'
import { useSettingsStore } from '../../../store/settingsStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { findingsLiveKey } from '../../graph/useFindings'
import { useWorkspaceEvents } from '../../graph/useWorkspaceEvents'
import { bumpLive } from '../../live/testBump'
import * as chat from '../../sol/solChatStore'
import { NOTHING_OUT_OF_RANGE } from '../DeviceBenchView'
import { EXPLAIN_FINDING_PROMPT, FIX_FINDING_PROMPT } from './findingActions'
import { FindingsPane } from './FindingsPane'

vi.mock('../../../lib/api/findings', () => ({
  listFindings: vi.fn(),
  getFinding: vi.fn(),
  dismissFinding: vi.fn(),
  resolveFinding: vi.fn()
}))
vi.mock('../../../lib/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/client')>()),
  api: { request: vi.fn(), requestPage: vi.fn() }
}))
vi.mock('../../../lib/api/resources', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/api/resources')>()),
  addSolusEntry: vi.fn()
}))
vi.mock('../../../lib/api/resources.localfolder', () => ({ openLocalFolderEntity: vi.fn() }))
vi.mock('../../../lib/desktopBridge', () => ({ getDesktopSolBridge: vi.fn() }))
vi.mock('../../graph/useWorkspaceEvents', () => ({ useWorkspaceEvents: vi.fn(() => null) }))
vi.mock('../../sol/solChatStore', () => ({
  sendMessage: vi.fn(),
  selectSession: () => ({}),
  useSolChatStore: { getState: () => ({ sessions: {} }) }
}))

const CODE = '3f1c2b4a-5d6e-4f70-8a9b-0c1d2e3f4a5b'
const SOURCE = '7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d'

const finding = (over: Partial<Finding>): Finding => ({
  id: 'f',
  rule_id: 'rule',
  severity: 'warning',
  source: 'observer',
  status: 'open',
  headline: 'h',
  explanation: '',
  detail: '',
  subjects: ['e1'],
  evidence: {},
  count: 1,
  first_seen: '2026-10-27T10:00:00+00:00',
  last_seen: '2026-10-27T10:00:00+00:00',
  matrix_cell: null,
  domain: 'electrical',
  dismissed_until: null,
  created_at: '',
  updated_at: '',
  ...over
})

const STALL = finding({
  id: 'f-stall',
  rule_id: 'tracking_error_stall',
  severity: 'critical',
  headline: 'servo 3 stalls against its command',
  count: 4,
  last_seen: '2026-10-27T10:00:09+00:00',
  evidence: {
    current_a: 2.4,
    code_site: { entity_id: CODE, source_id: SOURCE, path: 'fw/arm.ino' }
  }
})
const FROZEN = finding({ id: 'f-frozen', headline: 'servo 5 position frozen' })
const INFO = finding({
  id: 'f-info',
  severity: 'info',
  source: 'checker',
  headline: 'servo 2 temperature rating unknown'
})

const session = (over: Partial<BenchSession>): BenchSession => ({
  id: 's',
  mode: 'real',
  provider: 'robot',
  status: 'active',
  link: 'streaming',
  label: 'Fake arm',
  created_at: '',
  ended_at: null,
  device: null,
  device_ids: [],
  counts: { ingested: 0, unresolved: 0 },
  last_summary: null,
  ...over
})

const SESSIONS = [
  session({ id: 's1', robot_entity_id: 'r1', label: 'Fake arm' }),
  session({ id: 's2', mode: 'sim', provider: 'mujoco', robot_entity_id: null, label: 'Sim' }),
  session({ id: 's3', robot_entity_id: 'r2', label: 'Second arm' })
]

function routeFindings(byRobot: Record<string, Finding[] | Error>): void {
  vi.mocked(findingsApi.listFindings).mockImplementation(async (_project, filters) => {
    const result = byRobot[filters?.robot ?? '']
    if (result instanceof Error) throw result
    return result ?? []
  })
}

const card = (headline: string): HTMLElement =>
  screen.getByRole('button', { name: headline }).closest('article') as HTMLElement

beforeEach(() => {
  vi.clearAllMocks()
  resetLiveRevisions()
  useAuthStore.setState({ status: 'authenticated', accessToken: null, user: { email: 'a@b.c' } })
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'P' } })
  useSettingsStore.setState({ solMode: 'Expert' })
  vi.mocked(getDesktopSolBridge).mockReturnValue({ open: vi.fn() } as never)
  vi.mocked(chat.sendMessage).mockResolvedValue(true)
})

describe('FindingsPane', () => {
  it('reads open findings per connected robot and groups them by severity', async () => {
    routeFindings({ r1: [FROZEN, INFO, STALL], r2: [] })
    render(<FindingsPane projectId="p1" sessions={SESSIONS} />)
    const arm = await screen.findByRole('region', { name: 'Findings for Fake arm' })
    expect(findingsApi.listFindings).toHaveBeenCalledWith('p1', { status: 'open', robot: 'r1' })
    expect(findingsApi.listFindings).toHaveBeenCalledWith('p1', { status: 'open', robot: 'r2' })
    expect(findingsApi.listFindings).toHaveBeenCalledTimes(2) // the sim session observes no robot
    const headings = within(arm)
      .getAllByText(/^(CRITICAL|WARNING|INFO) · \d+/)
      .map((node) => node.textContent?.split(' · last seen')[0])
    expect(headings).toEqual(['CRITICAL · 1', 'WARNING · 1', 'INFO · 1'])
    expect(
      within(arm)
        .getByText(/^CRITICAL · 1/)
        .querySelector('time')
    ).toHaveAttribute('datetime', '2026-10-27T10:00:09+00:00')
    // Checker infos sit collapsed below, so they never push the observer findings off the pane.
    const info = card('servo 2 temperature rating unknown')
    expect(info.closest('details')).not.toHaveAttribute('open')
    expect(card('servo 3 stalls against its command').closest('details')).toBeNull()
    expect(screen.getByText('FINDINGS · 3 OPEN')).toBeInTheDocument()
  })

  it('shows ✓ Nothing out of range for a robot with none, and unavailable for a failed read', async () => {
    routeFindings({ r1: new Error('offline'), r2: [] })
    render(<FindingsPane projectId="p1" sessions={SESSIONS} />)
    const second = await screen.findByRole('region', { name: 'Findings for Second arm' })
    expect(await within(second).findByText(NOTHING_OUT_OF_RANGE)).toBeInTheDocument()
    const arm = screen.getByRole('region', { name: 'Findings for Fake arm' })
    expect(await within(arm).findByRole('alert')).toHaveTextContent(/unavailable/)
    expect(within(arm).queryByText(NOTHING_OUT_OF_RANGE)).not.toBeInTheDocument()
  })

  it('renders nothing without a connected robot or an opened finding', () => {
    const { container } = render(<FindingsPane projectId="p1" sessions={[SESSIONS[1]]} />)
    expect(container).toBeEmptyDOMElement()
    expect(findingsApi.listFindings).not.toHaveBeenCalled()
  })
})

describe('FindingsPane actions', () => {
  it('puts each of the six actions on its route', async () => {
    routeFindings({ r1: [STALL], r2: [] })
    vi.mocked(localFolder.openLocalFolderEntity).mockResolvedValue({
      launched: false,
      tool: 'system',
      reason: 'The companion is not running on this machine'
    })
    vi.mocked(findingsApi.dismissFinding).mockResolvedValue(STALL)
    vi.mocked(findingsApi.resolveFinding).mockResolvedValue(STALL)
    render(<FindingsPane projectId="p1" sessions={SESSIONS} />)
    await screen.findByRole('button', { name: STALL.headline })
    const actions = within(card(STALL.headline))
    const anchors = { findingId: 'f-stall', forceConfirmation: false }

    fireEvent.click(actions.getByRole('button', { name: 'Explain more' }))
    await waitFor(() =>
      expect(chat.sendMessage).toHaveBeenLastCalledWith(
        'p1',
        EXPLAIN_FINDING_PROMPT,
        'guide',
        [],
        false,
        undefined,
        anchors
      )
    )
    fireEvent.click(actions.getByRole('button', { name: 'Propose a fix' }))
    await waitFor(() =>
      expect(chat.sendMessage).toHaveBeenLastCalledWith(
        'p1',
        FIX_FINDING_PROMPT,
        'do',
        [],
        false,
        undefined,
        anchors
      )
    )
    fireEvent.click(actions.getByRole('button', { name: 'Open the tool' }))
    expect(
      await actions.findByText('The companion is not running on this machine')
    ).toBeInTheDocument()
    expect(localFolder.openLocalFolderEntity).toHaveBeenCalledWith('p1', SOURCE, {
      entity_id: CODE,
      tool: 'system'
    })
    fireEvent.click(actions.getByRole('button', { name: 'File' }))
    await waitFor(() =>
      expect(resources.addSolusEntry).toHaveBeenCalledExactlyOnceWith('p1', 'errors', {
        kind: 'text',
        text: `${STALL.headline}\nfinding: f-stall`
      })
    )
    const reads = vi.mocked(findingsApi.listFindings).mock.calls.length
    fireEvent.click(actions.getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(findingsApi.dismissFinding).toHaveBeenCalledWith('p1', 'f-stall'))
    await waitFor(() =>
      expect(vi.mocked(findingsApi.listFindings).mock.calls.length).toBeGreaterThan(reads)
    )
    fireEvent.click(actions.getByRole('button', { name: 'Resolve with note' }))
    fireEvent.change(actions.getByLabelText('Resolution note'), { target: { value: 'Re-seated' } })
    fireEvent.click(actions.getByRole('button', { name: 'Resolve' }))
    await waitFor(() =>
      expect(findingsApi.resolveFinding).toHaveBeenCalledWith('p1', 'f-stall', {
        note: 'Re-seated'
      })
    )
    // Dismiss wrote nothing else and Resolve's one errors entry is filed by its route.
    expect(resources.addSolusEntry).toHaveBeenCalledOnce()
  })
})

describe('FindingsPane live reads', () => {
  it('refetches on the findings live key through the one stream it mounts', async () => {
    routeFindings({ r1: [STALL], r2: [] })
    const { rerender } = render(<FindingsPane projectId="p1" sessions={SESSIONS} />)
    await screen.findByRole('button', { name: STALL.headline })
    // One stream for the pane, not one per robot: SESSIONS holds two robots, so a stream per
    // robot section would subscribe twice in the one render below.
    vi.mocked(useWorkspaceEvents).mockClear()
    rerender(<FindingsPane projectId="p1" sessions={SESSIONS} />)
    expect(vi.mocked(useWorkspaceEvents).mock.calls).toEqual([['p1', expect.any(Function)]])
    routeFindings({ r1: [], r2: [] })
    await bumpLive(findingsLiveKey('p1'))
    expect(await screen.findAllByText(NOTHING_OUT_OF_RANGE)).toHaveLength(2)
    // graph.changed reaches the pane's refetch directly as well.
    routeFindings({ r1: [FROZEN], r2: [] })
    const onChanged = vi.mocked(useWorkspaceEvents).mock.calls.at(-1)?.[1]
    expect(onChanged).toBeTypeOf('function') // never a silent no-op call below
    onChanged?.()
    expect(await screen.findByRole('button', { name: FROZEN.headline })).toBeInTheDocument()
  })

  it('opens a marker’s finding by id, expanded, until closed', async () => {
    routeFindings({ r1: [], r2: [] })
    vi.mocked(findingsApi.getFinding).mockResolvedValue({ ...STALL, status: 'dismissed' })
    const onClose = vi.fn()
    render(
      <FindingsPane
        projectId="p1"
        sessions={SESSIONS}
        selectedFindingId="f-stall"
        onCloseSelected={onClose}
      />
    )
    const opened = await screen.findByRole('region', { name: 'Opened finding' })
    expect(findingsApi.getFinding).toHaveBeenCalledWith('p1', 'f-stall')
    expect(within(opened).getByRole('list', { name: 'Evidence' })).toBeInTheDocument()
    fireEvent.click(within(opened).getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('reads what could not be checked only when asked', async () => {
    routeFindings({ r1: [], r2: [] })
    vi.mocked(api.request).mockResolvedValue({
      properties: { missing_signals: ['servo 2: temperature', 'servo 5: stall_current_a'] }
    })
    render(<FindingsPane projectId="p1" sessions={SESSIONS} />)
    const arm = await screen.findByRole('region', { name: 'Findings for Fake arm' })
    expect(api.request).not.toHaveBeenCalled()
    fireEvent.click(within(arm).getByRole('button', { name: 'Could not check' }))
    const list = await within(arm).findByRole('list', { name: 'Could not check' })
    expect(api.request).toHaveBeenCalledExactlyOnceWith('/projects/p1/entities/r1')
    expect([...list.querySelectorAll('li')].map((item) => item.textContent)).toEqual([
      'servo 2: temperature',
      'servo 5: stall_current_a'
    ])
  })
})
