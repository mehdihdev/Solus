// WS-01's acceptance criterion, made executable: two widgets on one shared focus, and selecting
// in ONE re-scopes the OTHER. Everything else in the focus engine exists to make this work.
//
// The widgets here are deliberately trivial — the claim under test is the contract and the
// broadcast, not any particular lens. A real schematic/CAD/telemetry widget is the same shape.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useFocusStore } from '../focusStore'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import * as resources from '../../../lib/api/resources'
import { WidgetHost } from './WidgetHost'
import { NeighborsWidget } from './NeighborsWidget'
import { FocusSummaryWidget } from './FocusSummaryWidget'
import { SOL_ACTION_KINDS, type SolActionKind, type WidgetProps } from '../widget.contract'

vi.mock('../../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../lib/api/resources')>()
  return { ...actual, getGraphNeighborhood: vi.fn() }
})

const MOTOR: resources.Entity = {
  id: 'e-motor',
  type: 'motor',
  domain: 'mechanical',
  name: 'knee_motor',
  source_key: ':motor'
}
const DRIVER: resources.Entity = {
  id: 'e-driver',
  type: 'ic',
  domain: 'electrical',
  name: 'DRV8301',
  source_key: ':u4'
}

const around = (root: resources.Entity, other: resources.Entity): resources.Neighborhood => ({
  entities: [root, other],
  edges: [{ id: 'edge-1', type: 'drives', from_entity_id: root.id, to_entity_id: other.id }],
  truncated: false
})

beforeEach(() => {
  vi.clearAllMocks()
  useFocusStore.getState().reset()
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Strider' } })
  vi.mocked(resources.getGraphNeighborhood).mockImplementation(async (_p, root) =>
    root === MOTOR.id ? around(MOTOR, DRIVER) : around(DRIVER, MOTOR)
  )
})

function renderBothWidgets(): void {
  render(
    <>
      <WidgetHost widget={NeighborsWidget} />
      <WidgetHost widget={FocusSummaryWidget} />
    </>
  )
}

describe('two widgets, one shared focus', () => {
  it('re-scopes BOTH widgets when the focus changes in ONE of them', async () => {
    const user = userEvent.setup()
    renderBothWidgets()

    await useFocusStore.getState().focus(MOTOR.id)
    await waitFor(() => expect(screen.getByTestId('focused-name')).toHaveTextContent('knee_motor'))
    // The summary widget agrees with the neighbours widget about what is focused.
    expect(screen.getByTestId('neighbour-count')).toHaveTextContent('2')

    // Selecting inside the NEIGHBOURS widget...
    await user.click(screen.getByRole('button', { name: 'DRV8301' }))

    // ...re-scopes the SUMMARY widget, which never knew the click happened.
    await waitFor(() => expect(screen.getByTestId('focused-name')).toHaveTextContent('DRV8301'))
    expect(screen.getByTestId('focused-domain')).toHaveTextContent('electrical')
  })

  it('costs ONE request per selection no matter how many widgets are mounted', async () => {
    renderBothWidgets()
    await useFocusStore.getState().focus(MOTOR.id)
    await waitFor(() => expect(screen.getByTestId('focused-name')).toHaveTextContent('knee_motor'))
    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(1)
  })

  it('does not refetch when returning to an entity already visited', async () => {
    const user = userEvent.setup()
    renderBothWidgets()

    await useFocusStore.getState().focus(MOTOR.id)
    await waitFor(() => expect(screen.getByTestId('focused-name')).toHaveTextContent('knee_motor'))
    await user.click(screen.getByRole('button', { name: 'DRV8301' }))
    await waitFor(() => expect(screen.getByTestId('focused-name')).toHaveTextContent('DRV8301'))

    await user.click(screen.getByRole('button', { name: 'knee_motor' }))
    await waitFor(() => expect(screen.getByTestId('focused-name')).toHaveTextContent('knee_motor'))

    expect(resources.getGraphNeighborhood).toHaveBeenCalledTimes(2) // not 3
  })
})

describe('widget contract surface', () => {
  it('renders an empty state before anything is focused', () => {
    renderBothWidgets()
    expect(screen.getByTestId('focused-name')).toHaveTextContent('Nothing focused')
  })

  it('surfaces a load failure instead of rendering a stale or blank neighbourhood', async () => {
    vi.mocked(resources.getGraphNeighborhood).mockRejectedValueOnce(new Error('unreachable'))
    renderBothWidgets()
    await useFocusStore.getState().focus(MOTOR.id)
    // Both widgets surface it — a failure is shared state, not one lens's private problem.
    await waitFor(() => expect(screen.getAllByTestId('focus-error')).toHaveLength(2))
  })

  it('routes a SOL action request to the host rather than letting the widget act', async () => {
    const user = userEvent.setup()
    const onSolAction = vi.fn()
    render(<WidgetHost widget={FocusSummaryWidget} onSolAction={onSolAction} />)

    await useFocusStore.getState().focus(MOTOR.id)
    await waitFor(() => expect(screen.getByTestId('focused-name')).toHaveTextContent('knee_motor'))
    await user.click(screen.getByRole('button', { name: /ask sol/i }))

    expect(onSolAction).toHaveBeenCalledWith({ kind: 'explain', entityId: MOTOR.id })
  })

  it('DROPS a SOL action outside the allowlist instead of forwarding it', async () => {
    // The contract says "the widget proposes, the host decides". TypeScript's union is erased at
    // runtime, and once WS-04 lets SOL drive the workspace a widget's request is model-influenced
    // input — CLAUDE.md §7 requires the action set be fixed in Solus code before it is honoured.
    const user = userEvent.setup()
    const onSolAction = vi.fn()
    const RogueWidget = ({ actions }: WidgetProps): React.JSX.Element => (
      <button
        type="button"
        onClick={() => actions.requestSolAction({ kind: 'delete_everything' as SolActionKind })}
      >
        rogue
      </button>
    )

    render(<WidgetHost widget={RogueWidget} onSolAction={onSolAction} />)
    await user.click(screen.getByRole('button', { name: 'rogue' }))

    expect(onSolAction).not.toHaveBeenCalled()
  })

  it('forwards every kind that IS on the allowlist', async () => {
    const user = userEvent.setup()
    const onSolAction = vi.fn()
    const Sender = ({ actions }: WidgetProps): React.JSX.Element => (
      <>
        {SOL_ACTION_KINDS.map((kind) => (
          <button key={kind} type="button" onClick={() => actions.requestSolAction({ kind })}>
            {kind}
          </button>
        ))}
      </>
    )

    render(<WidgetHost widget={Sender} onSolAction={onSolAction} />)
    for (const kind of SOL_ACTION_KINDS) {
      await user.click(screen.getByRole('button', { name: kind }))
    }
    expect(onSolAction).toHaveBeenCalledTimes(SOL_ACTION_KINDS.length)
  })

  it('warns the user when the server truncated the neighbourhood', async () => {
    vi.mocked(resources.getGraphNeighborhood).mockResolvedValueOnce({
      ...around(MOTOR, DRIVER),
      truncated: true
    })
    renderBothWidgets()
    await useFocusStore.getState().focus(MOTOR.id)
    await waitFor(() => expect(screen.getByTestId('truncated-notice')).toBeInTheDocument())
  })
})
