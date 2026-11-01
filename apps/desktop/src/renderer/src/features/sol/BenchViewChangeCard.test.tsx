// SOLUSDEV-319 B8: the SOL turn's bench-view change chip (wireflow live-bench-view.md §5,
// route doc bench-view.md §6–§7). Undo is a user REST call through the bench view store.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EMPTY_BENCH_VIEW } from '@solus/shared-types'
import { patchBenchView } from '../../lib/api/resources.benchView'
import { ApiError } from '../../lib/api/envelope.types'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useMe } from '../workspace/useMe'
import { resetBenchViewStore } from '../bench/view/useBenchView'
import { BenchViewChangeCard, BenchViewChangesView } from './BenchViewChangeCard'
import type { BenchViewChange } from './solChatItems'

vi.mock('../../lib/api/resources.benchView', async (importActual) => ({
  ...(await importActual<typeof import('../../lib/api/resources.benchView')>()),
  patchBenchView: vi.fn()
}))
vi.mock('../workspace/useMe', () => ({ useMe: vi.fn() }))

const meWith = (role: string): ReturnType<typeof useMe> => ({
  status: 'ready',
  name: null,
  email: 'u@example.test',
  me: {
    id: 'u',
    email: 'u@example.test',
    name: null,
    avatar_url: null,
    created_at: '',
    teams: [
      { team_id: 't1', name: 'T', role, is_personal: false, plan_status: '', trial_ends_at: '' }
    ]
  }
})

const inverseOps = [{ kind: 'delete_derived' as const, id: 'd9' }]
const change = (over: Partial<BenchViewChange> = {}): BenchViewChange => ({
  callId: 'c1',
  summary: 'Created derived signal "Lift error"',
  version: 7,
  inverseOps,
  ...over
})

const renderCard = (c: BenchViewChange = change()): ReturnType<typeof render> =>
  render(<BenchViewChangeCard change={c} projectId="p1" />)

const undoButton = (): HTMLElement => screen.getByRole('button', { name: 'Undo' })

beforeEach(() => {
  resetBenchViewStore()
  vi.mocked(patchBenchView).mockReset()
  vi.mocked(useMe).mockReturnValue(meWith('member'))
  useWorkspaceStore.setState({ teamId: 't1', project: null })
})

describe('BenchViewChangeCard', () => {
  it('shows the Solus-composed summary with an Undo button for a member', () => {
    renderCard()
    expect(screen.getByText(/Bench view/)).toBeInTheDocument()
    expect(screen.getByText('Created derived signal "Lift error"')).toBeInTheDocument()
    expect(undoButton()).toBeEnabled()
  })

  it('Undo sends the inverse ops with the result version and undo:true, then reads Undone', async () => {
    vi.mocked(patchBenchView).mockResolvedValue({
      version: 8,
      view: { ...EMPTY_BENCH_VIEW, version: 8 },
      inverse_ops: []
    })
    renderCard()
    await act(async () => fireEvent.click(undoButton()))
    expect(patchBenchView).toHaveBeenCalledWith('p1', { version: 7, ops: inverseOps, undo: true })
    expect(screen.getByText('Undone ✓')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })

  it('reads "View changed since — Undo unavailable" on 409 and disables the button', async () => {
    vi.mocked(patchBenchView).mockRejectedValue(
      new ApiError(409, 'conflict', 'stale', [{ current_version: 9 }])
    )
    renderCard()
    await act(async () => fireEvent.click(undoButton()))
    expect(screen.getByText('View changed since — Undo unavailable')).toBeInTheDocument()
    expect(undoButton()).toBeDisabled()
  })

  it('shows an error line on any other failure and keeps Undo available', async () => {
    vi.mocked(patchBenchView).mockRejectedValue(new Error('offline'))
    renderCard()
    await act(async () => fireEvent.click(undoButton()))
    expect(screen.getByText('Undo failed — check your connection.')).toBeInTheDocument()
    expect(undoButton()).toBeEnabled()
  })

  it('offers no Undo when the inverse ops did not validate', () => {
    renderCard(change({ inverseOps: null }))
    expect(screen.getByText('Created derived signal "Lift error"')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })

  it('offers no Undo to a viewer', () => {
    vi.mocked(useMe).mockReturnValue(meWith('viewer'))
    renderCard()
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })

  it("uses the open project's team over the active team", () => {
    useWorkspaceStore.setState({
      teamId: 'other',
      project: { id: 'p1', name: 'P', teamId: 't1' } as never
    })
    renderCard()
    expect(undoButton()).toBeInTheDocument()
  })

  it('renders a hostile summary as text, never markup', () => {
    const hostile = '<img src=x onerror="alert(1)"><b>bold</b>'
    const { container } = renderCard(change({ summary: hostile }))
    expect(screen.getByText(hostile)).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
  })
})

describe('BenchViewChangesView', () => {
  it('renders one chip per change and nothing for none', () => {
    const { container, rerender } = render(
      <BenchViewChangesView changes={undefined} projectId="p1" />
    )
    expect(container).toBeEmptyDOMElement()
    rerender(
      <BenchViewChangesView
        changes={[change(), change({ callId: 'c2', summary: 'Pinned 2 signals' })]}
        projectId="p1"
      />
    )
    expect(screen.getAllByRole('button', { name: 'Undo' })).toHaveLength(2)
    expect(screen.getByText('Pinned 2 signals')).toBeInTheDocument()
  })
})
