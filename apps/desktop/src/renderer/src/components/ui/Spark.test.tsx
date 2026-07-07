import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { Spark } from './Spark'

describe('Spark', () => {
  it('renders a polyline for the series', () => {
    const { container } = render(<Spark values={[1, 3, 2, 5]} />)
    expect(container.querySelector('polyline')).not.toBeNull()
  })

  it('renders an empty svg when there is not enough data', () => {
    const { container } = render(<Spark values={[1]} />)
    expect(container.querySelector('polyline')).toBeNull()
    expect(container.querySelector('svg')).not.toBeNull()
  })
})
