import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { decodeRunFindings, decodeRunNarration } from './runDecoders'
import { RunNarrationPanel } from './RunNarrationPanel'
import { narrateRun } from './runsApi'
vi.mock('./runsApi', () => ({ narrateRun: vi.fn() }))
it('accepts server evidence origin and rejects malformed narration', () => {
  expect(
    decodeRunFindings({ findings: [], insufficient: [], evidence_origin: 'live' })
  ).toBeDefined()
  expect(() =>
    decodeRunNarration({
      mode: 'model',
      reason: 'ok',
      findings: [],
      insufficient: [],
      narration: [{}],
      evidence_origin: 'live'
    })
  ).toThrow()
})
it('requests narration explicitly and labels fallback', async () => {
  vi.mocked(narrateRun).mockResolvedValue({
    mode: 'deterministic',
    reason: 'No findings require narration.',
    findings: [],
    insufficient: [],
    narration: [],
    evidence_origin: 'live'
  })
  render(<RunNarrationPanel projectId="p" runId="r" />)
  expect(narrateRun).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Explain findings' }))
  expect(await screen.findByText('No findings require narration.')).toBeInTheDocument()
  expect(narrateRun).toHaveBeenCalledWith('p', 'r', expect.any(AbortSignal))
})
