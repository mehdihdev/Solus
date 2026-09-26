import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { confirmExtraction, proposeExtraction } from '../../../lib/api/topologyExtraction'
import { ExtractionReviewCard } from './ExtractionReviewCard'

vi.mock('../../../lib/api/topologyExtraction', () => ({
  proposeExtraction: vi.fn(),
  confirmExtraction: vi.fn()
}))
vi.mock('../hardware/HardwareSourcesPanel', () => ({
  HardwareSourcesPanel: ({
    onSelect,
    onSourceChange
  }: {
    onSelect: (ref: string) => void
    onSourceChange: () => void
  }) => (
    <>
      <button onClick={onSourceChange}>Relink selected fixture</button>
      <button onClick={() => onSelect('source:00000000-0000-0000-0000-000000000001')}>
        Select fixture file
      </button>
    </>
  )
}))
vi.mock('../../../lib/api/hardwareTopology', () => ({
  readHardwareTopology: vi
    .fn()
    .mockResolvedValue({ nodes: [{ id: 'retained', name: 'Existing elbow' }] })
}))
const props = { projectId: 'p1', brainId: 'b1', robots: [{ id: 'r1', name: 'Arm' }] }
beforeEach(() => {
  vi.mocked(proposeExtraction).mockReset()
  vi.mocked(confirmExtraction).mockReset()
})

it('requires explicit file and kind then reviews candidate evidence with explicit acceptance', async () => {
  vi.mocked(proposeExtraction).mockResolvedValue({
    robot_id: 'r1',
    brain_id: 'b1',
    source_ref: 'source:00000000-0000-0000-0000-000000000001',
    proposal_digest: 'digest',
    extraction: {
      source_kind: 'firmware',
      status: 'success',
      notes: [],
      rows: [
        {
          source_namespace: 'local',
          source_ref: 'opaque',
          bus: null,
          device: null,
          protocol: 'pwm',
          address: null,
          part_candidate: 'elbow',
          provenance: [{ source_ref: 'opaque', pin_ref: 'PIN_X', entity_ref: null, detail: null }],
          confidence: null
        }
      ]
    }
  })
  render(<ExtractionReviewCard {...props} />)
  expect(screen.getByRole('button', { name: 'Review file evidence' })).toBeDisabled()
  fireEvent.click(screen.getByText('Select fixture file'))
  fireEvent.change(screen.getByRole('combobox', { name: 'Evidence type' }), {
    target: { value: 'firmware' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Review file evidence' }))
  expect(await screen.findByText('elbow')).toBeInTheDocument()
  expect(screen.getByText('PIN_X')).toBeInTheDocument()
  const confirm = screen.getByRole('button', { name: 'Confirm evidence' })
  expect(confirm).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select evidence 1' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Reviewed name 1' }), {
    target: { value: 'Reviewed elbow' }
  })
  fireEvent.change(screen.getByRole('combobox', { name: 'Retain identity 1' }), {
    target: { value: 'retained' }
  })
  vi.mocked(confirmExtraction).mockResolvedValue({
    robot_id: 'r1',
    brain_id: 'b1',
    proposal_digest: 'digest',
    entity_ids: ['retained'],
    created: 0
  })
  fireEvent.click(confirm)
  expect(await screen.findByText(/Evidence saved/)).toBeInTheDocument()
  expect(confirmExtraction).toHaveBeenCalledWith(
    'p1',
    'r1',
    expect.objectContaining({
      proposal_digest: 'digest',
      operation_id: expect.any(String),
      selections: [{ row_index: 0, name: 'Reviewed elbow', entity_id: 'retained' }]
    })
  )
  expect(proposeExtraction).toHaveBeenCalledWith('p1', 'r1', {
    brain_id: 'b1',
    source_ref: 'source:00000000-0000-0000-0000-000000000001',
    source_kind: 'firmware'
  })
  expect(screen.queryByText('Relink selected fixture')).toBeNull()
  expect(screen.getByRole('button', { name: 'Review file evidence' })).toBeDisabled()
})

it.each(['brain', 'relink'])('discards responses after %s changes', async (change) => {
  let finish!: (value: never) => void
  vi.mocked(proposeExtraction).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const view = render(<ExtractionReviewCard {...props} />)
  fireEvent.click(screen.getByText('Select fixture file'))
  fireEvent.change(screen.getByRole('combobox', { name: 'Evidence type' }), {
    target: { value: 'firmware' }
  })
  fireEvent.click(screen.getByRole('button', { name: 'Review file evidence' }))
  if (change === 'brain') view.rerender(<ExtractionReviewCard {...props} brainId="b2" />)
  else fireEvent.click(screen.getByText('Relink selected fixture'))
  await act(async () => finish({ extraction: { rows: [], notes: ['OLD RESULT'] } } as never))
  expect(screen.queryByText('OLD RESULT')).toBeNull()
})

