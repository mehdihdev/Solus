// SOLUSDEV-216 (CTR-01) — the reference widget, proving a lane can build and
// TEST a widget with NO CANVAS IN THE REPO.
//
// Nothing here imports a canvas, a layout, or a workspace shell. The widget is
// mounted directly with the two props the contract defines. If this file keeps
// passing, a lane blocked on LANE B is not actually blocked.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Focus } from '@solus/shared-types'
import { describe, expect, test, vi } from 'vitest'
import { ReferenceWidget } from './ReferenceWidget'
import manifest from './widget.manifest'

const PROJECT = '11111111-1111-1111-1111-111111111111'

const motor: Focus = {
  entity: { projectId: PROJECT, entityId: 'aaaa1111-0000-0000-0000-000000000001' },
  domain: 'mechanical',
  label: 'drive_motor',
  path: []
}

describe('ReferenceWidget', () => {
  test('renders the empty state when nothing is focused', () => {
    render(<ReferenceWidget focus={null} onFocusChange={vi.fn()} />)
    expect(screen.getByRole('status')).toHaveTextContent(/nothing focused/i)
  })

  test('renders the focused entity once loaded', async () => {
    render(<ReferenceWidget focus={motor} onFocusChange={vi.fn()} />)
    expect(await screen.findByText('drive_motor')).toBeInTheDocument()
    expect(screen.getByText('mechanical')).toBeInTheDocument()
  })

  test('reports every render state it passes through', async () => {
    const onStateChange = vi.fn()
    render(<ReferenceWidget focus={motor} onFocusChange={vi.fn()} onStateChange={onStateChange} />)
    await waitFor(() => expect(onStateChange).toHaveBeenLastCalledWith('ready'))
    expect(onStateChange.mock.calls.map(([s]) => s)).toEqual(['loading', 'ready'])
  })

  test('renders the error state when the entity cannot be described', async () => {
    const broken: Focus = { ...motor, entity: { projectId: PROJECT, entityId: 'not-a-uuid' } }
    render(<ReferenceWidget focus={broken} onFocusChange={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not/i)
  })

  test('reports a focus change through the callback, never by mutating', async () => {
    const onFocusChange = vi.fn()
    render(<ReferenceWidget focus={motor} onFocusChange={onFocusChange} />)
    await userEvent.click(await screen.findByRole('button', { name: /follow/i }))

    expect(onFocusChange).toHaveBeenCalledTimes(1)
    const next = onFocusChange.mock.calls[0]![0] as Focus
    // descend() semantics: the old focus becomes the trail, the relation is recorded.
    expect(next.path).toHaveLength(1)
    expect(next.path[0]?.relation).toBe('drives')
    expect(next.entity.projectId).toBe(PROJECT)
    expect(motor.path).toEqual([]) // the prop was not mutated
  })
})

describe('the reference manifest', () => {
  test('declares itself without touching any shared file', () => {
    expect(manifest.id).toBe('reference')
    expect(manifest.component).toBe(ReferenceWidget)
    expect(manifest.size.preferred).toBe('compact')
  })
})
