import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { GuideTour, type TourState } from './GuideTour'

function makeTour(steps: TourState['steps'], idx = 0, advance = vi.fn()): TourState {
  return { steps, idx, advance }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('GuideTour', () => {
  it('renders the step text and counter even when the target is missing', () => {
    const tour = makeTour([
      { target: '#does-not-exist', text: 'Alerts live here.', action: null },
      { target: '#also-missing', text: 'Second step.', action: null }
    ])
    render(<GuideTour tour={tour} onEnd={vi.fn()} />)
    expect(screen.getByText('Alerts live here.')).toBeInTheDocument()
    expect(screen.getByText(/STEP 1 OF 2/)).toBeInTheDocument()
  })

  it('advances with Next and finishes with Done', () => {
    const advance = vi.fn()
    const onEnd = vi.fn()
    const steps: TourState['steps'] = [
      { target: '#missing-a', text: 'First.', action: null },
      { target: '#missing-b', text: 'Last.', action: null }
    ]
    const { rerender } = render(<GuideTour tour={makeTour(steps, 0, advance)} onEnd={onEnd} />)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(advance).toHaveBeenCalledTimes(1)
    expect(onEnd).not.toHaveBeenCalled()
    rerender(<GuideTour tour={makeTour(steps, 1, advance)} onEnd={onEnd} />)
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onEnd).toHaveBeenCalledTimes(1)
  })

  it('clicks the target and finishes for a click-action final step', () => {
    vi.useFakeTimers()
    const targetClick = vi.fn()
    render(<button id="tour-target" onClick={targetClick} />)
    const onEnd = vi.fn()
    render(
      <GuideTour
        tour={makeTour([{ target: '#tour-target', text: 'Click it.', action: 'click' }])}
        onEnd={onEnd}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Do it for me' }))
    expect(targetClick).toHaveBeenCalledTimes(1)
    act(() => {
      vi.advanceTimersByTime(700)
    })
    expect(onEnd).toHaveBeenCalledTimes(1)
  })

  it('does not crash on a click-action step whose target is missing', () => {
    vi.useFakeTimers()
    const advance = vi.fn()
    render(
      <GuideTour
        tour={makeTour(
          [
            { target: '#gone', text: 'Missing.', action: 'click' },
            { target: '#gone-too', text: 'Next one.', action: null }
          ],
          0,
          advance
        )}
        onEnd={vi.fn()}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Do it for me' }))
    act(() => {
      vi.advanceTimersByTime(700)
    })
    expect(advance).toHaveBeenCalledTimes(1)
  })

  it('ends the tour from the End tour button', () => {
    const onEnd = vi.fn()
    render(
      <GuideTour
        tour={makeTour([{ target: '#missing', text: 'Step.', action: null }])}
        onEnd={onEnd}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'End tour' }))
    expect(onEnd).toHaveBeenCalledTimes(1)
  })

  it('renders nothing when the index is past the last step', () => {
    const { container } = render(
      <GuideTour
        tour={makeTour([{ target: '#missing', text: 'Step.', action: null }], 1)}
        onEnd={vi.fn()}
      />
    )
    expect(container.firstChild).toBeNull()
  })
})
