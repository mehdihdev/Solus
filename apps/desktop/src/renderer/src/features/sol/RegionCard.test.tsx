// SOLUSDEV-252 S3: the circled-region card — crop from memory, caption as text.
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RegionCard } from './RegionCard'
import { SOL_REGION } from './solWindow.fixtures'

describe('RegionCard', () => {
  it('renders the crop as a data URL with the source caption and the ask', () => {
    const onAsk = vi.fn()
    render(<RegionCard region={SOL_REGION} onAsk={onAsk} />)
    expect(screen.getByRole('img', { name: 'Circled screen region' })).toHaveAttribute(
      'src',
      `data:image/png;base64,${SOL_REGION.pngBase64}`
    )
    expect(screen.getByText('Onshape — Bracket v3')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'What do you think this is?' }))
    expect(onAsk).toHaveBeenCalledTimes(1)
  })

  it('renders a hostile window title as text, never markup', () => {
    render(
      <RegionCard
        region={{ ...SOL_REGION, source: { app: 'X', title: '<img src=x onerror=alert(1)>' } }}
        onAsk={vi.fn()}
      />
    )
    expect(screen.getByText('X — <img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(document.querySelectorAll('img')).toHaveLength(1) // the crop only
  })

  it('omits the caption when the source window is unknown', () => {
    render(<RegionCard region={{ ...SOL_REGION, source: null }} onAsk={vi.fn()} />)
    expect(screen.queryByText(/—/)).not.toBeInTheDocument()
  })
})
