import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Entity, Relation } from '../../../lib/api/resources'
import { useWorkspaceStore } from '../../../store/workspaceStore'
import { useFocusStore } from '../../workspace/focusStore'
import type { FindingsBySubject } from '../useFindings'
import { ConnectionsPanel, connectionStatus } from './ConnectionsPanel'

const node = (id: string, name: string, domain = 'electrical'): Entity => ({
  id,
  name,
  type: 'part',
  domain,
  source_key: null
})
const MOUNT = node('mount', 'Motor mount rev C', 'mechanical')
const BOARD = node('board', 'Main board rev B')
const IMU = node('imu', 'IMU breakout')
const edges: Relation[] = [
  { id: 'e1', type: 'mates_with', from_entity_id: 'mount', to_entity_id: 'board' },
  { id: 'e2', type: 'connected_to', from_entity_id: 'imu', to_entity_id: 'mount' },
  { id: 'e3', type: 'contains', from_entity_id: 'board', to_entity_id: 'imu' }
]

beforeEach(() => {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover', teamId: 't1' } })
  useFocusStore.setState({
    focusedEntityId: 'mount',
    status: 'ready',
    depth: 1,
    cache: { 'p1:mount@1': { entities: [MOUNT, BOARD, IMU], edges, truncated: false } }
  })
})

describe('connectionStatus', () => {
  it('derives the pill from the worst open finding on either endpoint', () => {
    expect(connectionStatus(null, undefined)).toEqual({ label: 'In sync', tone: 'ok' })
    expect(connectionStatus({ severity: 'info', count: 1 })).toEqual({
      label: 'Review',
      tone: 'warn'
    })
    expect(connectionStatus(null, { severity: 'warning', count: 2 })).toEqual({
      label: 'Review',
      tone: 'warn'
    })
    expect(
      connectionStatus({ severity: 'warning', count: 1 }, { severity: 'critical', count: 1 })
    ).toEqual({ label: 'Broken', tone: 'err' })
  })
})

describe('ConnectionsPanel', () => {
  it('lists only the edges touching the node, with the edge sentence and a status pill', () => {
    const findings: FindingsBySubject = new Map([['board', { severity: 'critical', count: 1 }]])
    const onReveal = vi.fn()
    render(<ConnectionsPanel entity={MOUNT} findings={findings} onReveal={onReveal} />)
    expect(screen.getByText('CONNECTIONS · 2')).toBeInTheDocument()
    expect(screen.getByText('Motor mount rev C mates with Main board rev B')).toBeInTheDocument()
    expect(screen.getByText('IMU breakout connected to Motor mount rev C')).toBeInTheDocument()
    const pills = document.querySelectorAll('.conn-status')
    expect(Array.from(pills).map((pill) => pill.textContent)).toEqual(['Broken', 'In sync'])
    fireEvent.click(screen.getByRole('button', { name: 'Reveal Main board rev B' }))
    expect(onReveal).toHaveBeenCalledWith('board')
  })

  it('filters by name or effect and says so when nothing matches', () => {
    render(<ConnectionsPanel entity={MOUNT} findings={new Map()} onReveal={vi.fn()} />)
    const search = screen.getByRole('searchbox', { name: 'Search connections' })
    fireEvent.change(search, { target: { value: 'imu' } })
    expect(screen.getByText('CONNECTIONS · 1')).toBeInTheDocument()
    expect(screen.queryByText(/mates with/)).toBeNull()
    fireEvent.change(search, { target: { value: 'zzz' } })
    expect(screen.getByText('No connections match “zzz”')).toBeInTheDocument()
  })

  it('is honest about an empty or truncated neighbourhood', () => {
    useFocusStore.setState({
      cache: { 'p1:mount@1': { entities: [MOUNT], edges: [], truncated: true } }
    })
    render(<ConnectionsPanel entity={MOUNT} findings={new Map()} onReveal={vi.fn()} />)
    expect(screen.getByText('No connections in the graph yet.')).toBeInTheDocument()
    expect(screen.getByText(/the graph has more/)).toBeInTheDocument()
  })
})
