// Live Bench: hosts the SOLUSDEV-235 widget canvas (EXT-16) — the default
// `builtin:livebench` slot mounts the LB-05 LiveBenchWidget scoped to the
// shared focus (SOLUSDEV-70 wiring), the header carries the focus/device line
// and ONE `+ Add widget` button; without a focus the device-keyed telemetry
// view for streaming sessions (SOLUSDEV-72) still takes the screen, and an
// ACTIONABLE honest empty line is shown when nothing is streaming. The honesty
// rules from SOLUSDEV-152 still bind: no fabricated devices, signals, or
// REAL/streaming labels.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { BenchScreen } from './BenchScreen'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFocusStore } from '../workspace/focusStore'
import { api } from '../../lib/api/client'
import type { BenchSession, Entity } from '../../lib/api/resources'
import {
  getWidgetLayout,
  listProjectExtensions,
  putWidgetLayout,
  type WidgetLayoutApi,
  type WidgetLayoutSlotApi
} from '../../lib/api/resources.extensions'
import { OFFLINE_NOTE } from '../canvas'

vi.mock('../../lib/api/client', () => ({
  api: { request: vi.fn(), requestPage: vi.fn() }
}))

// The canvas's own client calls (layout GET/PUT, install snapshot) — mocked at
// the resource seam so the bench tests script the layout, not the wire.
vi.mock('../../lib/api/resources.extensions', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api/resources.extensions')>()),
  getWidgetLayout: vi.fn(),
  putWidgetLayout: vi.fn(),
  listProjectExtensions: vi.fn()
}))

const requestMock = vi.mocked(api.request)
const layoutGetMock = vi.mocked(getWidgetLayout)
const layoutPutMock = vi.mocked(putWidgetLayout)
const installsMock = vi.mocked(listProjectExtensions)

const E1: Entity = {
  id: 'e1',
  type: 'part',
  domain: 'mechanical',
  name: 'elbow motor',
  source_key: 'onshape:e1'
}

const SESSION: BenchSession = {
  id: 's1',
  mode: 'sim',
  provider: 'mujoco',
  status: 'active',
  link: 'streaming',
  label: 'MuJoCo demo scene',
  created_at: '2026-08-16T00:00:00Z',
  ended_at: null,
  device: null,
  device_ids: ['demo/rod'],
  counts: { ingested: 123, unresolved: 0 },
  last_summary: null
}

const DEFAULT_SLOT: WidgetLayoutSlotApi = { ref: 'builtin:livebench', size: 'wide' }

function layoutApi(layout: WidgetLayoutSlotApi[], updatedAt: string | null): WidgetLayoutApi {
  return { project_id: 'p1', layout, updated_at: updatedAt }
}

function seedProject(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
}

function seedFocusedProject(): void {
  seedProject()
  useFocusStore.setState({
    focusedEntityId: 'e1',
    status: 'ready',
    cache: { 'p1:e1@1': { entities: [E1], edges: [], truncated: false } }
  })
}

/** Route the mocked client by path: sessions, device-recent, entity telemetry. */
function routeApi(options: { sessions?: BenchSession[] } = {}): void {
  requestMock.mockImplementation(async (path: string) => {
    if (path.includes('/bench/sessions')) return (options.sessions ?? []) as never
    if (path.includes('/bench/device-recent')) {
      // The batched route: {devices: [...]}, one entry per requested id.
      return {
        devices: [
          {
            device_id: 'demo/rod',
            resolved_entity_id: null,
            signals: [
              {
                signal: 'qvel',
                points: [{ timestamp: new Date().toISOString(), value: 1.25 }]
              }
            ]
          }
        ]
      } as never
    }
    if (path.includes('/bench/recent/')) return { entity_id: 'e1', signals: [] } as never
    return [] as never
  })
}

/** The canvas seam: a never-arranged project (server default), no installs, PUT echoes. */
function routeCanvas(stored: WidgetLayoutSlotApi[] | null = null): void {
  layoutGetMock.mockImplementation(async () =>
    stored === null ? layoutApi([], null) : layoutApi(stored, '2026-08-16T00:00:00Z')
  )
  layoutPutMock.mockImplementation(async (_p, layout) => layoutApi([...layout], 'now'))
  installsMock.mockResolvedValue({
    data: [],
    meta: { has_next: false, next_cursor: null }
  } as never)
}

const slots = (): HTMLElement[] => screen.queryAllByTestId('widget-slot')
const addWidgetButtons = (): HTMLElement[] =>
  screen.queryAllByRole('button', { name: /add widget/i })

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
  routeApi()
  routeCanvas()
})

