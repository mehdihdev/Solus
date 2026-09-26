import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { InlineSupplierResults } from './InlineSupplierResults'
import { useSourcing, type SourcingData } from '../../sourcing/useSourcing'
vi.mock('../../sourcing/useSourcing', () => ({ useSourcing: vi.fn() }))
const submit = vi.fn(),
  select = vi.fn(),
  onCreated = vi.fn()
let data: SourcingData
beforeEach(() => {
  vi.clearAllMocks()
  data = {
    phase: 'requirement',
    rules: null,
    torque: null,
    request: null,
    selected: null,
    error: null,
    busy: false,
    actions: { submit, select, derive: vi.fn(), saveRules: vi.fn(), reset: vi.fn() }
  }
  vi.mocked(useSourcing).mockImplementation(() => data)
})
it('only starts metered sourcing after explicit click for the shared search query', async () => {
  render(
    <InlineSupplierResults
      projectId="p"
      query="force sensor"
      disabled={false}
      onCreated={onCreated}
    />
  )
  expect(submit).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: /Search suppliers/ }))
  expect(submit).toHaveBeenCalledWith({ door: 'workspace', spec: { text: 'force sensor' } })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
it('adds an inline candidate with one selection and forwards the created entity once', async () => {
  data = {
    ...data,
    phase: 'candidates',
    request: {
      id: 'request',
      candidates: [
        {
          id: 'candidate',
          name: 'Cited force sensor',
          grounding: 'cited',
          notes: 'Known facts',
          flags: [],
          certifications: [],
          optimizes_for: 'size',
          gives_up: 'range'
        }
      ],
      excluded: []
    } as unknown as SourcingData['request']
  }
  const { rerender } = render(
    <InlineSupplierResults
      projectId="p"
      query="force sensor"
      disabled={false}
      onCreated={onCreated}
    />
  )
  await userEvent.click(screen.getByRole('button', { name: 'Add Cited force sensor' }))
  expect(select).toHaveBeenCalledWith('candidate')
  data = {
    ...data,
    selected: { id: 'part', name: 'Cited force sensor' } as NonNullable<SourcingData['selected']>,
    phase: 'selected'
  }
  rerender(
    <InlineSupplierResults
      projectId="p"
      query="force sensor"
      disabled={false}
      onCreated={onCreated}
    />
  )
  await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1))
})
