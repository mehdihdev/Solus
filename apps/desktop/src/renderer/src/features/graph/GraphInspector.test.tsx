// Inspector rail of the Context Model screen: idle explains itself honestly;
// once a selection lands (via the shared focus store) it mounts the WS-01
// widgets — focus summary + selectable neighbours — under WidgetHost, so
// "selecting a part re-scopes every mounted widget" holds on this screen too.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { GraphInspector } from './GraphInspector'
import { useFocusStore } from '../workspace/focusStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { Entity } from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getGraphNeighborhood: vi.fn() }
})

const E1: Entity = {
  id: 'e1',
  type: 'part',
  domain: 'mechanical',
  name: 'elbow motor',
  source_key: 'onshape:e1'
}
const E2: Entity = {
  id: 'e2',
  type: 'part',
  domain: 'mechanical',
  name: 'wrist servo',
  source_key: 'onshape:e2'
}

beforeEach(() => {
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
})

describe('GraphInspector — idle', () => {
  it('explains what the inspector will show', () => {
    render(<GraphInspector />)
    expect(screen.getByText(/properties, sources, and links across domains/i)).toBeInTheDocument()
  })

  it('contains no fabricated node data or tool buttons', () => {
    const { container } = render(<GraphInspector />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/DRV8316C|leg_ik\.c|Open in KiCad|Ask SOL/)
    expect(text).not.toMatch(/CONNECTED ACROSS DOMAINS/)
  })
})

describe('GraphInspector — focused', () => {
  it('shows a loading line while the neighbourhood fetches', () => {
    useFocusStore.setState({ focusedEntityId: 'e1', status: 'loading' })
    render(<GraphInspector />)
    expect(screen.getByText(/LOADING NEIGHBOURHOOD/)).toBeInTheDocument()
  })

  it('shows ONE error line when the neighbourhood fetch fails', () => {
    useFocusStore.setState({ focusedEntityId: 'e1', status: 'error', error: 'timed out' })
    render(<GraphInspector />)
    expect(screen.getAllByText(/Could not load the neighbourhood/)).toHaveLength(1)
    expect(screen.getByText(/timed out/)).toBeInTheDocument()
  })

  it('renders the focus summary and selectable neighbours once ready', () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    useFocusStore.setState({
      focusedEntityId: 'e1',
      status: 'ready',
      cache: { 'p1:e1@1': { entities: [E1, E2], edges: [], truncated: false } }
    })
    render(<GraphInspector />)
    expect(screen.getByTestId('focused-name')).toHaveTextContent('elbow motor')
    expect(screen.getByTestId('neighbour-count')).toHaveTextContent('2')
    expect(screen.getByRole('button', { name: 'wrist servo' })).toBeInTheDocument()
  })
})
