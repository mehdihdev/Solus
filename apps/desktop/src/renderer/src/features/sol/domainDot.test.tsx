// The dot itself; the domain and citation readers it is drawn from are tested in domainIds.test.ts.
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DomainDot } from './domainDot'

describe('domainDot', () => {
  it('renders no dot without a domain', () => {
    const { container, rerender } = render(<DomainDot d={null} />)
    expect(container.firstChild).toBeNull()
    rerender(<DomainDot d="ee" />)
    expect(container.firstElementChild).toHaveStyle({ background: 'var(--ee)' })
  })
})
