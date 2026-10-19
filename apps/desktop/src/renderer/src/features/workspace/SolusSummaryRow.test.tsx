// The .solus line in Home's PROJECT SETUP (SOLUSDEV-317): how much of the
// project's .solus is filled, which sections hold what, and "Add instructions".
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SolusSummaryRow } from './SolusSummaryRow'
import * as solusConfig from '../graph/useSolusConfig'
import type { SolusEntry } from '../../lib/api/resources'

vi.mock('../graph/useSolusConfig', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../graph/useSolusConfig')>()
  return { ...actual, useSolusConfig: vi.fn() }
})

const entries = (n: number): SolusEntry[] =>
  Array.from({ length: n }, (_, i) => ({ id: `e${i}` }) as unknown as SolusEntry)

function mockSolus(status: solusConfig.SolusState['status'], hardware = 0, docs = 0): void {
  vi.mocked(solusConfig.useSolusConfig).mockReturnValue({
    status,
    entityId: null,
    sections: { ...solusConfig.emptySections(), hardware: entries(hardware), docs: entries(docs) },
    refetch: vi.fn()
  })
}

beforeEach(() => vi.clearAllMocks())

describe('SolusSummaryRow', () => {
  it('states how many sections hold something and names them with counts', () => {
    mockSolus('ready', 7, 2)
    render(<SolusSummaryRow projectId="p1" onAddInstructions={vi.fn()} />)
    expect(screen.getByText(/2 of 5 sections filled/)).toBeInTheDocument()
    expect(screen.getByText(/Hardware configs \(7\)/)).toBeInTheDocument()
    expect(screen.getByText(/Documentation \(2\)/)).toBeInTheDocument()
    const segments = screen.getAllByTestId('solus-segment')
    expect(segments).toHaveLength(5)
    expect(segments.filter((s) => s.dataset.filled === 'true')).toHaveLength(2)
  })

  it('says so when nothing is filled yet', () => {
    mockSolus('ready')
    render(<SolusSummaryRow projectId="p1" onAddInstructions={vi.fn()} />)
    expect(screen.getByText(/nothing yet/i)).toBeInTheDocument()
  })

  it('offers Add instructions', async () => {
    mockSolus('ready', 1)
    const onAddInstructions = vi.fn()
    render(<SolusSummaryRow projectId="p1" onAddInstructions={onAddInstructions} />)
    await userEvent.click(screen.getByRole('button', { name: 'Add instructions' }))
    expect(onAddInstructions).toHaveBeenCalled()
  })

  it('is honest while loading and offline', () => {
    mockSolus('loading')
    const first = render(<SolusSummaryRow projectId="p1" onAddInstructions={vi.fn()} />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    first.unmount()
    mockSolus('offline')
    render(<SolusSummaryRow projectId="p1" onAddInstructions={vi.fn()} />)
    expect(screen.getByText(/can't reach its api/i)).toBeInTheDocument()
  })

  it('eases the segments as they fill', () => {
    mockSolus('ready', 1)
    render(<SolusSummaryRow projectId="p1" onAddInstructions={vi.fn()} />)
    expect(screen.getAllByTestId('solus-segment')[0]).toHaveClass('home-segment')
  })
})
