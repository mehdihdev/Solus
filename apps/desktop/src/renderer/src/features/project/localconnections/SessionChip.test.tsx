// SOLUSDEV-72 — inline session chip: honest link state, real counts, Stop.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SessionChip } from './SessionChip'
import type { BenchSession } from '../../../lib/api/resources'

const SESSION: BenchSession = {
  id: 's1',
  mode: 'sim',
  provider: 'mujoco',
  status: 'active',
  link: 'disconnected',
  label: 'MuJoCo demo scene',
  created_at: '2026-08-16T00:00:00Z',
  ended_at: null,
  device: null,
  device_ids: ['demo/rod'],
  counts: { ingested: 123, unresolved: 45 },
  last_summary: null
}

describe('SessionChip', () => {
  it('renders the label, the ingested count, and the HONEST link state', () => {
    render(<SessionChip session={SESSION} onStop={vi.fn()} />)
    expect(screen.getByText('MuJoCo demo scene')).toBeInTheDocument()
    expect(screen.getByText('123 INGESTED')).toBeInTheDocument()
    // A dead pump reads DISCONNECTED — never relabelled as streaming.
    expect(screen.getByText('DISCONNECTED')).toBeInTheDocument()
  })

  it('stops the session by id', () => {
    const onStop = vi.fn()
    render(<SessionChip session={SESSION} onStop={onStop} />)
    fireEvent.click(screen.getByRole('button', { name: 'Stop MuJoCo demo scene' }))
    expect(onStop).toHaveBeenCalledWith('s1')
  })

  it('a starting session reads STARTING and cannot be stopped yet', () => {
    render(<SessionChip session={{ ...SESSION, status: 'starting' }} onStop={vi.fn()} />)
    expect(screen.getByText('STARTING')).toBeInTheDocument()
    // The backend 409s `session_starting` on stop — don't offer it.
    expect(screen.getByRole('button', { name: 'Stop MuJoCo demo scene' })).toBeDisabled()
  })
})
