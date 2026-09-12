// MO-04: the subtle pre-flight indicator + override popover.
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import type { ClassifyPreview } from '../../lib/api/resources'
import { ClassifyIndicator } from './ClassifyIndicator'

const PREVIEW: ClassifyPreview = {
  complexity: 'standard',
  type: 'code',
  reasoner: { name: 'sol-reasoner-1', effort: 'standard' },
  cost_tier: 'standard',
  source: { complexity: 'estimator', type: 'estimator' },
  tokens_estimate: 42,
  viable: true,
  reason: null,
  escalated: false,
  options: {
    complexities: [
      {
        value: 'trivial',
        viable: false,
        reason: 'Too many tokens for this tier (340K > 200K)',
        cost_tier: 'low'
      },
      {
        value: 'standard',
        viable: true,
        reason: null,
        cost_tier: 'standard'
      },
      { value: 'hard', viable: true, reason: null, cost_tier: 'premium' }
    ],
    types: [
      {
        value: 'code',
        viable: true,
        reason: null,
        cost_tier: 'standard'
      },
      {
        value: 'general',
        viable: true,
        reason: null,
        cost_tier: 'standard'
      }
    ]
  }
}

const NO_OVERRIDE = { complexity: null, type: null, thinkHarder: false }

it('shows an honest idle line without a preview — the row never pops in and out', () => {
  // SOLUSDEV-233: the routing line is a permanent part of the composer. With
  // no classification (empty input / endpoint hiccup) it says so instead of
  // vanishing — and never fabricates a tier or model.
  render(
    <ClassifyIndicator
      preview={null}
      override={NO_OVERRIDE}
      onOverride={() => {}}
      onReset={() => {}}
    />
  )
  expect(screen.getByText(/auto routing/)).toBeInTheDocument()
  expect(screen.queryByText(/sol-reasoner/)).not.toBeInTheDocument()
})

it('renders the muted one-line summary', () => {
  render(
    <ClassifyIndicator
      preview={PREVIEW}
      override={NO_OVERRIDE}
      onOverride={() => {}}
      onReset={() => {}}
    />
  )
  const line = screen.getByTestId('classify-indicator')
  // S1-W3: the product reasoner + an effort label — never a model id.
  expect(line.textContent).toContain('sol-reasoner-1 · standard · code')
})

it('offers a "Think harder" toggle in the popover that sets think_harder', () => {
  const onOverride = vi.fn()
  render(
    <ClassifyIndicator
      preview={PREVIEW}
      override={NO_OVERRIDE}
      onOverride={onOverride}
      onReset={() => {}}
    />
  )
  fireEvent.click(screen.getByTestId('classify-indicator'))
  const toggle = screen.getByRole('switch', { name: 'Think harder' })
  expect(toggle).toHaveAttribute('aria-checked', 'false')
  fireEvent.click(toggle)
  expect(onOverride).toHaveBeenCalledWith({ thinkHarder: true })
})

it('is keyboard-accessible: Enter toggles the popover', () => {
  render(
    <ClassifyIndicator
      preview={PREVIEW}
      override={NO_OVERRIDE}
      onOverride={() => {}}
      onReset={() => {}}
    />
  )
  const indicator = screen.getByTestId('classify-indicator')
  expect(indicator).toHaveAttribute('role', 'button')
  fireEvent.keyDown(indicator, { key: 'Enter' })
  expect(screen.getByTestId('classify-popover')).toBeInTheDocument()
  fireEvent.keyDown(indicator, { key: 'Enter' })
  expect(screen.queryByTestId('classify-popover')).not.toBeInTheDocument()
})

it('opens the popover, dims non-viable options, and shows the tiny reason', () => {
  render(
    <ClassifyIndicator
      preview={PREVIEW}
      override={NO_OVERRIDE}
      onOverride={() => {}}
      onReset={() => {}}
    />
  )
  fireEvent.click(screen.getByTestId('classify-indicator'))
  const trivial = screen.getByRole('button', { name: /trivial/ })
  expect(trivial).toBeDisabled()
  expect(screen.getByText('Too many tokens for this tier (340K > 200K)')).toBeInTheDocument()
})

it('picking a viable option overrides that axis for this call', () => {
  const onOverride = vi.fn()
  render(
    <ClassifyIndicator
      preview={PREVIEW}
      override={NO_OVERRIDE}
      onOverride={onOverride}
      onReset={() => {}}
    />
  )
  fireEvent.click(screen.getByTestId('classify-indicator'))
  fireEvent.click(screen.getByRole('button', { name: /hard/ }))
  expect(onOverride).toHaveBeenCalledWith({ complexity: 'hard' })
})

it('marks overridden values and offers a one-click reset', () => {
  const onReset = vi.fn()
  render(
    <ClassifyIndicator
      preview={PREVIEW}
      override={{ complexity: 'hard', type: null, thinkHarder: false }}
      onOverride={() => {}}
      onReset={onReset}
    />
  )
  expect(screen.getByTestId('classify-indicator').textContent).toContain('(you)')
  fireEvent.click(screen.getByTestId('classify-indicator'))
  fireEvent.click(screen.getByRole('button', { name: /reset/i }))
  expect(onReset).toHaveBeenCalled()
})