describe('BenchScreen — empty states', () => {
  it('asks for a project when none is open, without touching the API', () => {
    render(<BenchScreen />)
    expect(screen.getByText('NO PROJECT OPEN')).toBeInTheDocument()
    expect(requestMock).not.toHaveBeenCalled()
    expect(layoutGetMock).not.toHaveBeenCalled()
    expect(addWidgetButtons()).toHaveLength(0)
  })

  it('with no focus and nothing streaming, offers Connect a device honestly', async () => {
    seedProject()
    const onNavigate = vi.fn()
    render(<BenchScreen onNavigate={onNavigate} />)
    // The session check ran and found nothing — the copy says so.
    await waitFor(() =>
      expect(requestMock).toHaveBeenCalledWith('/projects/p1/bench/sessions?status=active')
    )
    expect(await screen.findByText('NOTHING STREAMING')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Connect a device' }))
    expect(onNavigate).toHaveBeenCalledWith('sources')
    // The canvas is still there underneath: the default Live Bench slot, unfocused.
    expect(await screen.findByText('Focus a part to watch its telemetry.')).toBeInTheDocument()
  })

  it('contains no fabricated devices, signals, or REAL/streaming labels', () => {
    const { container } = render(<BenchScreen />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/STRIDER/i)
    expect(text).not.toMatch(/500 HZ/)
    expect(text).not.toMatch(/STREAMING/)
    expect(text).not.toMatch(/NO DEVICE CONNECTED/)
    expect(text).not.toMatch(/τ_/)
    expect(text).not.toMatch(/Inject anomaly/)
  })
})

describe('BenchScreen — device-keyed view (SOLUSDEV-72)', () => {
  it('renders per-device telemetry from active sessions when nothing is focused', async () => {
    seedProject()
    routeApi({ sessions: [SESSION] })
    render(<BenchScreen />)
    // The device from the active session gets its own panel with recent values.
    expect(await screen.findByText('demo/rod')).toBeInTheDocument()
    await waitFor(() =>
      expect(requestMock).toHaveBeenCalledWith(
        '/projects/p1/bench/device-recent?device_id=demo%2Frod&limit=60'
      )
    )
    expect(await screen.findByText(/qvel: 1\.25/)).toBeInTheDocument()
    // The device view takes the screen: no canvas slots beside it.
    expect(slots()).toHaveLength(0)
  })
})

describe('BenchScreen — focused', () => {
  it('mounts the Live Bench widget scoped to the focused entity, in the default canvas slot', async () => {
    seedFocusedProject()
    render(<BenchScreen />)
    await waitFor(() => expect(requestMock).toHaveBeenCalledWith('/projects/p1/bench/recent/e1'))
    // No telemetry for the part → the widget's own honest empty state.
    expect(
      await screen.findByText(/No telemetry yet for elbow motor — nothing is streaming\./)
    ).toBeInTheDocument()
    expect(slots().map((s) => s.dataset.ref)).toEqual(['builtin:livebench'])
    expect(screen.getByText('elbow motor')).toBeInTheDocument()
    // Nothing was written: an untouched project never accumulates layout rows.
    expect(layoutPutMock).not.toHaveBeenCalled()
  })
})

describe('BenchScreen — widget canvas (SOLUSDEV-235 / EXT-16)', () => {
  it('renders the Live Bench header with exactly one Add widget button once the layout loads', async () => {
    seedFocusedProject()
    render(<BenchScreen />)
    expect(screen.getByRole('heading', { name: 'Live Bench' })).toBeInTheDocument()
    await waitFor(() => expect(slots()).toHaveLength(1))
    expect(addWidgetButtons()).toHaveLength(1)
    expect(layoutGetMock).toHaveBeenCalledWith('p1')
  })

  it('Add widget opens the picker; adding a built-in appends a slot and saves the layout', async () => {
    seedFocusedProject()
    render(<BenchScreen />)
    await waitFor(() => expect(addWidgetButtons()).toHaveLength(1))
    fireEvent.click(addWidgetButtons()[0])
    const dialog = screen.getByRole('dialog', { name: 'Add widget' })
    // The default slot is already on the canvas: it reads Added, not Add.
    expect(within(dialog).getByText('Added')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add Reference' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(slots().map((s) => s.dataset.ref)).toEqual(['builtin:livebench', 'builtin:reference'])
    await waitFor(
      () =>
        expect(layoutPutMock).toHaveBeenCalledWith('p1', [
          DEFAULT_SLOT,
          { ref: 'builtin:reference', size: 'compact' }
        ]),
      { timeout: 2_000 }
    )
  })

  it('an empty saved layout shows the canvas empty state, still with the header line', async () => {
    seedProject()
    routeCanvas([])
    render(<BenchScreen />)
    expect(await screen.findByText('Nothing on your bench.')).toBeInTheDocument()
    expect(slots()).toHaveLength(0)
    expect(await screen.findByText('NOTHING STREAMING')).toBeInTheDocument()
  })

  it('a failed layout GET renders the default slot with the offline note', async () => {
    seedFocusedProject()
    layoutGetMock.mockRejectedValue(new TypeError('network'))
    render(<BenchScreen />)
    // The note sits beside the header button with its Retry link (split text).
    expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument()
    const notes = screen.getAllByRole('status').map((el) => el.textContent ?? '')
    expect(notes.some((text) => text.includes(OFFLINE_NOTE))).toBe(true)
    expect(slots().map((s) => s.dataset.ref)).toEqual(['builtin:livebench'])
  })

  it('the picker’s Browse the Store goes to the Store screen', async () => {
    seedFocusedProject()
    const onNavigate = vi.fn()
    render(<BenchScreen onNavigate={onNavigate} />)
    await waitFor(() => expect(addWidgetButtons()).toHaveLength(1))
    fireEvent.click(addWidgetButtons()[0])
    fireEvent.click(screen.getByRole('button', { name: 'Browse the Store' }))
    expect(onNavigate).toHaveBeenCalledWith('store')
  })
})
