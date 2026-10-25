// SOLUSDEV-320 P5-T3d — the environment/divergences table.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EnvironmentDivergencesDoc } from '../../lib/api/environment'
import { EnvironmentDivergences, divergenceRows } from './EnvironmentDivergences'

afterEach(cleanup)

const DOC: EnvironmentDivergencesDoc = {
  schema_version: 1,
  computed_at: '2026-10-18T10:00:00Z',
  spec_entry_id: 'spec-1',
  machines: [
    {
      machine_id: 'm1',
      hostname: 'bench-1',
      causes: [
        {
          cause: 'version_drift',
          items: [{ name: 'torch', expected: '2.4.0', actual: '2.3.1' }]
        },
        { cause: 'missing', items: [{ name: 'ros-humble-xacro', expected: null, actual: null }] }
      ]
    },
    { machine_id: 'm2', hostname: 'bench-2', causes: [] }
  ]
}

describe('divergenceRows', () => {
  it('flattens machine → cause → item into one row each', () => {
    expect(divergenceRows(DOC)).toEqual([
      {
        machine: 'bench-1',
        cause: 'version drift',
        item: 'torch',
        expected: '2.4.0',
        actual: '2.3.1'
      },
      { machine: 'bench-1', cause: 'missing', item: 'ros-humble-xacro', expected: '—', actual: '—' }
    ])
  })
})

describe('EnvironmentDivergences', () => {
  it('renders a table with the five columns from the loaded document', async () => {
    render(<EnvironmentDivergences projectId="p1" load={vi.fn(async () => DOC)} />)
    expect(
      await screen.findByRole('table', { name: 'Environment divergences' })
    ).toBeInTheDocument()
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Machine',
      'Cause',
      'Item',
      'Expected',
      'Actual'
    ])
    expect(screen.getAllByRole('row')).toHaveLength(3)
    expect(screen.getByText('torch')).toBeInTheDocument()
    expect(screen.getByText('2.3.1')).toBeInTheDocument()
  })

  it('says so when no machine has reported, and when every machine matches', async () => {
    const empty = { ...DOC, machines: [] }
    const { unmount } = render(
      <EnvironmentDivergences projectId="p1" load={vi.fn(async () => empty)} />
    )
    expect(await screen.findByRole('status')).toHaveTextContent('No machine has reported yet.')
    unmount()
    const clean = { ...DOC, machines: [DOC.machines[1]!] }
    render(<EnvironmentDivergences projectId="p1" load={vi.fn(async () => clean)} />)
    expect(await screen.findByRole('status')).toHaveTextContent('Every machine matches the spec.')
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('reports a failed load honestly', async () => {
    render(
      <EnvironmentDivergences
        projectId="p1"
        load={vi.fn(async () => Promise.reject(new Error('x')))}
      />
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Could not load divergences.')
  })
})
