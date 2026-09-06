// The System A → System B focus adapter: workspace focusStore projected into
// the shared-types `Focus` shape the manifest widgets consume. Two properties
// are load-bearing and pinned here: referential stability across unrelated
// store emissions (LiveBenchWidget's poll effect is keyed on the focus object),
// and never fabricating a focus (unknown domain / missing project → null).
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { toSharedFocus, useSharedFocus } from './useSharedFocus'
import { useFocusStore } from './focusStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { Entity } from '../../lib/api/resources'

const E1: Entity = {
  id: 'e1',
  type: 'part',
  domain: 'mechanical',
  name: 'elbow motor',
  source_key: 'onshape:e1'
}

function seedReadyFocus(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
  useFocusStore.setState({
    focusedEntityId: 'e1',
    status: 'ready',
    cache: { 'p1:e1@1': { entities: [E1], edges: [], truncated: false } }
  })
}

beforeEach(() => {
  useWorkspaceStore.getState().reset()
  useFocusStore.getState().reset()
})

describe('toSharedFocus', () => {
  it('maps entity + project into the shared Focus shape', () => {
    expect(toSharedFocus(E1, 'p1')).toEqual({
      entity: { projectId: 'p1', entityId: 'e1' },
      domain: 'mechanical',
      label: 'elbow motor',
      path: []
    })
  })

  it('returns null without an entity or without a project', () => {
    expect(toSharedFocus(null, 'p1')).toBeNull()
    expect(toSharedFocus(E1, null)).toBeNull()
  })

  it('returns null — never a fabricated focus — on an unknown domain', () => {
    expect(toSharedFocus({ ...E1, domain: 'astral' }, 'p1')).toBeNull()
  })
})

describe('useSharedFocus', () => {
  it('passes the navigator ancestry through to Live Bench without a new fetch', () => {
    seedReadyFocus()
    const path = [
      {
        entity: { projectId: 'p1', entityId: 'robot' },
        domain: 'runtime' as const,
        label: 'Rover',
        relation: 'contains'
      }
    ]
    useFocusStore.setState({ path })
    const { result } = renderHook(() => useSharedFocus())
    expect(result.current?.path).toEqual(path)
  })
  it('is null when nothing is focused', () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    const { result } = renderHook(() => useSharedFocus())
    expect(result.current).toBeNull()
  })

  it('is null while the neighbourhood is still loading (no cached entity)', () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
    useFocusStore.setState({ focusedEntityId: 'e1', status: 'loading' })
    const { result } = renderHook(() => useSharedFocus())
    expect(result.current).toBeNull()
  })

  it('projects the cached focused entity once ready', () => {
    seedReadyFocus()
    const { result } = renderHook(() => useSharedFocus())
    expect(result.current).toEqual({
      entity: { projectId: 'p1', entityId: 'e1' },
      domain: 'mechanical',
      label: 'elbow motor',
      path: []
    })
  })

  it('keeps the SAME object across unrelated store emissions', () => {
    seedReadyFocus()
    const { result, rerender } = renderHook(() => useSharedFocus())
    const first = result.current
    act(() => {
      useFocusStore.setState({ error: 'unrelated churn' })
    })
    rerender()
    expect(Object.is(result.current, first)).toBe(true)
  })

  it('drops to null after the project is cleared', () => {
    seedReadyFocus()
    const { result } = renderHook(() => useSharedFocus())
    expect(result.current).not.toBeNull()
    act(() => {
      useFocusStore.getState().clearProject()
      useWorkspaceStore.getState().setProject(null)
    })
    expect(result.current).toBeNull()
  })
})