const candidate = {
  robot_id: 'r1',
  brain_id: 'b1',
  source_ref: 'source:00000000-0000-0000-0000-000000000001',
  proposal_digest: 'd'.repeat(64),
  extraction: {
    source_kind: 'firmware' as const,
    status: 'success' as const,
    notes: [],
    rows: [
      { source_namespace: 'local', source_ref: 'opaque', part_candidate: 'motor', provenance: [] }
    ]
  }
}
async function selectEvidence(): Promise<void> {
  fireEvent.click(screen.getByText('Select fixture file'))
  fireEvent.change(screen.getByRole('combobox', { name: 'Evidence type' }), {
    target: { value: 'firmware' }
  })
  fireEvent.click(screen.getByText('Review file evidence'))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Select evidence 1' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Reviewed name 1' }), {
    target: { value: 'Motor' }
  })
}
it('freezes uncertain confirmation and retries the same operation without duplicate clicks', async () => {
  vi.mocked(proposeExtraction).mockResolvedValue(candidate)
  vi.mocked(confirmExtraction)
    .mockRejectedValueOnce(new Error('lost response'))
    .mockResolvedValueOnce({
      robot_id: 'r1',
      brain_id: 'b1',
      proposal_digest: candidate.proposal_digest,
      entity_ids: ['created'],
      created: 1
    })
  const refresh = vi.fn()
  render(<ExtractionReviewCard {...props} onConfirmed={refresh} />)
  await selectEvidence()
  fireEvent.click(screen.getByText('Confirm evidence'))
  expect(await screen.findByRole('alert')).toHaveTextContent('Retry the same selection')
  expect(screen.getByRole('textbox', { name: 'Reviewed name 1' })).toBeDisabled()
  expect(screen.getByText('Review file evidence')).toBeDisabled()
  expect(screen.queryByText('Select fixture file')).toBeNull()
  expect(screen.queryByText('Relink selected fixture')).toBeNull()
  expect(screen.queryByRole('combobox', { name: 'Evidence type' })).toBeNull()
  fireEvent.click(screen.getByText('Confirm evidence'))
  fireEvent.click(screen.getByText('Confirm evidence'))
  await screen.findByText(/Evidence saved/)
  expect(confirmExtraction).toHaveBeenCalledTimes(2)
  expect(vi.mocked(confirmExtraction).mock.calls[0][2]).toEqual(
    vi.mocked(confirmExtraction).mock.calls[1][2]
  )
  expect(refresh).toHaveBeenCalledTimes(1)
})
it('does not publish confirmation after project changes', async () => {
  vi.mocked(proposeExtraction).mockResolvedValue(candidate)
  let finish!: (value: Awaited<ReturnType<typeof confirmExtraction>>) => void
  vi.mocked(confirmExtraction).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const refresh = vi.fn()
  const view = render(<ExtractionReviewCard {...props} onConfirmed={refresh} />)
  await selectEvidence()
  fireEvent.click(screen.getByText('Confirm evidence'))
  view.rerender(<ExtractionReviewCard {...props} projectId="p2" onConfirmed={refresh} />)
  await act(async () =>
    finish({
      robot_id: 'r1',
      brain_id: 'b1',
      proposal_digest: candidate.proposal_digest,
      entity_ids: ['created'],
      created: 1
    })
  )
  expect(refresh).not.toHaveBeenCalled()
  expect(screen.queryByText(/Evidence saved/)).toBeNull()
})
it('shows empty evidence without enabling confirmation', async () => {
  vi.mocked(proposeExtraction).mockResolvedValue({
    ...candidate,
    extraction: { ...candidate.extraction, rows: [] }
  })
  render(<ExtractionReviewCard {...props} />)
  fireEvent.click(screen.getByText('Select fixture file'))
  fireEvent.change(screen.getByRole('combobox', { name: 'Evidence type' }), {
    target: { value: 'firmware' }
  })
  fireEvent.click(screen.getByText('Review file evidence'))
  await screen.findByText('No recognized wiring declarations in this file.')
  expect(screen.getByText('Confirm evidence')).toBeDisabled()
})
